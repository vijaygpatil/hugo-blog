---
title: "SQS Long-Polling, Graceful Shutdown, and DLQ Recovery"
date: 2018-09-12
draft: false
tags: ["aws", "sqs", "java", "spring-boot", "microservices", "messaging", "concurrency"]
description: "How we built reliable SQS message processing in a Spring Boot microservice — long-polling configuration, a thread-pool worker model, graceful shutdown on application stop, and dead-letter queue recovery."
---

When we moved our notification pipeline to SQS, the basic pattern — poll for messages, process, delete — took about an afternoon to implement. Making it reliable took considerably longer. This post is about the non-obvious parts: long-polling configuration, managing worker threads, shutting down cleanly, and recovering from failures via dead-letter queues.

## Why SQS for Async Processing

Our notification service needed to process events asynchronously, decouple from the upstream systems producing events, and handle backpressure naturally when processing slows down. SQS ticked every box. The producer drops a message onto the queue and forgets about it. The consumer picks it up at its own pace.

The challenge with SQS is that "reliable" means more than just reading messages. It means not losing messages when a pod restarts, not processing the same message twice during slow periods, and recovering automatically when something goes wrong.

## Long-Polling

By default, SQS uses short-polling: it queries a subset of servers and returns immediately even if no messages are available. This is wasteful — you burn API calls and incur latency between polls.

Long-polling tells SQS to wait up to N seconds before returning if the queue is empty. This dramatically reduces empty responses and lowers costs.

```yaml
# application.yml
aws:
  sqs:
    wait-time-seconds: 20
    max-number-of-messages: 10
    polling-delay-ms: 5000
    initial-delay-ms: 10000
    worker-count: 8
    worker-shutdown-wait-seconds: 90
```

The `wait-time-seconds: 20` is the maximum SQS supports. Unless you have a specific reason to use a lower value, set it to 20.

`max-number-of-messages: 10` is also the maximum SQS allows per receive call. Batching reduces API calls and improves throughput.

## The Worker Model

We use a two-tier thread pool. The outer pool — the polling layer — has one thread per "worker". Each polling thread makes a `ReceiveMessage` call and gets back up to 10 messages. The inner pool — the processing layer — runs the actual message handling concurrently.

```java
@Component
public class MessageConsumerService {

    private final AmazonSQS sqsClient;
    private final MessageProcessor processor;
    private final SqsProperties properties;
    private final ScheduledExecutorService pollingExecutor;
    private final ExecutorService processingExecutor;
    private volatile boolean shutdown = false;

    public MessageConsumerService(AmazonSQS sqsClient,
                                  MessageProcessor processor,
                                  SqsProperties properties) {
        this.sqsClient = sqsClient;
        this.processor = processor;
        this.properties = properties;
        this.pollingExecutor = Executors.newScheduledThreadPool(properties.getWorkerCount());
        this.processingExecutor = Executors.newFixedThreadPool(10);
    }

    @PostConstruct
    public void start() {
        for (int i = 0; i < properties.getWorkerCount(); i++) {
            pollingExecutor.scheduleWithFixedDelay(
                this::pollAndProcess,
                properties.getInitialDelayMs(),
                properties.getPollingDelayMs(),
                TimeUnit.MILLISECONDS
            );
        }
    }

    private void pollAndProcess() {
        if (shutdown) return;

        ReceiveMessageRequest request = new ReceiveMessageRequest(properties.getQueueUrl())
            .withWaitTimeSeconds(properties.getWaitTimeSeconds())
            .withMaxNumberOfMessages(properties.getMaxNumberOfMessages());

        List<Message> messages;
        try {
            messages = sqsClient.receiveMessage(request).getMessages();
        } catch (AmazonClientException e) {
            log.error("Failed to receive messages from SQS", e);
            return;
        }

        if (shutdown) return;  // check again after the long-poll returns

        for (Message message : messages) {
            processingExecutor.submit(() -> handleMessage(message));
        }
    }
}
```

The double shutdown check matters. The long-poll blocks for up to 20 seconds. You check before the poll so you don't start new work during shutdown. You check after because shutdown may have been signalled while you were waiting.

## Visibility Timeout

When SQS delivers a message to a consumer, it makes it invisible to other consumers for the visibility timeout period. If you don't delete the message before the timeout expires, SQS assumes your consumer failed and makes the message visible again for redelivery.

This creates a window: your visibility timeout must be longer than your worst-case processing time. If processing takes 5 minutes but your visibility timeout is 3 minutes, the same message will be processed twice.

We set the visibility timeout in the CloudFormation template at 2 minutes and enforced a per-message processing timeout in code:

```java
private void handleMessage(Message message) {
    Future<?> future = processingExecutor.submit(() -> {
        try {
            processor.process(message);
            deleteMessage(message);
        } catch (Exception e) {
            log.error("Failed to process message {}", message.getMessageId(), e);
            // Do not delete — let it become visible again for retry
        }
    });

    try {
        future.get(2, TimeUnit.MINUTES);
    } catch (TimeoutException e) {
        future.cancel(true);
        log.error("Processing timed out for message {}", message.getMessageId());
        // Do not delete — let it become visible again
    } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
    } catch (ExecutionException e) {
        log.error("Execution failed for message {}", message.getMessageId());
    }
}
```

The key rule: only delete the message after successful processing. If processing fails or times out, let the message become visible again and retry.

## Retry with Backoff

Transient failures — downstream service unavailable, database briefly unreachable — should be retried. But retrying immediately hammers the failing dependency and makes things worse.

```java
private void deleteMessage(Message message) {
    int maxRetries = 3;
    long backoffMs = 3000;

    for (int attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            sqsClient.deleteMessage(properties.getQueueUrl(), message.getReceiptHandle());
            return;
        } catch (AmazonSQSException e) {
            if (attempt == maxRetries) {
                log.error("Failed to delete message after {} attempts", maxRetries, e);
                return;
            }
            log.warn("Delete attempt {} failed, retrying in {}ms", attempt, backoffMs);
            sleep(backoffMs);
            backoffMs *= 2;  // exponential backoff: 3s, 6s, 12s
        }
    }
}
```

We also handle malformed messages explicitly. A message that can't be parsed is acknowledged (deleted) rather than left to block the queue. These get logged separately so they can be investigated without disrupting normal processing.

## Graceful Shutdown

The naive shutdown problem: the JVM exits, the polling threads are killed mid-flight, and messages that were received but not yet deleted become visible again after their visibility timeout. This results in duplicate processing.

The correct approach is to signal shutdown before the JVM exits, allow in-flight processing to complete, then shut down the executor pools.

Spring's `ContextClosedEvent` fires when the application context is being closed — before the JVM exits. We listen for it:

```java
@Component
public class GracefulShutdownService implements ApplicationListener<ContextClosedEvent> {

    private final MessageConsumerService consumerService;
    private final int shutdownWaitSeconds;

    @Override
    public void onApplicationEvent(ContextClosedEvent event) {
        log.info("Application shutdown initiated — stopping message polling");
        consumerService.initiateShutdown();

        try {
            boolean completed = consumerService.awaitShutdown(shutdownWaitSeconds, TimeUnit.SECONDS);
            if (!completed) {
                log.warn("Shutdown timed out after {}s — some messages may be reprocessed",
                    shutdownWaitSeconds);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.warn("Shutdown interrupted");
        }
    }
}
```

And in the consumer service:

```java
public void initiateShutdown() {
    shutdown = true;
    pollingExecutor.shutdown();
}

public boolean awaitShutdown(long timeout, TimeUnit unit) throws InterruptedException {
    boolean pollingDone = pollingExecutor.awaitTermination(timeout, unit);
    processingExecutor.shutdown();
    boolean processingDone = processingExecutor.awaitTermination(timeout, unit);
    return pollingDone && processingDone;
}
```

The `volatile boolean shutdown` ensures the flag is visible across threads without additional synchronisation overhead. The wait on shutdown is 90 seconds in our production environment — long enough for in-flight messages to finish processing under normal conditions.

## Dead-Letter Queues

SQS supports dead-letter queues: a second queue where messages are moved after a configurable number of failed delivery attempts. This is configured at the queue level, not in application code.

```yaml
# CloudFormation snippet (simplified)
MainQueue:
  Type: AWS::SQS::Queue
  Properties:
    VisibilityTimeout: 120
    RedrivePolicy:
      deadLetterTargetArn: !GetAtt DeadLetterQueue.Arn
      maxReceiveCount: 3

DeadLetterQueue:
  Type: AWS::SQS::Queue
  Properties:
    MessageRetentionPeriod: 1209600  # 14 days
```

`maxReceiveCount: 3` means: after the message has been received and not deleted 3 times, SQS moves it to the DLQ. This catches messages that consistently fail processing without requiring any code changes.

A CloudWatch alarm on the DLQ depth ensures we're notified when messages land there:

```yaml
DLQAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    MetricName: ApproximateNumberOfMessagesVisible
    Namespace: AWS/SQS
    Dimensions:
      - Name: QueueName
        Value: !GetAtt DeadLetterQueue.QueueName
    Threshold: 1
    ComparisonOperator: GreaterThanOrEqualToThreshold
    EvaluationPeriods: 1
    Period: 60
    Statistic: Sum
    TreatMissingData: notBreaching
```

## DLQ Recovery

Messages in the DLQ are not lost — they sit there for up to 14 days. When an alarm fires, the investigation follows a standard pattern:

1. Pull a sample of messages from the DLQ to understand the failure mode
2. Check logs around the time of first failure (SQS includes the original `ApproximateFirstReceiveTimestamp` attribute)
3. Fix the root cause (a code bug, a configuration issue, a dependency that was down)
4. Redrive the messages back to the main queue for reprocessing

The AWS console has a redrive option. For scripted recovery:

```bash
# Move messages from DLQ back to main queue
aws sqs send-message \
  --queue-url $MAIN_QUEUE_URL \
  --message-body "$(aws sqs receive-message \
    --queue-url $DLQ_URL \
    --query 'Messages[0].Body' \
    --output text)"
```

For bulk redrive, the SQS console's "Start DLQ redrive" feature is more practical than scripting it.

## What Bit Us

A few things that weren't obvious when we started:

**Visibility timeout too short** — our first implementation set it to 30 seconds. Processing occasionally took longer under load, leading to duplicate processing. The fix was setting it to 2 minutes and enforcing the processing timeout in code to match.

**Not checking shutdown after long-poll** — the first version only checked `shutdown` at the top of the polling loop. During a deployment, the long-poll would block for up to 20 seconds, delay shutdown, and cause the Kubernetes termination grace period to kill the process anyway. Adding the post-poll check reduced shutdown time significantly.

**DLQ messages ageing out unnoticed** — in the early months we had the DLQ configured but no alarm on it. Messages landed there and sat for days before anyone noticed. The CloudWatch alarm was added after we found a backlog of messages that should have been processed.

**Malformed messages looping** — before we added explicit handling for parse failures, a malformed message would fail processing, become visible again, be received again, and loop indefinitely until it hit `maxReceiveCount`. Now we detect parse failures early and delete the message (while logging it), so it doesn't consume retry budget meant for transient failures.

---

The patterns here aren't specific to any one service. They apply to any SQS-based consumer: long-poll at 20 seconds, set visibility timeout to cover your worst-case processing time, always check shutdown before and after the poll, and use a DLQ with an alarm rather than hoping nothing goes wrong.

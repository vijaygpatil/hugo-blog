---
title: "Graceful Shutdown and Kubernetes Readiness in Spring Boot"
date: 2022-03-18
draft: false
tags: ["java", "spring-boot", "kubernetes", "microservices", "reliability", "devops"]
description: "How to implement graceful shutdown correctly in a Spring Boot microservice running on Kubernetes — coordinating the readiness endpoint, Spring's built-in graceful shutdown, and the ContextClosedEvent to drain in-flight work before the pod terminates."
---

Terminating a pod without losing in-flight work requires more than just setting `terminationGracePeriodSeconds` to a large number and hoping for the best. There is a specific sequence of events between Kubernetes issuing a termination signal and the JVM exiting, and if your application is not aware of that sequence, you will lose requests.

This post covers how to implement graceful shutdown correctly in a Spring Boot 2.6.x microservice on Kubernetes — the readiness probe, Spring's built-in graceful shutdown, and `ContextClosedEvent` for coordinating your own threads.

## The Problem

When Kubernetes terminates a pod, the sequence is:

1. Pod is removed from the `Endpoints` object — load balancers and service meshes stop routing new traffic to it
2. SIGTERM is sent to the container process
3. The pod has `terminationGracePeriodSeconds` to finish in-flight work and exit cleanly
4. After the grace period, SIGKILL is sent and the process is forcibly terminated

The gap between steps 1 and 2 is not instantaneous. The load balancer update propagates asynchronously, and requests in flight at the moment SIGTERM arrives may still be in the middle of processing. If your application exits immediately on SIGTERM, those requests fail.

The additional problem: your application may have background threads — queue consumers, batch workers, scheduled tasks — that are mid-processing when the signal arrives. Killing them abruptly can leave data in an inconsistent state.

## Spring Boot's Built-In Graceful Shutdown

Since Spring Boot 2.3, you can enable graceful shutdown with two properties:

```yaml
# application.yml
server:
  shutdown: graceful

spring:
  lifecycle:
    timeout-per-shutdown-phase: 120s
```

`server.shutdown: graceful` tells the embedded web server (Tomcat, Undertow, Netty) to stop accepting new requests on SIGTERM but allow in-flight HTTP requests to complete.

`timeout-per-shutdown-phase: 120s` is how long Spring waits for each lifecycle phase to complete before moving on. If you have requests that can run for up to two minutes, set this to at least that.

This handles the web layer. It does not handle your own `ExecutorService` instances, message queue consumers, or background threads — those require additional coordination.

## The Readiness Probe and Why It Matters

Kubernetes uses two probes to manage pod health:

- **Liveness probe**: Is the process alive? Failure triggers a restart.
- **Readiness probe**: Should traffic be sent here? Failure removes the pod from rotation without restarting it.

For graceful shutdown, the readiness probe is the critical one. When your readiness probe fails, the load balancer stops sending new requests to this pod. If you fail the readiness probe *before* SIGTERM arrives, you buy time for in-flight requests to drain without new ones arriving.

A minimal readiness endpoint:

```java
@RestController
public class ReadinessController {

    private final ShutdownCoordinator shutdownCoordinator;

    @GetMapping("/internal/ready")
    public ResponseEntity<String> ready() {
        if (shutdownCoordinator.isShuttingDown()) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body("Shutting down");
        }
        return ResponseEntity.ok("Ready");
    }
}
```

The Kubernetes probe configuration to match:

```yaml
# Kubernetes deployment spec
readinessProbe:
  httpGet:
    path: /internal/ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 1
```

`failureThreshold: 1` means a single non-200 response removes the pod from rotation immediately. This is intentional — during shutdown you want traffic to stop as fast as possible.

## The Shutdown Coordinator

The central class coordinates shutdown state across the readiness endpoint, background threads, and the Spring lifecycle event:

```java
@Component
public class ShutdownCoordinator implements ApplicationListener<ContextClosedEvent> {

    private static final Logger log = LoggerFactory.getLogger(ShutdownCoordinator.class);

    private volatile boolean shuttingDown = false;

    @Override
    public void onApplicationEvent(ContextClosedEvent event) {
        log.info("Application shutdown initiated");
        shuttingDown = true;
    }

    public synchronized boolean isShuttingDown() {
        return shuttingDown;
    }
}
```

`ContextClosedEvent` fires when Spring begins closing the application context — triggered by SIGTERM reaching the JVM. At this point:

- The readiness endpoint starts returning `503`, causing Kubernetes to remove the pod from rotation
- Background workers check `isShuttingDown()` before starting new work
- Spring's built-in graceful shutdown drains the HTTP thread pool

`volatile` on `shuttingDown` ensures visibility across threads without full synchronisation on every read. The setter path uses `synchronized` because it's called once and the guarantee matters there.

## Coordinating Background Threads

Background workers — queue consumers, batch processors — need to check the shutdown flag before starting a new unit of work:

```java
@Component
public class MessageWorker {

    private final ShutdownCoordinator shutdownCoordinator;

    private void pollAndProcess() {
        if (shutdownCoordinator.isShuttingDown()) {
            return;  // do not start new work during shutdown
        }

        List<Message> messages = receiveMessages();  // long-poll — may block up to 20s

        if (shutdownCoordinator.isShuttingDown()) {
            return;  // check again after the blocking call returns
        }

        for (Message message : messages) {
            processingExecutor.submit(() -> handle(message));
        }
    }
}
```

The double check — before and after any blocking call — matters because a long-poll can block for tens of seconds. Shutdown may be initiated while the thread is blocked. Without the post-poll check, the worker would start processing a fresh batch of messages during shutdown.

## Waiting for In-Flight Work to Finish

Setting the shutdown flag stops new work from starting. It does not wait for work that is already running. For background threads with their own `ExecutorService`, you need to shut those down explicitly.

Spring's `@PreDestroy` is the right hook — it runs after `ContextClosedEvent` and before the context is destroyed:

```java
@Component
public class MessageConsumerService {

    private final ExecutorService processingExecutor =
        Executors.newFixedThreadPool(10);

    @PreDestroy
    public void shutdown() throws InterruptedException {
        log.info("Stopping message processing executor");
        processingExecutor.shutdown();

        boolean completed = processingExecutor.awaitTermination(90, TimeUnit.SECONDS);
        if (!completed) {
            log.warn("Processing executor did not terminate cleanly — forcing shutdown");
            processingExecutor.shutdownNow();
        }
    }
}
```

The `awaitTermination` timeout should be less than `spring.lifecycle.timeout-per-shutdown-phase` so Spring does not kill the context before your threads finish.

## The Complete Shutdown Sequence

With everything wired together, the shutdown sequence is:

```
1. SIGTERM received by JVM
2. Spring fires ContextClosedEvent
3. ShutdownCoordinator.shuttingDown = true
4. Readiness endpoint starts returning 503
5. Kubernetes removes pod from load balancer rotation (within one probe period: ~5s)
6. Background workers finish current unit of work, do not start new work
7. @PreDestroy shuts down processing executor, waits up to 90s for threads to drain
8. Spring's web layer drains remaining HTTP requests (timeout-per-shutdown-phase: 120s)
9. Spring closes application context and JVM exits
```

The Kubernetes `terminationGracePeriodSeconds` should cover the longest of these: `120s` for the HTTP drain is the upper bound, so `terminationGracePeriodSeconds: 150` gives a reasonable buffer.

```yaml
# Kubernetes deployment spec
spec:
  terminationGracePeriodSeconds: 150
  containers:
    - name: app
      lifecycle:
        preStop:
          exec:
            command: ["sh", "-c", "sleep 5"]  # brief pause before SIGTERM
```

The `preStop` sleep gives the load balancer a moment to propagate the readiness failure before SIGTERM arrives. Without it, the race between endpoint propagation and SIGTERM can still result in a few dropped requests.

## What Happens Without This

Without graceful shutdown:

- SIGTERM → JVM exits immediately → all in-flight HTTP requests get a connection reset
- Queue consumer threads are killed mid-processing → messages become visible again after the visibility timeout (at best, duplicate processing; at worst, data corruption if the processing was partially committed)
- Kubernetes readiness failure propagates slowly → new requests arrive after SIGTERM, fail immediately

With graceful shutdown, a rolling deployment or a pod restart is invisible to clients. Without it, every deployment causes a brief error spike.

---

The configuration is small — a few properties, two classes, one readiness endpoint. The sequence it implements is what separates deployments that are transparent to users from ones that cause brief but visible errors.

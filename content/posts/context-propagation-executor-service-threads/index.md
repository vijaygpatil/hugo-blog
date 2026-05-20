---
title: "Context Propagation Across Thread Boundaries in Spring Boot"
date: 2023-08-15
draft: false
tags: ["java", "spring-boot", "concurrency", "threading", "microservices", "observability"]
description: "How to propagate request context — tenant scope, MDC fields, Spring request attributes — across thread boundaries when submitting work to executor service thread pools, using a wrapper that captures and restores context automatically."
---

Spring Boot's request-scoped beans and thread-local state — MDC fields, `RequestContextHolder` attributes, tenant identifiers — work automatically on the thread that handles an HTTP request. They do not automatically cross thread boundaries. When you submit a task to an `ExecutorService`, the worker thread starts with empty context.

This matters because anything logged or traced from the worker thread loses the correlation ID, the tenant identifier, and any other context that would make the log entry queryable in production. For multitenant services, it also means tenant-scoped state is simply absent on the worker thread, which can cause wrong-data bugs if the code assumes it is set.

This post covers a wrapper pattern that captures all of that context before task submission and restores it on the worker thread.

## The Problem

```java
// On the HTTP request thread:
MDC.put("correlation_id", correlationId);  // set
EntityScope.set(tenantId);                  // set

// Worker thread sees none of this:
executor.submit(() -> {
    MDC.get("correlation_id");  // null
    EntityScope.get();          // null
    log.info("Processing");     // log line has no correlation_id
});
```

The fix requires three operations: capture the current context before `submit()`, set it on the worker thread before the task runs, and clear it when the task finishes.

## Dependencies

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-web:3.1.2'
implementation 'io.micrometer:micrometer-core:1.11.3'
```

Java 17. Micrometer is used for thread pool metrics.

## The Context Capture Interface

Define the capture, restore, and clear contract:

```java
public interface ContextAwareExecutable {

    void initContext();

    void clearContext();

    Runnable wrap(Runnable task);

    default <T> Callable<T> wrap(Callable<T> task) {
        return () -> {
            initContext();
            try {
                return task.call();
            } finally {
                clearContext();
            }
        };
    }
}
```

And a concrete implementation that handles the three context types we need to propagate:

```java
@Component
@Scope("prototype")
public class RequestContextCapture implements ContextAwareExecutable {

    private final Map<String, String> mdcCopy;
    private final Object requestAttributes;
    private final String tenantId;

    public RequestContextCapture() {
        // Capture at construction time (on the submitting thread)
        this.mdcCopy = MDC.getCopyOfContextMap();
        this.requestAttributes = RequestContextHolder.getRequestAttributes();
        this.tenantId = EntityScope.get();  // thread-local tenant identifier
    }

    @Override
    public void initContext() {
        if (mdcCopy != null) {
            MDC.setContextMap(mdcCopy);
        }
        if (requestAttributes != null) {
            RequestContextHolder.setRequestAttributes(
                (RequestAttributes) requestAttributes, true);
        }
        if (tenantId != null) {
            EntityScope.set(tenantId);
        }
    }

    @Override
    public void clearContext() {
        MDC.clear();
        RequestContextHolder.resetRequestAttributes();
        EntityScope.clear();
    }

    @Override
    public Runnable wrap(Runnable task) {
        return () -> {
            initContext();
            try {
                task.run();
            } finally {
                clearContext();
            }
        };
    }
}
```

The prototype scope ensures a fresh capture instance per submission — if you used singleton scope and reused the same instance, concurrent tasks would share one context snapshot.

## The Context-Aware Executor Service

Wrapping `ExecutorService` to apply the capture automatically:

```java
public class ContextAwareExecutorService implements ExecutorService {

    private final ExecutorService delegate;
    private final Provider<RequestContextCapture> captureProvider;

    public ContextAwareExecutorService(ExecutorService delegate,
                                       Provider<RequestContextCapture> captureProvider) {
        this.delegate = delegate;
        this.captureProvider = captureProvider;
    }

    @Override
    public Future<?> submit(Runnable task) {
        RequestContextCapture capture = captureProvider.get();
        return delegate.submit(capture.wrap(task));
    }

    @Override
    public <T> Future<T> submit(Callable<T> task) {
        RequestContextCapture capture = captureProvider.get();
        return delegate.submit(capture.wrap(task));
    }

    @Override
    public void execute(Runnable command) {
        RequestContextCapture capture = captureProvider.get();
        delegate.execute(capture.wrap(command));
    }

    // Delegate remaining ExecutorService methods to delegate directly
    @Override public void shutdown() { delegate.shutdown(); }
    @Override public List<Runnable> shutdownNow() { return delegate.shutdownNow(); }
    @Override public boolean isShutdown() { return delegate.isShutdown(); }
    @Override public boolean isTerminated() { return delegate.isTerminated(); }
    @Override public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        return delegate.awaitTermination(timeout, unit);
    }
    @Override public <T> List<Future<T>> invokeAll(Collection<? extends Callable<T>> tasks) throws InterruptedException {
        return delegate.invokeAll(tasks.stream().map(t -> captureProvider.get().wrap(t)).toList());
    }
    @Override public <T> T invokeAny(Collection<? extends Callable<T>> tasks) throws ExecutionException, InterruptedException {
        return delegate.invokeAny(tasks.stream().map(t -> captureProvider.get().wrap(t)).toList());
    }
}
```

## Wiring Up Multiple Pools

Production services often have more than one executor pool — different pools for different work categories, each with its own sizing. Register them as beans:

```java
@Configuration
public class ExecutorConfiguration {

    @Bean("processingExecutor")
    public ExecutorService processingExecutor(Provider<RequestContextCapture> captureProvider) {
        ExecutorService pool = Executors.newFixedThreadPool(100);
        ExecutorServiceMetrics.monitor(Metrics.globalRegistry, pool, "processing");
        return new ContextAwareExecutorService(pool, captureProvider);
    }

    @Bean("metricsExecutor")
    public ExecutorService metricsExecutor(Provider<RequestContextCapture> captureProvider) {
        ExecutorService pool = Executors.newFixedThreadPool(10);
        ExecutorServiceMetrics.monitor(Metrics.globalRegistry, pool, "metrics");
        return new ContextAwareExecutorService(pool, captureProvider);
    }
}
```

`ExecutorServiceMetrics.monitor()` registers the pool with Micrometer, exposing active count, queue size, and completed task count as metrics. This is three characters of overhead per pool definition and gives you visibility into thread pool saturation without additional instrumentation.

## Using It

Injection and use are identical to a plain `ExecutorService`:

```java
@Service
public class BatchProcessingService {

    @Qualifier("processingExecutor")
    private final ExecutorService processingExecutor;

    public void processItems(List<Item> items) {
        List<Future<?>> futures = items.stream()
            .map(item -> processingExecutor.submit(() -> process(item)))
            .toList();

        for (Future<?> future : futures) {
            try {
                future.get(30, TimeUnit.SECONDS);
            } catch (TimeoutException | ExecutionException e) {
                log.error("Item processing failed", e);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private void process(Item item) {
        // MDC fields, EntityScope, request attributes are all available here
        log.info("Processing item {}", item.getId());  // correlation_id in log
    }
}
```

No changes to the task code. Context propagation is entirely in the executor wrapper.

## What Gets Propagated

**MDC fields** — correlation IDs, batch identifiers, tenant identifiers added via `MDC.put()`. These appear on every log line the worker thread writes.

**Spring RequestAttributes** — `RequestContextHolder` state, which includes things like request-scoped beans. The `inheritable=true` argument to `setRequestAttributes()` makes child threads of the worker also inherit the context, relevant if the task itself spawns more threads.

**EntityScope** — a thread-local tenant identifier. Services with multiple tenants depend on this to scope database queries and cache lookups. Without it, a worker thread processing tenant A's data could inadvertently use tenant B's scope if a previous task left stale state.

## What Happens on Cleanup Failure

The `finally` block in `wrap()` ensures context is cleared even when the task throws. Without this, a thread pool thread that threw an exception would carry stale MDC fields into its next task. If the pool has a fixed size of 100 threads and each thread processes thousands of tasks over its lifetime, a stale context leak would be subtle and hard to diagnose — tasks would log under the wrong correlation ID for the duration of the JVM process.

## Considerations for Background Tasks

For tasks submitted outside a request context — scheduled jobs, startup initialization — `RequestContextHolder.getRequestAttributes()` returns null and `EntityScope.get()` may also return null. The `initContext()` method guards against this with null checks, so the worker thread simply starts with no context rather than throwing. Log those paths with their own identifying fields rather than expecting request-level context.

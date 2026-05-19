---
title: "Resilience4j with Custom Context Propagators in Spring Boot 3"
date: 2025-03-10
draft: false
tags: ["java", "spring-boot", "resilience4j", "microservices", "reliability", "circuit-breaker", "concurrency"]
description: "How to configure Resilience4j circuit breakers, bulkheads, and time limiters with custom ContextPropagators to carry tenant scope and MDC fields through async operations — so resilience decorators don't silently discard your request context."
---

Resilience4j's async decorators — `TimeLimiter`, `Bulkhead` — run your code on a different thread. That thread does not automatically have your MDC fields, tenant identifier, or other thread-local state. The result: a log line written inside a resilience decorator has no correlation ID, and a tenant-scoped database call fails because the scope is absent.

Resilience4j solves this with `ContextPropagator`: a three-method interface you implement to define what gets captured, copied, and cleared around thread boundaries. This post covers the implementation and wiring.

## Dependencies

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-web:3.4.3'
implementation 'io.github.resilience4j:resilience4j-spring-boot3:2.3.0'
implementation 'io.github.resilience4j:resilience4j-circuitbreaker:2.3.0'
implementation 'io.github.resilience4j:resilience4j-timelimiter:2.3.0'
implementation 'io.github.resilience4j:resilience4j-bulkhead:2.3.0'
```

Java 21. Resilience4j 2.3.0 requires Spring Boot 3.x.

## The ContextPropagator Interface

```java
public interface ContextPropagator<T> {
    Supplier<Optional<T>> retrieve();
    UnaryOperator<Optional<T>> copy();
    Consumer<Optional<T>> clear();
}
```

The three methods map to three points in the task lifecycle:

- **`retrieve()`** — called on the submitting thread. Returns a `Supplier` that captures the current context.
- **`copy()`** — called on the worker thread before the task runs. Restores context from what `retrieve()` captured.
- **`clear()`** — called on the worker thread after the task finishes. Removes the context.

## Implementing EntityScope Propagation

For a tenant-scoped thread-local:

```java
@Component
public class EntityScopeContextPropagator implements ContextPropagator<String> {

    @Override
    public Supplier<Optional<String>> retrieve() {
        // Capture current tenant ID on the submitting thread
        String tenantId = EntityScope.get();
        return () -> Optional.ofNullable(tenantId);
    }

    @Override
    public UnaryOperator<Optional<String>> copy() {
        return tenantIdOptional -> {
            // Restore tenant ID on the worker thread
            tenantIdOptional.ifPresent(EntityScope::set);
            return tenantIdOptional;
        };
    }

    @Override
    public Consumer<Optional<String>> clear() {
        // Clean up after task completes
        return ignored -> EntityScope.clear();
    }
}
```

## Implementing MDC Propagation

```java
@Component
public class MdcContextPropagator implements ContextPropagator<Map<String, String>> {

    @Override
    public Supplier<Optional<Map<String, String>>> retrieve() {
        Map<String, String> mdcCopy = MDC.getCopyOfContextMap();
        return () -> Optional.ofNullable(mdcCopy);
    }

    @Override
    public UnaryOperator<Optional<Map<String, String>>> copy() {
        return mdcOptional -> {
            mdcOptional.ifPresent(MDC::setContextMap);
            return mdcOptional;
        };
    }

    @Override
    public Consumer<Optional<Map<String, String>>> clear() {
        return ignored -> MDC.clear();
    }
}
```

## Wiring Propagators in application.yml

Resilience4j reads `context-propagators` as a list of class names per instance. You can configure different propagators per backend:

```yaml
resilience4j:
  circuitbreaker:
    instances:
      external-config-api:
        sliding-window-type: TIME_BASED
        sliding-window-size: 5
        failure-rate-threshold: 50
        wait-duration-in-open-state: 10s
        permitted-number-of-calls-in-half-open-state: 3
        context-propagators:
          - com.example.service.resilience.EntityScopeContextPropagator
          - com.example.service.resilience.MdcContextPropagator
      payment-api:
        sliding-window-type: COUNT_BASED
        sliding-window-size: 10
        failure-rate-threshold: 60
        wait-duration-in-open-state: 30s
        context-propagators:
          - com.example.service.resilience.EntityScopeContextPropagator
          - com.example.service.resilience.MdcContextPropagator

  timelimiter:
    instances:
      external-config-api:
        timeout-duration: 5s
        cancel-running-future: true
      payment-api:
        timeout-duration: 10s

  bulkhead:
    instances:
      external-config-api:
        max-concurrent-calls: 20
        max-wait-duration: 500ms
      payment-api:
        max-concurrent-calls: 10
        max-wait-duration: 1s
```

## Using the Decorators

```java
@Service
public class ExternalConfigService {

    private final CircuitBreaker circuitBreaker;
    private final TimeLimiter timeLimiter;
    private final ScheduledExecutorService scheduler;
    private final RestClient configClient;

    public ExternalConfigService(CircuitBreakerRegistry cbRegistry,
                                 TimeLimiterRegistry tlRegistry) {
        this.circuitBreaker = cbRegistry.circuitBreaker("external-config-api");
        this.timeLimiter = tlRegistry.timeLimiter("external-config-api");
        this.scheduler = Executors.newScheduledThreadPool(5);
    }

    public ConfigResponse fetchConfig(String entityCode) {
        Supplier<CompletableFuture<ConfigResponse>> futureSupplier = () ->
            CompletableFuture.supplyAsync(() -> configClient.get()
                .uri("/config/{entityCode}", entityCode)
                .retrieve()
                .body(ConfigResponse.class), scheduler);

        try {
            return timeLimiter.executeFutureSupplier(
                circuitBreaker.decorateSupplier(futureSupplier));
        } catch (TimeoutException e) {
            log.warn("Config fetch timed out for {}", entityCode);
            return ConfigResponse.empty();
        } catch (CallNotPermittedException e) {
            log.warn("Circuit breaker open for external-config-api");
            return ConfigResponse.empty();
        } catch (Exception e) {
            log.error("Config fetch failed for {}", entityCode, e);
            return ConfigResponse.empty();
        }
    }
}
```

When `CompletableFuture.supplyAsync()` dispatches to the scheduler thread, the `EntityScopeContextPropagator` and `MdcContextPropagator` will have already set the context. The supplier runs with the full context of the calling thread.

## Annotation-Based Alternative

If you prefer the annotation style over programmatic decoration:

```java
@Service
public class ExternalConfigService {

    private final RestClient configClient;

    @CircuitBreaker(name = "external-config-api", fallbackMethod = "fetchConfigFallback")
    @TimeLimiter(name = "external-config-api")
    @Bulkhead(name = "external-config-api")
    public CompletableFuture<ConfigResponse> fetchConfig(String entityCode) {
        return CompletableFuture.supplyAsync(() -> configClient.get()
            .uri("/config/{entityCode}", entityCode)
            .retrieve()
            .body(ConfigResponse.class));
    }

    public CompletableFuture<ConfigResponse> fetchConfigFallback(
            String entityCode, Exception e) {
        log.warn("Falling back to empty config for {}: {}", entityCode, e.getMessage());
        return CompletableFuture.completedFuture(ConfigResponse.empty());
    }
}
```

The annotations use the same configuration from `application.yml`, including the `context-propagators` list. Context propagation happens transparently.

## Circuit Breaker Behaviour

The TIME_BASED sliding window counts failures within a time window rather than the last N calls. This is more appropriate for latency-sensitive dependencies: if a downstream service slows down and starts timing out in bursts, a time-based window opens the circuit faster than a count-based window of the same size.

The configuration above (`sliding-window-size: 5`, `failure-rate-threshold: 50`) means: if more than 50% of calls in the last 5 seconds failed, open the circuit. `wait-duration-in-open-state: 10s` is how long to stay open before allowing a probe call through (HALF_OPEN). `permitted-number-of-calls-in-half-open-state: 3` means allow 3 probe calls — if 2 or more succeed, close the circuit.

## What the Propagators Don't Cover

`ContextPropagator` handles thread boundaries within Resilience4j's async execution. It does not propagate context to:

- Threads spawned inside the task itself
- `@Async` Spring methods called from within the decorated code
- Reactive chains (Reactor/WebFlux)

For those cases you need the executor service wrapper pattern or Reactor's context propagation mechanisms. The Resilience4j propagators are specifically for the thread hop that the framework itself introduces.

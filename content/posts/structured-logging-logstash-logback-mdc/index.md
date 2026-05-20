---
title: "Structured Logging for Production Observability: Logstash-Logback and MDC"
date: 2021-09-14
draft: false
tags: ["java", "spring-boot", "logging", "logstash", "logback", "observability", "microservices", "elk"]
description: "How to set up structured JSON logging in a Spring Boot microservice using Logstash-Logback, and how to use MDC to propagate correlation IDs and processing context across threads — so your logs are actually queryable in production."
---

Plain-text logs are fine for reading on a laptop. They are not fine for production. When you have ten pods each writing thousands of lines per minute, you need logs that a tool can query — filter by correlation ID, aggregate by error type, trace a single request across services. That means JSON.

This post is about setting up structured logging in a Spring Boot microservice using `logstash-logback-encoder`, and using MDC (Mapped Diagnostic Context) to attach context to every log line a thread writes — without threading it through every method signature.

## Dependencies

```groovy
// build.gradle
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web'
    implementation 'net.logstash.logback:logstash-logback-encoder:6.6'
}
```

Spring Boot's default logging is Logback. `logstash-logback-encoder` adds JSON encoders and a `ShortenedThrowableConverter` for clean stack traces. No other logging framework changes needed.

## Profile-Based Configuration

The key constraint: developers want readable console output; production needs machine-parseable JSON. Spring's profile-based Logback configuration handles this cleanly.

```xml
<!-- src/main/resources/logback-spring.xml -->
<configuration>

  <!-- Dev profile: readable console output -->
  <springProfile name="dev">
    <appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">
      <encoder>
        <pattern>%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n</pattern>
      </encoder>
    </appender>

    <root level="INFO">
      <appender-ref ref="STDOUT"/>
    </root>
  </springProfile>

  <!-- Docker/production profile: structured JSON -->
  <springProfile name="docker">
    <appender name="STDOUT-JSON" class="ch.qos.logback.core.ConsoleAppender">
      <encoder class="net.logstash.logback.encoder.LoggingEventCompositeJsonEncoder">
        <providers>
          <timestamp>
            <fieldName>@timestamp</fieldName>
          </timestamp>
          <logLevel>
            <fieldName>level</fieldName>
          </logLevel>
          <loggerName>
            <fieldName>logger</fieldName>
            <shortenedLoggerNameLength>36</shortenedLoggerNameLength>
          </loggerName>
          <message>
            <fieldName>description</fieldName>
          </message>
          <mdc/>  <!-- all MDC fields appear at root level -->
          <stackTrace>
            <throwableConverter class="net.logstash.logback.stacktrace.ShortenedThrowableConverter">
              <maxDepthPerThrowable>75</maxDepthPerThrowable>
              <maxLength>12000</maxLength>
              <shortenedClassNameLength>200</shortenedClassNameLength>
              <rootCauseFirst>true</rootCauseFirst>
              <!-- suppress framework noise -->
              <exclude>sun\.reflect\..*\.invoke.*</exclude>
              <exclude>net\.sf\.cglib\.proxy\.MethodProxy\.invoke</exclude>
              <exclude>org\.springframework\..*</exclude>
              <exclude>org\.apache\.catalina\..*</exclude>
            </throwableConverter>
          </stackTrace>
        </providers>
      </encoder>
    </appender>

    <root level="INFO">
      <appender-ref ref="STDOUT-JSON"/>
    </root>
  </springProfile>

</configuration>
```

A few decisions worth explaining:

**`<message>` field named `description`** — the default is `message`, but `message` collides with the Elasticsearch built-in field. Naming it `description` avoids the conflict without any other changes.

**`<mdc/>`** — this single element includes every key currently in the MDC as a top-level JSON field. You don't enumerate them; anything you put into the MDC appears automatically.

**`ShortenedThrowableConverter`** — the default stack trace serialisation in JSON is verbose and noisy. `ShortenedThrowableConverter` trims it: `rootCauseFirst` puts the actual exception at the top rather than buried under framework frames, and the `<exclude>` patterns strip Spring and Tomcat internals that are never useful.

## What Is MDC?

MDC (Mapped Diagnostic Context) is a thread-local `Map<String, String>` maintained by the logging framework. When you write a log statement, Logback includes every key-value pair currently in the MDC alongside the message. You never have to pass a correlation ID through your method signatures — you put it in the MDC once and it appears on every subsequent log line that thread writes.

```java
// Put context in once
MDC.put("correlation_id", correlationId);
MDC.put("company_uuid", companyId);

// Every log statement on this thread now includes those fields
log.info("Starting batch processing");      // → includes correlation_id, company_uuid
log.info("Fetched {} records", count);      // → includes correlation_id, company_uuid
log.error("Processing failed", exception);  // → includes correlation_id, company_uuid

// Clean up when done
MDC.remove("correlation_id");
MDC.remove("company_uuid");
```

The critical rule: **always clear MDC fields when you're done with them**. Thread pools reuse threads, and MDC is thread-local. If you set a correlation ID on a thread and don't clear it, the next request handled by that thread will log under the previous correlation ID.

## Organising MDC Fields

For a service doing batch processing, there are several categories of context worth tracking. We group them by lifecycle:

```java
public final class MdcUtil {

    // Fields set for the duration of a processing job
    private static final List<String> BATCH_FIELDS = List.of(
        "correlation_id", "company_uuid", "batch_number",
        "reports_expected", "reports_completed", "reports_failed"
    );

    // Fields set per-request (API layer)
    private static final List<String> REQUEST_FIELDS = List.of(
        "correlation_id", "request_id", "request_uri",
        "request_method", "status_code", "duration_ms"
    );

    public static void setBatchContext(String correlationId, String companyUuid,
                                       int batchNumber, int reportsExpected) {
        MDC.put("correlation_id", correlationId);
        MDC.put("company_uuid", companyUuid);
        MDC.put("batch_number", String.valueOf(batchNumber));
        MDC.put("reports_expected", String.valueOf(reportsExpected));
        MDC.put("reports_completed", "0");
        MDC.put("reports_failed", "0");
    }

    public static void updateBatchProgress(int completed, int failed) {
        MDC.put("reports_completed", String.valueOf(completed));
        MDC.put("reports_failed", String.valueOf(failed));
    }

    public static void clearBatchContext() {
        BATCH_FIELDS.forEach(MDC::remove);
    }

    public static void setRequestContext(HttpServletRequest request, String correlationId) {
        MDC.put("correlation_id", correlationId);
        MDC.put("request_id", UUID.randomUUID().toString());
        MDC.put("request_uri", request.getRequestURI());
        MDC.put("request_method", request.getMethod());
    }

    public static void clearRequestContext() {
        REQUEST_FIELDS.forEach(MDC::remove);
    }

    private MdcUtil() {}
}
```

Grouping into `BATCH_FIELDS` / `REQUEST_FIELDS` lists makes clearing reliable — you can't accidentally miss a field.

## Setting Context at the Right Layer

For request-scoped context, a servlet filter is the right place: it runs before any application code, and the finally block ensures cleanup regardless of what happens in the handler.

```java
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class MdcFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain)
            throws ServletException, IOException {

        String correlationId = Optional
            .ofNullable(request.getHeader("X-Correlation-Id"))
            .orElse(UUID.randomUUID().toString());

        MdcUtil.setRequestContext(request, correlationId);
        response.setHeader("X-Correlation-Id", correlationId);

        try {
            chain.doFilter(request, response);
        } finally {
            MdcUtil.clearRequestContext();
        }
    }
}
```

For async or batch processing, set context at the point where you pick up the work item (e.g., when you dequeue an SQS message or start processing a batch record), and clear it in the finally block:

```java
private void processBatch(BatchRequest batch) {
    MdcUtil.setBatchContext(
        batch.correlationId(),
        batch.companyUuid(),
        batch.batchNumber(),
        batch.expectedCount()
    );
    try {
        doProcessing(batch);
    } finally {
        MdcUtil.clearBatchContext();
    }
}
```

## MDC and Thread Pools

MDC is thread-local, which means it does not propagate automatically to threads spawned by an `ExecutorService`. If you submit work to a thread pool inside a request handler, the worker thread starts with an empty MDC.

The fix is to capture the MDC before submitting and restore it in the worker:

```java
public void submitAsync(Runnable task) {
    Map<String, String> contextCopy = MDC.getCopyOfContextMap();

    executor.submit(() -> {
        if (contextCopy != null) {
            MDC.setContextMap(contextCopy);
        }
        try {
            task.run();
        } finally {
            MDC.clear();
        }
    });
}
```

`MDC.getCopyOfContextMap()` returns a snapshot of the current context. Setting it on the worker thread with `MDC.setContextMap()` means the worker's log lines carry the same correlation ID as the submitting thread.

## What This Looks Like in Production

A single log line in the JSON output:

```json
{
  "@timestamp": "2021-09-10T14:23:45.123Z",
  "level": "INFO",
  "logger": "c.e.d.service.BatchProcessingService",
  "description": "Batch processing complete",
  "correlation_id": "a3f2c891-44b1-4d2e-8c3f-1b2e3d4f5a6b",
  "company_uuid": "79c46d15-272e-4b22-b7bf-11a64b8e247f",
  "batch_number": "3",
  "reports_expected": "250",
  "reports_completed": "248",
  "reports_failed": "2"
}
```

In Kibana or any ELK-compatible tool, you can now:

- Filter by `correlation_id` to see every log line for a specific job across all pods
- Aggregate by `company_uuid` to see which tenants are generating failures
- Build a dashboard on `reports_failed` over time
- Alert when `reports_failed` exceeds a threshold

None of this is possible with plain-text logs at any reasonable scale.

## Checklist

- Use `LoggingEventCompositeJsonEncoder` in non-dev profiles; plain pattern layout in dev
- Name the message field `description` to avoid Elasticsearch collision
- Always pair every `MDC.put()` with a `MDC.remove()` (or `MDC.clear()`) in a finally block
- Group related MDC fields into lists for reliable bulk cleanup
- Capture and restore `MDC.getCopyOfContextMap()` when crossing thread boundaries
- Use `ShortenedThrowableConverter` with `rootCauseFirst=true` and exclude framework packages

---

The setup takes a few hours. Once it's in place, debugging a production issue changes from grepping log files to running a Kibana query. The difference in diagnosis time is not marginal.

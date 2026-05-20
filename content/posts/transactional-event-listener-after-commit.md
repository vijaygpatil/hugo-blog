---
title: "Reliable Event Publishing with @TransactionalEventListener"
date: 2025-03-10
draft: false
tags: ["java", "spring-boot", "events", "transactions", "microservices", "reliability"]
description: "How to publish domain events after a database transaction commits using Spring's @TransactionalEventListener — avoiding the lost-update problem, handling the fallbackExecution edge case, and keeping event context clean without coupling listeners to domain objects."
---

A common pattern in Spring applications is to publish an event when something changes — a report was submitted, a batch completed, a record was updated. The naive approach is to publish the event inside the service method that makes the change. This creates a timing problem.

If the event is published before the transaction commits, any listener that immediately reads the database sees the old state. If the transaction rolls back after the event is published, the event describes a change that did not happen. Neither outcome is correct.

`@TransactionalEventListener` solves this: it holds the event until after the transaction commits, then delivers it.

## The Timing Problem

```java
// Naive approach — event published before transaction commits
@Transactional
public void submitReport(String reportId) {
    reportRepository.updateStatus(reportId, Status.SUBMITTED);
    eventPublisher.publishEvent(new ReportSubmittedEvent(reportId));  // ← fires NOW, before commit
}

// If the listener immediately queries the database:
@EventListener
public void onReportSubmitted(ReportSubmittedEvent event) {
    Report report = reportRepository.findById(event.reportId());
    // report.getStatus() may still be DRAFT — the transaction hasn't committed yet
}
```

The database update and the listener run in the same transaction. The listener can read what looks like stale data, and if it makes further database changes based on that read, those changes are also inside the original transaction — coupling concerns that should be independent.

## Deferring to After Commit

```java
@Transactional
public void submitReport(String reportId) {
    reportRepository.updateStatus(reportId, Status.SUBMITTED);
    eventPublisher.publishEvent(new ReportSubmittedEvent(reportId));
    // Event is held — not delivered until this transaction commits
}

@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
public void onReportSubmitted(ReportSubmittedEvent event) {
    // Transaction has committed — database state is visible
    Report report = reportRepository.findById(event.reportId());
    // report.getStatus() is SUBMITTED
    log.info("Processing post-submission steps for report {}", event.reportId());
    notifyApprovers(report);
}
```

`phase = TransactionPhase.AFTER_COMMIT` is the most common setting. The listener runs after the surrounding transaction commits. This is what you want in almost all cases.

The other phases — `BEFORE_COMMIT`, `AFTER_ROLLBACK`, `AFTER_COMPLETION` — exist for specific cases: `BEFORE_COMMIT` for side effects that must be part of the transaction, `AFTER_ROLLBACK` for cleanup when things go wrong.

## The fallbackExecution Edge Case

By default, `@TransactionalEventListener` only fires when there is an active transaction. If the event is published from a non-transactional context — a test, a startup listener, a `@Scheduled` method — the event is silently discarded.

Setting `fallbackExecution = true` makes the listener fire even without a transaction:

```java
@TransactionalEventListener(
    phase = TransactionPhase.AFTER_COMMIT,
    fallbackExecution = true
)
public void onReportSubmitted(ReportSubmittedEvent event) {
    // Fires after commit when there's a transaction
    // Fires immediately when there's no transaction
}
```

This matters for integration tests that publish events directly, and for batch processes that may or may not be transactional depending on configuration. Without `fallbackExecution = true`, tests that publish events and expect listeners to fire will fail silently — the event is published, the listener is never called, and the test passes or fails for confusing reasons.

## Event Context Design

Event objects should carry enough context for listeners to do their work without needing to join back to the calling method's state. Carrying a domain context object avoids the listener making assumptions about what is available:

```java
public record ReportSubmittedEvent(
    String reportId,
    DomainContext context
) {}

public record DomainContext(
    String correlationId,
    String userId,
    String companyId,
    String changeSource
) {}
```

The listener receives the event and has the correlation ID for logging, the company ID for tenant-scoped queries, and the change source for audit purposes — without coupling to the `Report` domain object or making any additional database calls just to reconstruct context.

```java
@TransactionalEventListener(
    phase = TransactionPhase.AFTER_COMMIT,
    fallbackExecution = true
)
public void onReportSubmitted(ReportSubmittedEvent event) {
    DomainContext ctx = event.context();
    MDC.put("correlation_id", ctx.correlationId());
    MDC.put("company_id", ctx.companyId());
    try {
        processPostSubmission(event.reportId(), ctx);
    } catch (Exception e) {
        // Do not rethrow — the originating transaction has already committed.
        // Rethrowing here does not roll it back; it only propagates to the
        // application event multicaster, which logs and discards it.
        log.warn("Post-submission processing failed for report {}: {}",
            event.reportId(), e.getMessage(), e);
    } finally {
        MDC.remove("correlation_id");
        MDC.remove("company_id");
    }
}
```

The catch-all is deliberate. When `AFTER_COMMIT` fires, the originating transaction has already committed. There is nothing to roll back. If the listener throws, Spring's event multicaster catches it and logs a warning, but the event is not re-delivered. If your listener needs retry behaviour, implement it explicitly (with a queue or scheduled re-check), not by relying on exception propagation from a post-commit listener.

## Transactional Listener Executing in a New Transaction

If the listener needs to write to the database, it runs in a new transaction by default (no propagation annotation means `REQUIRED`, but since the outer transaction has already committed, there is no active transaction to join). To be explicit:

```java
@TransactionalEventListener(
    phase = TransactionPhase.AFTER_COMMIT,
    fallbackExecution = true
)
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void onReportSubmitted(ReportSubmittedEvent event) {
    // This starts a new transaction for the listener's own writes
    auditRepository.recordEvent(event.reportId(), "SUBMITTED", event.context());
}
```

`REQUIRES_NEW` suspends any ambient transaction (there isn't one at AFTER_COMMIT, but it makes the intent explicit and handles the `fallbackExecution` case where a transaction may be active).

## Testing

For component tests, publishing events from outside a transaction and expecting listeners to fire requires `fallbackExecution = true`. Verify listener behaviour with an integration test that uses the real application context:

```java
@SpringBootTest
@Transactional
class ReportSubmissionListenerTest {

    @Autowired ApplicationEventPublisher eventPublisher;
    @Autowired ReportRepository reportRepository;

    @Test
    void listenerFiresAfterCommit() {
        // The @Transactional here is rolled back after the test, but
        // AFTER_COMMIT listeners fire at commit time — not at rollback.
        // For testing AFTER_COMMIT, use TestTransaction.flagForCommit() or
        // run the test without @Transactional and clean up manually.
    }
}
```

Testing `AFTER_COMMIT` listeners requires actually committing the transaction. The simplest approach is a test that does not use `@Transactional` on the test method and cleans up after itself via `@AfterEach`.

## When Not to Use This Pattern

`@TransactionalEventListener` adds asynchrony within the request. The listener runs in the same thread as the request but after the outer transaction closes. This is not the same as background processing — if the listener takes 5 seconds, the HTTP response is delayed by 5 seconds.

For genuinely asynchronous side effects — sending notifications, triggering downstream services, writing to external systems — combine `@TransactionalEventListener(AFTER_COMMIT)` with `@Async` or explicit executor submission. The transactional listener ensures the side effect only starts when the data is committed; the async execution ensures it does not block the response.

---
title: "Audit Trails for MongoDB Documents with JaVers"
date: 2025-11-10
draft: false
tags: ["java", "spring-boot", "mongodb", "javers", "audit", "microservices"]
description: "How to add complete audit trails to MongoDB documents using JaVers — configuration, capturing who changed what and when, querying change history by entity or date, and what JaVers stores in its snapshot collections."
---

An audit trail answers: what changed, when, and who made the change. For compliance requirements, debugging production issues, and customer support, being able to reconstruct the state of a record at any point in time is valuable.

JaVers is a library that compares object states and stores the diffs in a dedicated MongoDB collection. You call `javers.commit(author, object)` after saving, and JaVers computes what changed, stores a snapshot of the new state, and makes the diff queryable.

## Dependencies

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-data-mongodb:3.5.7'
implementation 'org.javers:javers-spring-mongo:7.9.0'
```

Java 21. `javers-spring-mongo` provides both the core JaVers engine and the MongoDB persistence layer.

## Configuration

```java
@Configuration
public class JaversConfiguration {

    @Bean
    public Javers javers(MongoTemplate mongoTemplate) {
        return JaversBuilder.javers()
            .registerJaversRepository(new MongoRepository(mongoTemplate.getDb()))
            .build();
    }
}
```

Three lines. `MongoRepository` stores JaVers data in two collections in the same database: `jv_commits` (metadata: author, timestamp, commit ID) and `jv_snapshots` (full state of the audited object at each commit, plus the diff from the previous state).

No schema changes to your domain collections. JaVers writes to its own collections alongside yours.

## Recording Changes

Inject `Javers` into any service that modifies auditable entities and call `commit()` after the MongoDB write:

```java
@Service
public class ReportService {

    private final ReportRepository reportRepository;
    private final Javers javers;

    public Report updateReport(String reportId, ReportUpdateRequest request,
                               String authorId) {
        Report report = reportRepository.findById(reportId)
            .orElseThrow(() -> new NotFoundException(reportId));

        report.setStatus(request.status());
        report.setTotalAmount(request.totalAmount());
        report.setLastModifiedBy(authorId);

        Report saved = reportRepository.save(report);

        // Record the change in JaVers
        javers.commit(authorId, saved);

        return saved;
    }
}
```

`commit(author, object)` takes an author identifier — typically a user ID or service name — and the object after the change. JaVers computes the diff from the previous snapshot and records it.

For objects being created for the first time, JaVers records an `INITIAL` snapshot with all fields set. For deletions:

```java
public void deleteReport(String reportId, String authorId) {
    reportRepository.deleteById(reportId);
    javers.commitShallowDelete(authorId, new Report(reportId));  // records deletion
}
```

## Querying Change History

### All changes to a specific entity

```java
public List<Change> getReportHistory(String reportId) {
    return javers.findChanges(
        QueryBuilder.byInstanceId(reportId, Report.class)
            .withChangedProperty("status")  // optional: filter to specific field
            .limit(50)
            .build()
    );
}
```

Each `Change` in the result represents one field change with its old and new value, the commit timestamp, and the author. Calling `getChanges()` without a property filter returns all field changes across all commits.

### Snapshots at a point in time

```java
public Optional<Report> getReportStateAt(String reportId, Instant pointInTime) {
    List<CdoSnapshot> snapshots = javers.findSnapshots(
        QueryBuilder.byInstanceId(reportId, Report.class)
            .to(pointInTime)
            .limit(1)
            .build()
    );

    if (snapshots.isEmpty()) {
        return Optional.empty();
    }

    CdoSnapshot snapshot = snapshots.get(0);
    // Reconstruct the object state from the snapshot
    return Optional.of(reconstructFromSnapshot(snapshot));
}
```

`CdoSnapshot` contains the complete object state at the time of that commit, not just the diff. You can reconstruct what the object looked like at any point in its history.

### All changes by a specific author

```java
public List<Change> getChangesByAuthor(String authorId, Instant since) {
    return javers.findChanges(
        QueryBuilder.byAuthor(authorId)
            .from(since)
            .build()
    );
}
```

### All changes across a type

```java
public List<Change> getRecentReportChanges(Instant since) {
    return javers.findChanges(
        QueryBuilder.byValueObjectType(Report.class)
            .from(since)
            .limit(100)
            .build()
    );
}
```

## What JaVers Tracks

By default, JaVers compares all fields of an object. You can annotate fields to control this:

```java
@Document("reports")
public class Report {

    @Id
    private String id;

    private String status;

    private BigDecimal totalAmount;

    // Track changes to this field
    private String assignedApproverId;

    // Don't track this — it changes on every save and would create noise
    @DiffIgnore
    private Instant lastModifiedAt;

    // Track at shallow level — only whether this list changed size, not element diffs
    @ShallowReference
    private List<String> attachmentIds;
}
```

`@DiffIgnore` excludes a field from comparison entirely. Use it for fields that change constantly but whose changes are not meaningful — last-modified timestamps, internal version counters, cache metadata.

`@ShallowReference` records whether a collection or reference changed (added/removed), but does not recurse into the referenced objects. Use it for lists of IDs or references to other audited entities that have their own commit history.

## JaVers Collections

Two collections in your MongoDB database:

**`jv_commits`** — one document per `javers.commit()` call:
```json
{
  "_id": {"commitId": "1.0"},
  "author": "user-abc-123",
  "commitDate": "2025-11-10T14:23:45.000Z",
  "commitDateInstant": "2025-11-10T14:23:45.000Z",
  "changedObjects": ["Report/report-xyz-789"]
}
```

**`jv_snapshots`** — one document per committed object state:
```json
{
  "commitMetadata": {"id": "1.0", "author": "user-abc-123"},
  "globalId": {"entity": "Report", "cdoId": "report-xyz-789"},
  "type": "UPDATE",
  "state": {
    "id": "report-xyz-789",
    "status": "APPROVED",
    "totalAmount": 245.50,
    "assignedApproverId": "manager-def-456"
  },
  "changedProperties": ["status"],
  "version": 3
}
```

The `state` field is the complete object state after this commit, not just the diff. This makes point-in-time reconstruction straightforward — you read the snapshot for the relevant version and deserialise it.

## Index Recommendations

JaVers does not create indexes automatically. Add these for the common query patterns:

```java
@ChangeUnit(id = "010-javers-indexes", order = "010", author = "team@example.com")
public class JaversIndexesMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        mongoTemplate.indexOps("jv_snapshots")
            .ensureIndex(new Index()
                .on("globalId.cdoId", Direction.ASC)
                .on("commitMetadata.id", Direction.DESC)
                .named("idx_snapshots_entity_commit"));

        mongoTemplate.indexOps("jv_commits")
            .ensureIndex(new Index()
                .on("author", Direction.ASC)
                .on("commitDate", Direction.DESC)
                .named("idx_commits_author_date"));
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        mongoTemplate.indexOps("jv_snapshots").dropIndex("idx_snapshots_entity_commit");
        mongoTemplate.indexOps("jv_commits").dropIndex("idx_commits_author_date");
    }
}
```

Without the `globalId.cdoId` index, querying the full change history of a single entity scans the entire `jv_snapshots` collection. For collections with years of audit history, this becomes unacceptably slow.

## Storage Considerations

JaVers stores a full snapshot of the audited object on every commit. For objects with many fields or objects that change frequently, the `jv_snapshots` collection can grow large. Consider:

- Using `@DiffIgnore` aggressively on fields that are not audit-relevant
- Setting a MongoDB TTL index on `jv_snapshots.commitMetadata.commitDate` if you only need to retain a rolling window of history
- Auditing only specific service methods rather than every save

The audit trail is only as useful as what you put into it. Auditing every field on every object in a high-throughput service generates noise that obscures meaningful changes. Start with the fields that matter — status transitions, financial amounts, approval assignments — and expand from there.

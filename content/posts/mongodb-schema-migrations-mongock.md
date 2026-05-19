---
title: "MongoDB Schema Migrations with Mongock"
date: 2025-11-10
draft: false
tags: ["java", "spring-boot", "mongodb", "mongock", "migrations", "microservices", "devops"]
description: "How to manage MongoDB schema migrations in a Spring Boot 3 microservice using Mongock — writing ChangeUnit classes, handling reversible vs irreversible migrations, bulk operations, and deduplication patterns."
---

MongoDB's schemaless design means you can add a field to your Java model without any migration. What it does not handle for you is: populating that field in existing documents, removing obsolete fields, rebuilding indexes, or deduplicating records that violate a uniqueness constraint you are adding.

Mongock brings the migration tooling familiar from relational databases — versioned changesets, execution history, rollback support — to MongoDB. Each migration runs once, in order, and is tracked in a MongoDB collection. If a migration fails, subsequent ones are blocked until the failure is resolved.

## Dependencies

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-data-mongodb:3.5.7'
implementation 'io.mongock:mongock-springboot-v3:5.5.1'
implementation 'io.mongock:mongodb-springdata-v4-driver:5.5.1'
```

Java 21. The `mongodb-springdata-v4-driver` artifact bridges Mongock to Spring Data MongoDB 4.x, which is what Spring Boot 3.x manages.

## Auto-Configuration

With the starter, Mongock picks up from `application.yml`:

```yaml
mongock:
  migration-scan-package: com.example.service.migrations
  enabled: true
  transaction-enabled: false  # Multi-document transactions require replica set
```

`migration-scan-package` is where Mongock looks for `@ChangeUnit` classes. Set `transaction-enabled: false` unless your MongoDB instance is a replica set (standalone instances do not support multi-document transactions).

## Writing a ChangeUnit

```java
@ChangeUnit(id = "001-add-processed-field", order = "001", author = "team@example.com")
public class AddProcessedFieldMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        Query query = new Query(Criteria.where("processed").exists(false));
        Update update = new Update().set("processed", false);

        mongoTemplate.updateMulti(query, update, "reports");
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        mongoTemplate.updateMulti(
            new Query(),
            new Update().unset("processed"),
            "reports"
        );
    }
}
```

The `id` must be unique and immutable — it is what Mongock stores in its tracking collection. Changing the `id` of an already-executed migration causes Mongock to treat the new ID as an unexecuted migration and run it again.

The `order` field controls execution sequence. Mongock sorts changesets by `order`, then applies them in that sequence. Use zero-padded strings — `"001"`, `"002"` — rather than integers, so string sorting matches numeric sorting.

## Reversible vs Irreversible Migrations

Not all migrations can be cleanly reversed. Document which ones can and cannot:

```java
@ChangeUnit(id = "002-add-expense-count-index", order = "002", author = "team@example.com")
public class AddExpenseCountIndexMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        IndexDefinition index = new Index()
            .on("companyId", Direction.ASC)
            .on("createdAt", Direction.DESC)
            .named("idx_company_created");

        mongoTemplate.indexOps("reports").ensureIndex(index);
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        mongoTemplate.indexOps("reports").dropIndex("idx_company_created");
    }
}
```

```java
@ChangeUnit(id = "003-remove-legacy-sync-field", order = "003", author = "team@example.com")
public class RemoveLegacySyncFieldMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        mongoTemplate.updateMulti(
            new Query(),
            new Update().unset("legacySyncStatus"),
            "reports"
        );
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        // Irreversible: data was deleted. Cannot restore from migration alone.
        // Rollback requires restoring from backup.
        log.warn("Migration 003 is irreversible. legacySyncStatus field cannot be restored " +
            "from migration rollback. Restore from backup if needed.");
    }
}
```

The rollback annotation is required even for irreversible migrations — Mongock expects it. Document the irreversibility with a warning log rather than silently doing nothing. Someone triggering a rollback should know immediately that it did not restore data.

## Bulk Operations for Large Collections

For collections with many documents, `updateMulti` can be slow and may hold locks. Use bulk operations with a batch size:

```java
@ChangeUnit(id = "004-normalize-company-id", order = "004", author = "team@example.com")
public class NormalizeCompanyIdMigration {

    private static final int BATCH_SIZE = 500;

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        Query query = new Query(Criteria.where("companyId").regex("^P", "i"))
            .limit(BATCH_SIZE);

        List<Document> batch;
        int totalUpdated = 0;

        do {
            batch = mongoTemplate.find(query, Document.class, "reports");
            if (batch.isEmpty()) break;

            BulkOperations bulk = mongoTemplate.bulkOps(BulkMode.UNORDERED, "reports");
            for (Document doc : batch) {
                String normalizedId = ((String) doc.get("companyId")).toLowerCase();
                bulk.updateOne(
                    new Query(Criteria.where("_id").is(doc.get("_id"))),
                    new Update().set("companyId", normalizedId)
                );
            }
            bulk.execute();
            totalUpdated += batch.size();
        } while (batch.size() == BATCH_SIZE);

        log.info("Normalized companyId for {} reports", totalUpdated);
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        log.warn("Migration 004 rollback: case normalization is not reversible without backup.");
    }
}
```

`BulkMode.UNORDERED` allows MongoDB to execute the operations in parallel internally and continue on individual failures. For migrations, prefer `UNORDERED` when each operation is independent — it is faster and a single document failure does not block the rest.

## Deduplication Pattern

Adding a unique index to a collection that already has duplicates fails. Deduplicate first, then add the index as a separate changeset:

```java
@ChangeUnit(id = "005-deduplicate-receipt-ids", order = "005", author = "team@example.com")
public class DeduplicateReceiptIdsMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        // Aggregation pipeline to find all duplicate receiptId values
        Aggregation agg = Aggregation.newAggregation(
            Aggregation.group("receiptId").count().as("count")
                .first("_id").as("keepId"),
            Aggregation.match(Criteria.where("count").gt(1))
        );

        AggregationResults<Document> results =
            mongoTemplate.aggregate(agg, "receipts", Document.class);

        for (Document dup : results.getMappedResults()) {
            String receiptId = dup.getString("_id");
            ObjectId keepId = dup.getObjectId("keepId");

            // Delete all but the one to keep
            mongoTemplate.remove(
                new Query(Criteria.where("receiptId").is(receiptId)
                    .and("_id").ne(keepId)),
                "receipts"
            );
        }
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        log.warn("Migration 005 rollback: deleted duplicate documents cannot be restored.");
    }
}
```

```java
@ChangeUnit(id = "006-unique-index-receipt-id", order = "006", author = "team@example.com")
public class UniqueIndexReceiptIdMigration {

    @Execution
    public void execution(MongoTemplate mongoTemplate) {
        IndexDefinition index = new Index()
            .on("receiptId", Direction.ASC)
            .unique()
            .named("idx_receipt_id_unique");

        mongoTemplate.indexOps("receipts").ensureIndex(index);
    }

    @RollbackExecution
    public void rollbackExecution(MongoTemplate mongoTemplate) {
        mongoTemplate.indexOps("receipts").dropIndex("idx_receipt_id_unique");
    }
}
```

Splitting deduplication and index creation into two changesets means if the deduplication fails, the index migration is blocked and you can investigate before anything partially commits. The alternative — deduplication + index creation in one changeset — makes failure harder to diagnose and partially harder to resume.

## Tracking Collection

Mongock creates a collection named `mongockChangeLog` (configurable) to track execution state. Each executed changeset appears as a document with its `id`, `author`, `timestamp`, `state` (`EXECUTED` or `ROLLED_BACK`), and a checksum of the class.

The checksum is computed from the `@ChangeUnit` annotation fields. Changing the class body does not affect the checksum — only the annotation metadata does. This means you can add comments or refactor the implementation of an executed migration without Mongock treating it as a new migration.

Do not modify the `id` or `order` of an already-executed migration. The tracking document is keyed by `id`. Changing it causes Mongock to see a new, unexecuted migration and run it again.

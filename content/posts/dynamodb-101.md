---
title: "DynamoDB 101: Designing for Billions of Records"
date: 2024-08-15
tags: ["aws", "dynamodb", "database", "backend", "architecture"]
description: "A deep dive into DynamoDB's data model — partition keys, sort keys, GSIs, LSIs, and capacity planning — with a real-world example from a high-scale e-commerce order tracking service."
---

When you hit the limits of relational databases at scale, DynamoDB becomes an attractive option. But it's a fundamentally different beast — it rewards you for understanding its internals and punishes you for trying to treat it like Postgres. This post covers the mental model you need to design DynamoDB tables that perform well and cost predictably at billions of records.

## What DynamoDB Actually Is

DynamoDB is a fully managed, serverless key-value and document database. The critical properties:

- **Single-digit millisecond latency** at any scale
- **Horizontal scaling** — no vertical limits
- **No schema enforcement** — items in the same table can have different attributes
- **ACID transactions** — added in 2018, covering up to 100 items

What it is *not*: a relational database. There are no joins. There are no aggregations (outside of very limited scan operations). There is no free-text search. Your access patterns must be designed *into* the schema upfront.

## The Data Model

Every DynamoDB table has a mandatory **primary key**, which is either:

1. **Partition key only** — a single attribute that uniquely identifies each item
2. **Composite key** — a partition key + sort key pair that together uniquely identifies an item

### Partition Key (PK)

The partition key is hashed to determine which physical partition holds the item. This has a critical implication: **all items with the same partition key live on the same partition**, and a single partition can handle at most 3,000 RCUs or 1,000 WCUs per second.

Choosing a bad partition key creates "hot partitions" — a small number of partitions handling disproportionate traffic while others sit idle. Classic bad choices:

- A boolean flag (`is_active`) — creates 2 partitions max
- A low-cardinality enum (`status`) — creates N partitions where N is tiny
- A timestamp rounded to the day — all today's writes hit one partition

Good partition keys have **high cardinality** and **uniform access distribution**. User UUIDs, entity UUIDs, and order IDs are typically excellent choices.

### Sort Key (SK)

The sort key is optional. When present, items sharing a partition key are sorted by sort key value — enabling range queries within a partition.

This is where DynamoDB's power really shows up. Consider a table storing user activity events:

- Partition key: `user_id` (UUID)
- Sort key: `event_timestamp` (ISO 8601 string or epoch milliseconds)

This lets you efficiently query:
- All events for a specific user: `PK = user_id`
- Events for a user within a time range: `PK = user_id AND SK BETWEEN t1 AND t2`
- Latest 10 events: `PK = user_id, LIMIT 10, SCAN_INDEX_FORWARD = false`

All of these are **O(1) operations** — DynamoDB jumps directly to the partition and scans only the relevant range.

## A Real-World Example: Order Tracking Service

Here's how this looks in production. Consider a service tracking order line items for users at scale — processing millions of events per day across tens of thousands of merchants.

```
Table: orders

Partition Key: user_uuid      (UUID — uniquely identifies a user)
Sort Key:      order_uuid     (UUID — uniquely identifies an order)
```

Each item in this table represents one order for one user. The composite key means:
- You can instantly look up one user's one order: O(1)
- You can list all orders for a user: O(items in partition) — fast range scan
- Hot partition risk is minimal — orders distribute across all users

Sample item structure:
```json
{
  "user_uuid": "a3f2b1c4-...",
  "order_uuid": "7d9e3f2a-...",
  "status": "SHIPPED",
  "merchant": "ACME_CORP",
  "merchant_group": "ACME_US",
  "order_date": "2024-08-01",
  "amount": 47.50,
  "currency": "USD",
  "last_updated": "2024-08-01T14:23:11Z",
  "ttl": 1756684800
}
```

## Secondary Indexes: GSI and LSI

The primary key serves one query pattern perfectly. For everything else, you need secondary indexes.

### Local Secondary Index (LSI)

An LSI shares the *same partition key* as the base table but uses a *different sort key*. You must define LSIs at table creation time — they cannot be added afterward.

**Use case**: Multiple sort orders for the same partition.

In our orders table, an LSI was added for merchant-grouped queries:

```
LSI: merchantGroupDateIndex
  Partition Key: user_uuid          (same as base table)
  Sort Key:      merchant_group + # + order_date
```

This composite sort key (with a delimiter `#`) enables queries like:
- "All ACME_US orders for user X"
- "All ACME_US orders for user X in August 2024"

The trick with compound sort keys is encoding multiple dimensions into a single string with a consistent delimiter, then using `begins_with()` or `between` for range queries.

**LSI limits:**
- Max 5 per table
- Max 10 GB of data per partition key value (combined base + all LSIs)
- Cannot be added after table creation

### Global Secondary Index (GSI)

A GSI is essentially a separate table with its own partition key and optional sort key, maintained automatically by DynamoDB from the base table's data. GSIs can be added or deleted at any time.

**Use case**: Access patterns that don't share the base table's partition key.

In the order tracking service:

```
GSI: merchantUUIDIndex
  Partition Key: merchant_uuid
  Sort Key:      order_date
```

This allows operations like:
- "All orders for merchant X" (for merchant dashboards or reporting)
- "All orders for merchant X in a given time range"

Without this GSI, answering "show me all orders for this merchant" would require a full table scan — which is both slow and expensive.

**GSI important caveats:**

1. **Eventual consistency**: GSI reads are eventually consistent. A write to the base table may not be immediately reflected in the GSI.

2. **GSI has its own capacity**: If you're using provisioned capacity, the GSI needs its own RCU/WCU allocation. Writes to the base table that affect the GSI consume write capacity from *both* the base table and the GSI.

3. **Sparse indexes**: If an item doesn't have the GSI partition key attribute, it simply won't appear in the GSI. This is a feature — you can create sparse indexes covering only a subset of items.

4. **Projection**: You choose which attributes get copied to the GSI — `KEYS_ONLY`, `INCLUDE` (specific attributes), or `ALL`. Projecting fewer attributes reduces storage costs.

## Capacity Modes

### On-Demand Mode

DynamoDB automatically scales to any throughput, and you pay per request:
- $1.25 per million read request units (RRUs)
- $1.25 per million write request units (WRUs)

**Pros**: Zero capacity planning, handles unpredictable spikes, great for development.  
**Cons**: Can be 5-7x more expensive than well-tuned provisioned capacity at sustained high throughput.

**Use on-demand when**: traffic is unpredictable, spiky, or you're in early development.

### Provisioned Mode

You reserve a fixed number of Read Capacity Units (RCUs) and Write Capacity Units (WCUs) per second:
- 1 RCU = one strongly consistent read of ≤4 KB, or two eventually consistent reads
- 1 WCU = one write of ≤1 KB

**Pricing** (US East):
- $0.00013 per RCU-hour = ~$0.09 per RCU-month
- $0.00065 per WCU-hour = ~$0.47 per WCU-month

**Auto Scaling**: You set min/max bounds, and DynamoDB adjusts provisioned capacity based on utilization. Target utilization is typically 70%.

**Reserved Capacity**: For stable workloads, you can buy 1-year or 3-year reservations at 50-76% discount.

### Capacity Math Example

A service handling 10,000 writes/second of ~500-byte items:
- WCUs needed: 10,000 (each write ≤1 KB = 1 WCU)
- Monthly cost at on-demand: 10,000 × 86,400 × 30 × $0.00000125 = **$32,400/month**
- Monthly cost at provisioned (10,000 WCU): 10,000 × 720h × $0.00065 = **$4,680/month**

At scale, provisioned mode saves 85%+ over on-demand. The break-even point is typically around 20% sustained utilization of what you'd provision.

## Common Design Patterns

### Single-Table Design

For applications with multiple entity types, many DynamoDB practitioners advocate "single-table design" — storing all entities in one table using generic PK/SK names and type prefixes:

```
PK              SK                    Type
USER#a3f2b1c4   PROFILE               user
USER#a3f2b1c4   ORDER#7d9e3f2a        order
USER#a3f2b1c4   ORDER#4c1a9b3e        order
ORDER#7d9e3f2a  ITEM#1                order_item
ORDER#7d9e3f2a  ITEM#2                order_item
```

**Benefits**: Fetch a user and all their orders in one query. No cross-table joins needed.  
**Drawbacks**: Complex to understand, hard to evolve schema, poor fit for ad-hoc queries.

This pattern works well for microservices with well-understood, stable access patterns. For systems with evolving query requirements, multiple tables (one per entity type) is often more maintainable.

### Time-Series Data

For events, logs, and metrics, a common pattern is to shard by time:

```
PK: service#YYYY-MM   (e.g., "payments#2024-08")
SK: timestamp#event_id
```

This prevents any single partition from growing unbounded. As months pass, old partitions stop receiving writes. You can archive or delete old partitions easily.

For hot data, add an additional shard suffix to spread load:

```
PK: service#YYYY-MM-DD#shard_{0-9}
```

Pick a shard for writes by hashing the record ID modulo 10. For reads, query all 10 shards in parallel (fan-out) and merge the results client-side.

### Write Sharding for Hot Partitions

If a partition key value is genuinely hot (e.g., a celebrity's follower count), append a random shard suffix:

```python
import random
shard_suffix = random.randint(0, N-1)
pk = f"{user_id}#{shard_suffix}"
```

Writes fan out across N partitions. Reads must query all N shards and aggregate. Choose N based on your peak write rate divided by 1,000 WCU/partition/second.

## TTL: Automatic Expiry

DynamoDB's TTL feature automatically deletes items after a specified timestamp. Define a numeric attribute (epoch seconds) and enable TTL on that attribute:

```json
{
  "user_uuid": "...",
  "order_uuid": "...",
  "ttl": 1756684800
}
```

TTL deletions happen within 48 hours of expiry (not exactly at expiry). They don't consume capacity units. They do generate delete events in DynamoDB Streams (useful for cache invalidation).

In the order tracking service, TTL is set ~6 months in the future for each item. Old orders automatically expire without any maintenance job.

## Transactions

DynamoDB supports ACID transactions across up to 100 items (or 4 MB, whichever comes first):

```java
dynamoDbClient.transactWriteItems(request -> request
    .transactItems(
        TransactWriteItem.builder()
            .put(Put.builder()
                .tableName("orders")
                .item(orderItem)
                .conditionExpression("attribute_not_exists(order_uuid)")
                .build())
            .build(),
        TransactWriteItem.builder()
            .update(Update.builder()
                .tableName("user_counts")
                .key(Map.of("user_uuid", AttributeValue.fromS(userId)))
                .updateExpression("ADD order_count :one")
                .expressionAttributeValues(Map.of(":one", AttributeValue.fromN("1")))
                .build())
            .build()
    )
    .build()
);
```

Transactions cost 2x the normal RCU/WCU (the extra cost is for the prepare phase). Use them only when you genuinely need atomicity.

## Conditional Writes and Optimistic Locking

DynamoDB supports conditional expressions on writes — the write only proceeds if the condition holds:

```java
// Only create if item doesn't already exist
PutItemRequest.builder()
    .tableName("orders")
    .item(item)
    .conditionExpression("attribute_not_exists(partition_key)")
    .build();

// Optimistic locking with a version attribute
UpdateItemRequest.builder()
    .tableName("orders")
    .updateExpression("SET #s = :new_status, version = :new_version")
    .conditionExpression("version = :expected_version")
    .expressionAttributeValues(Map.of(
        ":new_status", AttributeValue.fromS("PROCESSED"),
        ":new_version", AttributeValue.fromN(String.valueOf(currentVersion + 1)),
        ":expected_version", AttributeValue.fromN(String.valueOf(currentVersion))
    ))
    .build();
```

If the condition fails, DynamoDB throws `ConditionalCheckFailedException`. This is the DynamoDB-idiomatic way to implement compare-and-swap.

## What to Monitor

Once your table is live, watch these CloudWatch metrics:

| Metric | What it means | Action threshold |
|--------|--------------|-----------------|
| `ConsumedReadCapacityUnits` | Actual reads consumed | >80% of provisioned |
| `ConsumedWriteCapacityUnits` | Actual writes consumed | >80% of provisioned |
| `ThrottledRequests` | Requests rejected due to insufficient capacity | Any > 0 in production |
| `SystemErrors` | DynamoDB internal errors | Any |
| `SuccessfulRequestLatency` | P50/P99 latency | P99 > 10ms for simple reads |
| `ConditionalCheckFailedRequests` | Failed optimistic locks | Spike indicates contention |

**Critical**: Set up CloudWatch alarms on `ThrottledRequests`. Throttling is silent from the user's perspective (the SDK retries with exponential backoff) but degrades latency significantly.

## Common Pitfalls

**Forgetting that GSIs are eventually consistent.** If you write an item and immediately query the GSI, you may not see it. Design your application to tolerate this — or use strongly consistent reads on the base table.

**Choosing a low-cardinality partition key.** If 90% of your requests go to one partition key value, you've created a hot partition. No amount of provisioned capacity will save you — you'll hit per-partition limits.

**Over-fetching with Scan.** A `Scan` operation reads every item in the table. At millions of items, this is slow and expensive. If you find yourself needing Scan in production, it's a sign the schema needs redesigning. Use GSIs instead.

**Not using projection in GSIs.** By default, GSIs copy all attributes. If your items are large and your GSI only needs a few attributes, specify `INCLUDE` or `KEYS_ONLY` to cut storage costs significantly.

**Storing large blobs.** DynamoDB item size limit is 400 KB. Store large payloads (images, documents) in S3 and keep only the S3 key in DynamoDB.

## Summary

DynamoDB's design philosophy flips the relational model: instead of designing a normalized schema and writing flexible queries, you design your data model *around* your access patterns. The partition key + sort key structure, combined with LSIs and GSIs, can serve a surprisingly wide range of query patterns with consistent sub-millisecond latency.

The key decisions in order of importance:
1. Partition key — must distribute writes uniformly at your peak throughput
2. Sort key — enables range queries and sorting within a partition
3. GSIs — add query dimensions without restructuring the table
4. Capacity mode — on-demand for uncertain/spiky traffic, provisioned for steady sustained load

Get the partition key wrong and you'll hit walls at scale. Get it right and DynamoDB scales to billions of items without a DBA, a connection pool, or a maintenance window.

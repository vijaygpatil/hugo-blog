---
title: "Redis Distributed Locking with Redisson Fair Locks"
date: 2023-09-28
draft: false
tags: ["java", "spring-boot", "redis", "redisson", "distributed-systems", "concurrency", "microservices"]
description: "How to use Redisson's fair lock implementation for distributed mutual exclusion in a Spring Boot microservice — configuration, tryLock with wait and lease timeouts, safe release in finally blocks, and the tradeoffs versus standard Redisson locks."
---

In-process synchronisation — `synchronized`, `ReentrantLock` — does not work across pods. When multiple instances of a service can process the same entity concurrently, you need a distributed lock. Redis is a common choice for this: low latency, atomic operations, and widely available in cloud environments. Redisson's fair lock implementation sits on top of Redis and handles the locking primitives so your application code does not have to.

This post covers the fair lock specifically — what it does differently from a standard lock, and how to use it in a Spring Boot microservice.

## Why Fair Locks

Redisson provides two lock types: `RLock` (standard) and `RFairLock` (fair). The difference is ordering.

A standard lock makes no delivery order guarantees. When the lock is released, any waiting acquirer gets it — the one that waited longest is not preferred. Under high contention, a single acquirer can repeatedly lose to faster acquirers and wait indefinitely (starvation).

A fair lock maintains a queue. Acquirers are served in the order they arrived. The first waiter gets the lock when it is released. This prevents starvation and makes lock acquisition latency predictable — you wait proportionally to how many requests are ahead of you, not arbitrarily.

For user-facing operations where you want to avoid one request dominating the lock at the expense of others, fair locks are the right choice.

## Dependencies

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-web:3.1.2'
implementation 'org.redisson:redisson-spring-boot-starter:3.23.2'
```

Java 17. `redisson-spring-boot-starter` auto-configures a `RedissonClient` bean from `spring.data.redis.*` properties.

## Configuration

```yaml
# application.yml
spring:
  data:
    redis:
      host: ${REDIS_HOST:localhost}
      port: ${REDIS_PORT:6379}

lock:
  wait-time-ms: 3000
  lease-time-ms: 30000
```

The starter creates a single `RedissonClient` bean. No additional configuration needed for basic use.

## Taking and Releasing a Fair Lock

```java
@Service
public class UserProcessingService {

    private final RedissonClient redissonClient;

    @Value("${lock.wait-time-ms}")
    private long lockWaitTimeMs;

    @Value("${lock.lease-time-ms}")
    private long lockLeaseTimeMs;

    public void processForUser(String userId) throws LockAcquisitionException {
        RLock lock = redissonClient.getFairLock("user-processing:" + userId);

        boolean acquired;
        try {
            acquired = lock.tryLock(lockWaitTimeMs, lockLeaseTimeMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new LockAcquisitionException("Interrupted waiting for lock: " + userId);
        }

        if (!acquired) {
            throw new LockAcquisitionException("Could not acquire lock within timeout: " + userId);
        }

        try {
            doProcessing(userId);
        } finally {
            if (lock.isLocked() && lock.isHeldByCurrentThread()) {
                lock.unlock();
            }
        }
    }
}
```

Three things to note:

**`getFairLock(key)`** returns a fair lock for the given key. The key should be specific enough to avoid false contention — using `"user-processing:" + userId` means only requests for the same user contend; requests for different users proceed in parallel.

**`tryLock(waitMs, leaseMs, unit)`** has two timeouts. `waitMs` is how long this thread is willing to wait to acquire the lock. `leaseMs` is how long the lock is held before Redis automatically releases it — this is your safety net against a JVM crash or network partition leaving the lock permanently held. Set `leaseMs` to the upper bound on your operation time, not to infinity.

**The release guard `isLocked() && isHeldByCurrentThread()`** prevents two failure modes: releasing a lock you don't hold (which throws an exception), and releasing a lock that was already automatically released by Redis because the lease expired. Both can happen if the operation took longer than expected.

## Lock Key Design

The lock key determines the granularity of mutual exclusion. Picking the right key is important:

```java
// User-level lock — only one operation per user at a time
RLock userLock = redissonClient.getFairLock("processing:user:" + userId);

// Entity-level lock — only one operation per entity at a time
RLock entityLock = redissonClient.getFairLock("processing:entity:" + entityId);

// Batch-level lock — prevent concurrent batch starts for the same tenant
RLock batchLock = redissonClient.getFairLock("batch:start:" + tenantId + ":" + batchType);
```

Too coarse (a single global lock) creates a bottleneck. Too fine (a lock per field) creates overhead without meaningful protection. The right level is the smallest unit of data that must not be concurrently modified.

## Handling Lock Acquisition Failure

Not acquiring the lock is a normal outcome that your calling code must handle:

```java
@RestController
public class ProcessingController {

    @PostMapping("/process/{userId}")
    public ResponseEntity<String> trigger(@PathVariable String userId) {
        try {
            processingService.processForUser(userId);
            return ResponseEntity.ok("Processing complete");
        } catch (LockAcquisitionException e) {
            // Another request is already processing this user
            return ResponseEntity.status(HttpStatus.CONFLICT)
                .body("Processing already in progress, retry shortly");
        }
    }
}
```

Returning `409 Conflict` is semantically accurate: the request is valid, but the current state of the resource prevents processing. The client can retry. Returning `503 Service Unavailable` would imply a service problem rather than a contention condition.

## Lease Time and the Split-Brain Scenario

Setting a finite lease time is not optional. Consider what happens without it:

1. Thread acquires lock, starts processing
2. JVM pauses for GC for 45 seconds (long GC pauses happen)
3. Lock was released automatically by Redis at 30 seconds
4. A second thread acquires the lock and starts processing the same entity
5. First thread resumes — two threads now hold the lock simultaneously

With a well-chosen lease time, the Redis automatic release happens only after a duration that is longer than any expected operation. The guard `isHeldByCurrentThread()` in the finally block catches the case where the lease did expire — it prevents the first thread from releasing a lock it no longer holds.

There is no way to fully eliminate the split-brain scenario in distributed systems. Finite lease times limit the window during which two holders can exist. If your operation takes longer than the lease time, it should be re-evaluated — either break it into smaller units that complete within the lease window, or extend the lease time and accept the longer recovery window if the holder crashes.

## Fair Lock Performance Considerations

Fair locks have higher overhead than standard locks. Maintaining the acquisition queue requires additional Redis operations on each lock and unlock. At low contention, this is negligible. At high contention (many requests competing for the same lock frequently), the queue operations become measurable.

Profile before choosing fair over standard. If your workload has low contention per key — many different users, few concurrent requests per user — the starvation risk that motivates fair locks may not exist in practice. Standard locks are sufficient for most cases. Use fair locks when you have observed or expect starvation: a subset of users consistently waiting significantly longer than others under concurrent load.

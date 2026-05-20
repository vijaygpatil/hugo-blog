---
title: "In-Process Caching with Guava CacheBuilder"
date: 2021-11-09
draft: false
tags: ["java", "spring-boot", "caching", "guava", "microservices", "performance"]
description: "How to use Guava's CacheBuilder to cache expensive external API calls in a Spring Boot microservice — configuration parameters, composite cache keys, the double-check pattern for thread safety, and how to choose expiry times."
---

Our data processing service makes a lot of calls to external configuration APIs — expense types, form definitions, company settings. These are not user data; they change infrequently, sometimes never within a processing run. Fetching them on every record is expensive and unnecessary.

We tried Spring's `@Cacheable` first. It works well for simple cases but becomes awkward when you need different expiry times per cache, composite keys that aren't just method parameters, or explicit control over eviction. Guava's `CacheBuilder` gives you all of that with a straightforward API.

## Dependency

```groovy
// build.gradle
implementation 'com.google.guava:guava:31.0.1-jre'
```

Guava is a general-purpose library; `CacheBuilder` is one part of it. No Spring integration needed — it is plain Java.

## Basic Setup

```java
import com.google.common.cache.Cache;
import com.google.common.cache.CacheBuilder;

@Service
public class ExpenseTypeService {

    private final Cache<String, ExpenseType> expenseTypeCache = CacheBuilder.newBuilder()
        .concurrencyLevel(10)
        .maximumSize(10_000)
        .expireAfterWrite(8, TimeUnit.HOURS)
        .build();

    // ...
}
```

Three parameters do most of the work:

**`concurrencyLevel(10)`** — the cache is internally segmented to allow concurrent writes without a single global lock. This value is roughly the number of threads you expect to write to the cache simultaneously. It does not cap the total concurrent readers. Setting it too low creates contention; setting it too high wastes memory on unused segments. For a typical microservice with 10–20 processing threads, 10 is reasonable.

**`maximumSize(10_000)`** — the maximum number of entries. When this is exceeded, Guava evicts entries using an approximation of LRU. The right number depends on your data: how many distinct keys do you expect, and how large is each value? Err on the side of larger rather than smaller — memory is cheap, cache misses are not.

**`expireAfterWrite(8, TimeUnit.HOURS)`** — entries expire 8 hours after they were written, regardless of how often they are read. This is appropriate for configuration data that changes rarely but should not be stale indefinitely. Use `expireAfterAccess` instead if you want entries to expire only when they haven't been read — useful for caches where unused entries should age out.

## Composite Cache Keys

When your cache key has more than one component, a typed record is cleaner than string concatenation:

```java
// Using a Java record (Java 16+) or a value class
record SiteSettingKey(String entityCode, String settingName) {}

private final Cache<SiteSettingKey, String> siteSettingCache = CacheBuilder.newBuilder()
    .concurrencyLevel(10)
    .maximumSize(10_000)
    .expireAfterWrite(1, TimeUnit.HOURS)
    .build();
```

A record gives you `equals()` and `hashCode()` for free, which is what `Cache` uses for key lookup. String concatenation like `entityCode + "_" + settingName` works but is fragile — separators can collide if either component contains the separator character.

For simpler cases, a formatted string key is fine:

```java
// Single-component or clearly-separated keys
String cacheKey = String.format("%s_expenseLedgers", entityCode);
String cacheKey = String.format("%s_form_%s", companyId, formId);
```

## The Double-Check Pattern

`Cache.getIfPresent(key)` returns `null` on a miss. The naive approach is:

```java
ExpenseType type = cache.getIfPresent(key);
if (type == null) {
    type = fetchFromApi(key);
    cache.put(key, type);
}
```

This is not thread-safe. Two threads can both see a null, both call `fetchFromApi`, and both put the result. For an idempotent read API this is merely wasteful — duplicate calls but the same result. However, under high concurrency (many threads processing simultaneously, all missing the cache at startup), the stampede can overwhelm a downstream service.

The safer pattern is double-check with synchronisation:

```java
public ExpenseType getExpenseType(String companyId, String typeCode) {
    String cacheKey = companyId + "_" + typeCode;

    // [1] Fast path — no lock, just a read
    ExpenseType cached = expenseTypeCache.getIfPresent(cacheKey);
    if (cached != null) {
        return cached;
    }

    // [2] Slow path — take the lock, check again, then fetch
    synchronized (this) {
        cached = expenseTypeCache.getIfPresent(cacheKey);  // re-check under lock
        if (cached != null) {
            return cached;
        }

        ExpenseType fetched = fetchFromExternalApi(companyId, typeCode);
        if (fetched != null) {
            expenseTypeCache.put(cacheKey, fetched);
        }
        return fetched;
    }
}
```

The second `getIfPresent` inside the `synchronized` block is the key step. By the time a thread acquires the lock, another thread may have already fetched and cached the value. Without the re-check, you make redundant API calls even with the lock.

Guava also provides a cleaner alternative via `get(key, loader)`:

```java
try {
    return expenseTypeCache.get(cacheKey, () -> fetchFromExternalApi(companyId, typeCode));
} catch (ExecutionException e) {
    throw new RuntimeException("Failed to load expense type", e.getCause());
}
```

`get(key, loader)` is internally synchronised per key: if two threads request the same missing key simultaneously, only one calls the loader and the other waits for the result. The wrapping `ExecutionException` is the main friction point, which is why some teams prefer the explicit double-check pattern instead.

## Different TTLs for Different Data

Not all cached data has the same freshness requirements. We use separate `Cache` instances with different expiry times:

```java
@Service
public class ConfigurationCacheService {

    // Configuration that almost never changes
    private final Cache<String, GroupConfig> groupConfigCache = CacheBuilder.newBuilder()
        .concurrencyLevel(10)
        .maximumSize(10_000)
        .expireAfterWrite(1, TimeUnit.DAYS)
        .build();

    // Configuration that changes occasionally
    private final Cache<String, FormField> formFieldCache = CacheBuilder.newBuilder()
        .concurrencyLevel(10)
        .maximumSize(10_000)
        .expireAfterWrite(8, TimeUnit.HOURS)
        .build();

    // Data that should be relatively fresh
    private final Cache<String, List<Comment>> commentCache = CacheBuilder.newBuilder()
        .concurrencyLevel(4)
        .maximumSize(10_000)
        .expireAfterWrite(10, TimeUnit.MINUTES)
        .build();
}
```

The principle: set the TTL to the longest time a stale value would be acceptable, not the shortest. A 10-minute cache on comments means a comment written 9 minutes ago might not appear — that is a product decision, not just a technical one. Get agreement on acceptable staleness before choosing a TTL.

## Cache Statistics

`CacheBuilder` supports statistics collection, but you have to enable it explicitly:

```java
private final Cache<String, ExpenseType> expenseTypeCache = CacheBuilder.newBuilder()
    .concurrencyLevel(10)
    .maximumSize(10_000)
    .expireAfterWrite(8, TimeUnit.HOURS)
    .recordStats()  // enable stats collection
    .build();
```

Then expose them however you surface metrics:

```java
CacheStats stats = expenseTypeCache.stats();
log.info("Cache hit rate: {}, miss rate: {}, eviction count: {}",
    stats.hitRate(), stats.missRate(), stats.evictionCount());
```

`recordStats()` adds some overhead — roughly 10-15% on write-heavy workloads. For read-heavy caches it is negligible. Enable it in production if you want visibility into cache effectiveness; leave it off if the overhead matters.

## What We Observed

After adding in-process caches in front of our configuration API calls, the per-record processing time dropped significantly. More importantly, it made downstream services less sensitive to our load — a batch processing ten thousand records no longer caused ten thousand API calls.

A few things we learned the hard way:

**Don't cache nulls without thinking about it** — if your API returns null for a missing key and you don't cache nulls, a bad key causes a cache miss on every access and hammers the downstream service. Either cache a sentinel value, or use `CacheBuilder.newBuilder().build(loader)` which handles null results explicitly.

**Monitor the hit rate, not just latency** — a cache that is 50% effective is barely worth the complexity. If your hit rate is low, the TTL may be too short, the key space may be too large for `maximumSize`, or the access pattern may not suit caching at all.

**In-process cache means per-instance cache** — each pod has its own cache. If you have ten pods, you have ten caches that can be in different states. This is fine for configuration data fetched from an external API. It is not fine for data that needs to be consistent across instances — that requires a distributed cache.

---

Guava's `CacheBuilder` hits the right balance for in-process caching: straightforward API, sensible defaults, no infrastructure dependencies. For data that is expensive to fetch, changes rarely, and does not need to be consistent across instances, it is usually the right tool.

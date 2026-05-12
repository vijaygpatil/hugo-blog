---
title: "Redis Bandwidth: The Hidden Constraint That Will Bite You"
date: 2024-09-20
tags: ["redis", "aws", "elasticache", "performance", "backend", "debugging"]
description: "CPU and memory get all the attention, but network bandwidth is the constraint that actually takes down Redis clusters under load. Here's what we learned — including a Redisson bug that caused 100% CPU on application pods."
---

Most engineers sizing a Redis cluster think about two things: CPU and memory. How much RAM do we need to hold the dataset? Is the CPU keeping up with command throughput? These are the obvious metrics. Dashboard turns red, you respond.

Network bandwidth is the metric nobody watches until it takes everything down.

This post covers what we learned after hitting bandwidth limits on ElastiCache in production — and the cascading failure it caused, including a Redisson connection pool bug that pushed application pods to 100% CPU.

## Why Bandwidth Is Different from CPU and Memory

When CPU is high, commands slow down proportionally. When memory is high, you get evictions or OOM errors — both are visible. When bandwidth is saturated, something subtler happens: **the cluster starts dropping or delaying packets**. TCP connection attempts queue up. Existing connections experience timeout-level latency. Commands that normally take microseconds start returning timeouts.

The tricky part: **your Redis metrics look fine**. CPU is 30%. Memory usage 60%. But response times are 5 seconds and your application is falling over.

ElastiCache exposes bandwidth utilization as a percentage metric: **`NetworkBandwidthOutAllowanceExceeded`** and **`NetworkBandwidthInAllowanceExceeded`**. These are not widely known. They don't show up in the default CloudWatch dashboards. Most teams only discover them in a post-mortem.

## ElastiCache Network Limits by Node Type

Every ElastiCache node type has a fixed network bandwidth ceiling. When you hit it, AWS starts dropping packets — no gradual degradation, just hard drops:

| Instance Type | Network Bandwidth |
|---------------|-------------------|
| cache.t3.micro | Up to 5 Gbps (burst) |
| cache.t3.small | Up to 5 Gbps (burst) |
| cache.t3.medium | Up to 5 Gbps (burst) |
| cache.m5.large | Up to 10 Gbps |
| cache.m5.xlarge | Up to 10 Gbps |
| cache.m5.2xlarge | Up to 10 Gbps |
| cache.r6g.large | Up to 10 Gbps |
| cache.r6g.xlarge | Up to 12.5 Gbps |
| cache.r6g.2xlarge | Up to 15 Gbps |

**T-type instances** (t3, t4g) use **burst network credits**. They can sustain high bandwidth for short periods but throttle back to the baseline when credits are exhausted. The baseline for a `t3.medium` is less than 1 Gbps — and baseline is what matters for sustained production traffic.

## Baseline, Not Burst

This is the most important lesson: **size for baseline, not burst**.

Burst looks great in benchmarks and load tests that run for 5-10 minutes. In production, where load is continuous, you exhaust burst credits within 30-60 minutes and drop to baseline. If your sustained traffic exceeds baseline, you're in the danger zone.

How to calculate your bandwidth requirement:

```
bytes_per_second = (requests_per_second × avg_payload_bytes_per_request)
                 + (cache_miss_rate × avg_value_bytes × requests_per_second)
```

Double that number for safety margin. If the result exceeds the baseline of your chosen instance, you'll hit trouble under sustained load.

**Example**: 10,000 cache GET requests/second, average value size 5 KB:
```
Bandwidth = 10,000 × 5 KB = 50 MB/s = 400 Mbps
```

A `cache.t3.medium` with a ~200 Mbps baseline would be undersized despite looking fine in a short load test.

## What "Allowance Exceeded" Looks Like

When ElastiCache's bandwidth allowance is exceeded, the CloudWatch metric `NetworkBandwidthOutAllowanceExceeded` spikes above 0. In our case, it went to values like 150,000-200,000 — meaning hundreds of thousands of packets were dropped per minute.

The symptom in the application: **intermittent timeouts and slow responses on Redis operations**, appearing suddenly under load, with no obvious Redis-side error. The cluster appeared healthy by standard metrics.

The alert we added after this incident:

```hcl
resource "aws_cloudwatch_metric_alarm" "redis_bandwidth_out" {
  alarm_name          = "redis-bandwidth-out-allowance-exceeded"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "NetworkBandwidthOutAllowanceExceeded"
  namespace           = "AWS/ElastiCache"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  
  dimensions = {
    CacheClusterId = aws_elasticache_cluster.main.id
  }
  
  alarm_actions = [aws_sns_topic.alerts.arn]
}
```

Zero tolerance — any non-zero value triggers the alarm. At that point, you have time to act before the situation degrades further.

## The Redisson Bug: Bandwidth Pressure Causes CPU Spikes

This is where the incident got interesting.

Under bandwidth pressure, Redis connections start timing out from the client side. Redisson (the Java Redis client) handles timeouts via its connection pool. Here's the bug we discovered:

**Under rapid connection timeout and retry conditions, Redisson's connection pool enters a spin loop** — continuously attempting to acquire connections that are timing out, never backing off, consuming 100% CPU on the application pods.

The chain:
1. ElastiCache bandwidth saturated → packets dropped
2. Redis connection attempts from Redisson start timing out
3. Redisson retries aggressively — no exponential backoff in the connection acquisition path
4. Application pod CPU goes to 100%
5. At 100% CPU, the application can't process incoming requests at all
6. Load balancer marks pod unhealthy, requests pile up on other pods
7. Other pods hit the same bandwidth pressure → they also spike CPU
8. Cascading failure across all pods

The surface symptom (application CPU 100%) looked completely unrelated to the root cause (Redis bandwidth). This is what made the incident hard to diagnose in real time.

### Redisson Configuration to Mitigate This

The relevant Redisson config parameters:

```yaml
redisson:
  singleServerConfig:
    address: "redis://your-elasticache-endpoint:6379"
    connectionPoolSize: 10          # don't set this too high
    connectionMinimumIdleSize: 2    # keep headroom
    connectTimeout: 3000            # ms - time to establish connection
    timeout: 3000                   # ms - time to receive response
    retryAttempts: 3               # don't retry infinitely
    retryInterval: 500             # ms between retries
    subscriptionsPerConnection: 5
```

**Key settings to tune**:

- `retryAttempts`: Default is 3 in newer Redisson versions, but was higher in older versions. Limit this.
- `retryInterval`: Add delay between retries. This is what prevents the spin loop.
- `connectionPoolSize`: Smaller pools = less bandwidth pressure from connection overhead.
- `timeout`: Keep this reasonable. A very long timeout means your threads block longer during bandwidth events, amplifying the CPU problem.

**Also important**: update to a recent Redisson version. The connection pool behavior under pressure has been improved significantly in versions after 3.17.

### Circuit Breaker Pattern

For services where Redis is a cache (not the primary data store), wrap Redis calls in a circuit breaker:

```java
@Bean
public RedisCircuitBreaker redisCircuitBreaker() {
    CircuitBreakerConfig config = CircuitBreakerConfig.custom()
        .failureRateThreshold(50)           // open at 50% failure rate
        .slowCallRateThreshold(50)          // open at 50% slow calls
        .slowCallDurationThreshold(Duration.ofMillis(500))
        .waitDurationInOpenState(Duration.ofSeconds(30))
        .permittedNumberOfCallsInHalfOpenState(5)
        .build();
    
    return CircuitBreakerRegistry.of(config)
        .circuitBreaker("redis");
}

public Optional<String> getCached(String key) {
    return redisCircuitBreaker.executeSupplier(() -> {
        return Optional.ofNullable(redisTemplate.opsForValue().get(key));
    }).recover(exception -> Optional.empty())
      .get();
}
```

When the circuit opens (Redis is having trouble), cache misses gracefully go to the database instead of hammering Redis with requests it can't serve, which would amplify the bandwidth pressure.

## Sizing Recommendations

### For new deployments

1. **Calculate your peak bandwidth requirement** using the formula above. Use P99 payload size, not average.
2. **Add 50% headroom** above your calculated peak.
3. **Avoid t-type instances** for anything with sustained high throughput. The burst behavior is misleading.
4. **Prefer r-type instances** (memory-optimized) over m-type if your dataset is large — you get more network bandwidth per dollar on r6g vs m5 at the same memory tier.

### For existing deployments

Add these CloudWatch metrics to your Redis dashboard immediately:
- `NetworkBandwidthInAllowanceExceeded`
- `NetworkBandwidthOutAllowanceExceeded`
- `NetworkPacketsOutAllowanceExceeded`

If any are non-zero during normal operation, you're already at risk.

### ElastiCache Cluster Mode

For workloads exceeding single-node bandwidth, ElastiCache Redis cluster mode distributes data across multiple shards. Each shard handles a subset of the keyspace, and bandwidth is effectively distributed:

```
Cluster with 3 shards × cache.r6g.xlarge
= 3 × 12.5 Gbps = 37.5 Gbps aggregate bandwidth
```

The tradeoff: client code must be cluster-aware (most modern Redis clients handle this transparently), and operations across multiple keys in different shards can't be executed atomically unless you use hash tags to force keys to the same shard.

## Payload Size Matters More Than Request Count

A counterintuitive finding: **reducing payload size has more impact than reducing request count**.

Switching from JSON serialization to a compact binary format (e.g., MessagePack or protobuf) for cached objects can cut bandwidth by 50-70% with no change to request patterns:

```java
// JSON: ~1.2 KB per object
objectMapper.writeValueAsBytes(myObject);

// MessagePack: ~380 bytes for the same object
MessagePack.newDefaultPacker().packValue(MessagePack.newDefaultUnpacker(bytes).unpackValue());
```

Similarly, review what you're actually storing. In one audit, we found objects with 40+ fields being cached when the consuming code only used 5. Projecting only the needed fields cut cache object size by 80%.

Compression is another option for large values (>1 KB):

```java
// Compress values over 1KB before storing
byte[] compress(byte[] data) throws IOException {
    if (data.length < 1024) return data;
    ByteArrayOutputStream bos = new ByteArrayOutputStream();
    try (GZIPOutputStream gzip = new GZIPOutputStream(bos)) {
        gzip.write(data);
    }
    return bos.toByteArray();
}
```

The CPU cost of compression is almost always worth it — a single Redis connection can saturate a CPU-bound compression operation thousands of times per second, while even modest bandwidth reduction meaningfully extends your runway.

## Read-Through Caching and Hot Keys

Another bandwidth optimization: **hot key detection**. If 10% of your keys get 80% of your traffic, caching those at the application level (in-process, with a short TTL) eliminates their Redis traffic entirely.

Spring Cache with local L1 cache backed by Redis L2:

```java
@Configuration
public class CacheConfig {
    
    @Bean
    public CacheManager cacheManager(RedisConnectionFactory cf) {
        // L1: Caffeine in-process cache, 1000 entries, 10s TTL
        CaffeineCacheManager l1 = new CaffeineCacheManager();
        l1.setCaffeine(Caffeine.newBuilder()
            .maximumSize(1000)
            .expireAfterWrite(Duration.ofSeconds(10)));
        
        // L2: Redis distributed cache
        RedisCacheManager l2 = RedisCacheManager.builder(cf)
            .cacheDefaults(RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofMinutes(5)))
            .build();
        
        // CompositeCacheManager: try L1 first, fall back to L2
        return new CompositeCacheManager(l1, l2);
    }
}
```

For the hottest keys, this keeps traffic off Redis entirely. The 10-second in-process TTL is acceptable for most caching use cases.

## Monitoring Checklist

Add these to your Redis dashboards before you need them:

```
CloudWatch Metrics to track:
□ NetworkBandwidthInAllowanceExceeded   (alert on > 0)
□ NetworkBandwidthOutAllowanceExceeded  (alert on > 0)
□ NetworkPacketsOutAllowanceExceeded    (alert on > 0)
□ EngineCPUUtilization                  (alert on > 80%)
□ CurrConnections                       (alert on > 70% of max)
□ CacheMisses / CacheHits               (watch miss rate trends)
□ Evictions                             (alert on > 0 if dataset fits in memory)

Application-side metrics:
□ Redis operation P50/P95/P99 latency
□ Redis connection pool usage
□ Redis timeout rate
□ Cache hit rate by cache region
```

## Summary

The lessons from this incident:

1. **Bandwidth is a hard limit** — unlike CPU, there's no gradual degradation. When you hit it, things break suddenly.
2. **Baseline, not burst** — T-type instances look capable in load tests. They're not for sustained production traffic.
3. **`AllowanceExceeded` metrics are not in default dashboards** — add them yourself, set alerts to zero tolerance.
4. **Redisson (and other clients) can spin-loop under bandwidth pressure** — understand your client's retry behavior and configure backoff appropriately.
5. **Payload size is your biggest lever** — switching serialization formats or projecting fewer fields often reduces bandwidth more than any infrastructure change.
6. **Circuit breakers prevent cascade** — when Redis is struggling, fail fast and gracefully rather than amplifying the problem.

The monitoring setup costs 30 minutes. The incident costs 4 hours and half your night. Do the monitoring setup.

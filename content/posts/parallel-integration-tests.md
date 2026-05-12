---
title: "From 170 Minutes to 42: Parallelizing Integration Tests with JUnit 5"
date: 2025-03-10
tags: ["testing", "junit5", "java", "spring-boot", "ci-cd", "performance"]
description: "Our integration test suite was taking nearly 3 hours. Here's how we cut it to 42 minutes using JUnit 5 parallel execution, @ResourceLock for shared state, and isolated mock templates — including the race conditions we fixed along the way."
---

Three-hour CI runs are a productivity killer. By the time your test suite finishes, you've lost context, picked up three other tasks, and now need to re-engage with the original change. We had this problem with two integration test workflows — our standard suite (253 tests, 170 minutes) and a specialized USO workflow suite (58 minutes). Here's how we parallelized both, the race conditions we hit, and what we ended up with.

## The Starting Point

Before any changes, the test profiles looked like this:

| Suite | Tests | Duration |
|-------|-------|----------|
| Standard | 253 | 170 minutes |
| USO workflow | ~60 | 58 minutes |

These ran sequentially, one test at a time. With the number of tests, each test averaged roughly 40 seconds. That's not slow per test — it's just too many tests to run sequentially.

The tests were Spring Boot integration tests using `@SpringBootTest` with a full application context, `MockRestServiceServer` for HTTP dependencies, and an in-memory H2 database. The external dependency mocking was the key design constraint for parallelization.

## JUnit 5 Parallel Execution Setup

JUnit 5 includes built-in parallel execution support. Enable it via a configuration file:

```properties
# src/test/resources/junit-platform.properties

# Enable parallel execution
junit.jupiter.execution.parallel.enabled=true

# Use fixed thread pool (don't use dynamic — predictable behavior)
junit.jupiter.execution.parallel.config.strategy=fixed

# Thread pool size — tune based on your CI instance
junit.jupiter.execution.parallel.config.fixed.parallelism=4

# Execute test classes in parallel, methods within a class sequentially
junit.jupiter.execution.parallel.mode.default=same_thread
junit.jupiter.execution.parallel.mode.classes.default=concurrent
```

The choice between `same_thread` and `concurrent` for the default mode matters:
- `same_thread`: test methods within a class run sequentially (safe default)
- `concurrent`: test methods within a class also run in parallel (requires thread-safe test code)

Start with `same_thread` for methods — it's much easier to reason about, and parallelizing across test *classes* is usually sufficient for the speedup you need.

## The Core Problem: Shared MockRestServiceServer

The immediate problem with parallel execution: `MockRestServiceServer` is not thread-safe.

Our test setup looked like this:

```java
@SpringBootTest
class SomeIntegrationTest {
    
    @Autowired
    private RestTemplate restTemplate;
    
    private MockRestServiceServer mockServer;
    
    @BeforeEach
    void setUp() {
        mockServer = MockRestServiceServer.createServer(restTemplate);
    }
    
    @Test
    void testSomething() {
        mockServer.expect(requestTo("/api/endpoint"))
                  .andRespond(withSuccess(responseBody, MediaType.APPLICATION_JSON));
        // ... test code
    }
}
```

When two test classes run in parallel, they share the same `RestTemplate` bean from the Spring context. Both tests call `MockRestServiceServer.createServer(restTemplate)`, which registers a mock request factory on the *same* `RestTemplate` instance. They then set expectations on different mocks pointing at the same underlying instance.

What happens: Test A sets an expectation for `/api/orders`. Test B sets an expectation for `/api/users`. Test A fires a request to `/api/orders` — but MockServer B's expectation is checked first (or vice versa). Test fails with "No further requests expected" or "Unexpected request to /api/users".

### Solution: Isolated MockRestServiceServer per Test Class

The fix: don't share the `RestTemplate`. Use a request factory approach where each test class gets isolation:

```java
@SpringBootTest
class SomeIntegrationTest {
    
    @Autowired
    private RestTemplate restTemplate;
    
    private MockRestServiceServer mockServer;
    
    @BeforeEach
    void setUp() {
        // bindTo creates a fresh interceptor chain — doesn't affect the bean
        mockServer = MockRestServiceServer.bindTo(restTemplate)
                                          .ignoreExpectOrder(true)
                                          .build();
    }
    
    @AfterEach
    void tearDown() {
        mockServer.reset();
    }
}
```

`MockRestServiceServer.bindTo()` (vs `createServer()`) creates an interceptor that is scoped to the test instance, not permanently modifying the `RestTemplate` bean. Combined with `reset()` in `@AfterEach`, this isolates each test class.

However, even with this, two tests running concurrently with the same `RestTemplate` bean can still interfere if they're truly concurrent. The more robust solution for full parallelism:

```java
@SpringBootTest
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class SomeIntegrationTest {
    
    // Create a fresh RestTemplate per test class instance
    private final RestTemplate testRestTemplate = new RestTemplate();
    private MockRestServiceServer mockServer;
    
    @BeforeAll
    void setUpClass() {
        // Replace the autowired template with our isolated one
        // using Spring's ApplicationContext manipulation
    }
    
    @BeforeEach
    void setUp() {
        mockServer = MockRestServiceServer.createServer(testRestTemplate);
    }
}
```

In practice, the cleanest solution was to use a `@Primary` mock bean for tests that creates per-test-class instances:

```java
@TestConfiguration
public class MockRestTemplateConfig {
    
    @Bean
    @Primary
    public RestTemplate mockRestTemplate() {
        // Each test class gets its own RestTemplate through Spring's
        // prototype or test context lifecycle
        return new RestTemplate();
    }
}
```

## @ResourceLock for Genuinely Shared State

Some tests truly cannot run in parallel because they share state that can't be isolated. JUnit 5's `@ResourceLock` annotation handles this:

```java
import org.junit.jupiter.api.parallel.ResourceLock;
import org.junit.jupiter.api.parallel.ResourceAccessMode;

// Tests that write to shared state must acquire an exclusive lock
@ResourceLock(value = "SHARED_CACHE", mode = ResourceAccessMode.READ_WRITE)
class CacheWritingTest {
    @Test
    void testCacheWrite() { ... }
}

// Tests that only read can run concurrently with other readers
@ResourceLock(value = "SHARED_CACHE", mode = ResourceAccessMode.READ)
class CacheReadingTest {
    @Test
    void testCacheRead() { ... }
}
```

Resource locks are string-based identifiers. Tests declaring the same resource with `READ_WRITE` mode will not run concurrently with each other or with any `READ` holder. Tests with `READ` mode can run concurrently with each other.

In our test suite, the shared resources requiring `@ResourceLock`:

1. **Database state** — tests that insert seed data and tests that check counts need coordination
2. **Scheduled job execution** — tests that verify a job ran can't run while another test is manually triggering the same job
3. **External service mock** — when a mock service is configured globally (not per-test) and tests verify call counts

```java
@ResourceLock("DATABASE_SEED")
class DataSeedingTest {
    // These tests set up baseline data — must run before any test that
    // assumes a specific database state
}

@ResourceLock(value = "DATABASE_SEED", mode = ResourceAccessMode.READ)
class DataReadingTest {
    // These tests read data — can run concurrently after seeding completes
}
```

### Constants for Resource Names

Define resource lock names as constants to prevent typos:

```java
public final class TestResources {
    public static final String DATABASE = "DATABASE";
    public static final String KAFKA_TOPIC = "KAFKA_TOPIC";
    public static final String SCHEDULED_JOB = "SCHEDULED_JOB";
    public static final String EXTERNAL_HTTP_MOCK = "EXTERNAL_HTTP_MOCK";
    
    private TestResources() {}
}

// Usage:
@ResourceLock(TestResources.DATABASE)
class MyTest { ... }
```

## Race Conditions We Fixed

### Race 1: Test Order-Dependent Assertions

Some tests were written assuming they run after a specific other test (because in sequential mode, test classes always run in the same order). Example:

```java
class OrderCountTest {
    @Test
    void shouldHave5Orders() {
        // This assumed previous tests had inserted exactly 5 orders
        assertEquals(5, orderRepository.count());
    }
}
```

Fix: Make tests self-contained. Each test creates exactly the data it needs and verifies only what it created:

```java
class OrderCountTest {
    
    @Test
    void shouldCountCreatedOrders() {
        // Create exactly 3 orders
        orderRepository.save(new Order(...));
        orderRepository.save(new Order(...));
        orderRepository.save(new Order(...));
        
        // Count only the ones we created, scoped by a unique test run ID
        assertEquals(3, orderRepository.countByTestRunId(testRunId));
    }
}
```

Using a unique `testRunId` per test class (a UUID generated in `@BeforeAll`) lets multiple tests insert data concurrently without interfering with each other's assertions.

### Race 2: Scheduled Job Interference

Tests that verify scheduled job behavior were failing intermittently because a parallel test would manually trigger the same scheduled job at the same time:

```java
// Test A: manually triggers job
@Test
void testJobExecution() {
    jobScheduler.triggerNow();
    await().until(() -> jobRepository.count() > 0);
}

// Test B (running in parallel): also verifies job
@Test
void testJobNotRunning() {
    assertEquals(0, jobRepository.count()); // fails if Test A's job ran
}
```

Fix: Lock on the job resource:

```java
@ResourceLock(TestResources.SCHEDULED_JOB)
class ScheduledJobTest {
    @Test
    void testJobExecution() { ... }
}

@ResourceLock(TestResources.SCHEDULED_JOB)  
class ScheduledJobStateTest {
    @Test
    void testJobNotRunning() { ... }
}
```

### Race 3: Kafka Consumer Group Offset Conflicts

Tests using Kafka would sometimes read messages from a previous test's run because consumer group offsets weren't being reset between parallel tests:

```java
@BeforeEach
void resetKafkaOffset() {
    // Reset to latest offset so this test only sees messages it produces
    kafkaTestUtils.seekToEnd(consumer, topicPartitions);
}
```

When multiple tests ran in parallel and both reset offsets, one would reset after the other had already started consuming, causing missed messages.

Fix: Use unique consumer groups per test class:

```java
@SpringBootTest(properties = {
    "spring.kafka.consumer.group-id=test-${random.uuid}"
})
class KafkaIntegrationTest { ... }
```

Each test class gets a fresh consumer group with no committed offsets, starting from the latest position. No coordination needed.

### Race 4: Static Application State

Some services used static state (caches, singleton counts) that accumulated across tests:

```java
public class MetricsService {
    private static final AtomicInteger requestCount = new AtomicInteger(0);
    
    public void increment() {
        requestCount.incrementAndGet();
    }
    
    public int getCount() {
        return requestCount.get();
    }
}
```

Tests asserting `assertEquals(1, metricsService.getCount())` would fail if another test had already called `increment()`.

Fix: Either reset static state in `@BeforeEach`, or better, redesign to avoid static state in tests:

```java
@BeforeEach
void resetMetrics() {
    ReflectionTestUtils.setField(MetricsService.class, "requestCount", new AtomicInteger(0));
}
```

Or scope metrics to a request/test context rather than a static field.

## Tuning Thread Count

The right thread pool size depends on:
- How many CPU cores your CI runner has
- How much of the test time is I/O-bound vs CPU-bound
- Memory pressure from multiple Spring contexts

For integration tests that do I/O (HTTP calls, database queries), you can use more threads than CPU cores because threads spend much of their time waiting:

```properties
# For a 4-core CI runner with I/O-heavy tests
junit.jupiter.execution.parallel.config.fixed.parallelism=6

# For CPU-heavy tests
junit.jupiter.execution.parallel.config.fixed.parallelism=4

# For tests with heavy Spring context startup overhead
junit.jupiter.execution.parallel.config.fixed.parallelism=3
```

**Monitoring**: Add test timing output to CI. If you see high variance in total time across runs, you likely have resource contention that needs `@ResourceLock`.

## Results After Changes

| Suite | Before | After | Improvement |
|-------|--------|-------|-------------|
| Standard (253 tests) | 170 minutes | 42 minutes | **4x faster** |
| USO workflow (~60 tests) | 58 minutes | 27 minutes | **2.1x faster** |

The standard suite showed a larger gain because it had more parallelism headroom (253 independent tests vs ~60). The USO suite had more tests with shared state requiring locks, limiting parallelism.

The 4x speedup with a 4-thread pool is close to theoretical maximum — most of the remaining overhead is Spring context startup (which happens once per test class regardless of parallelism) and the serialized sections protected by `@ResourceLock`.

## Cronjob Schedule Changes

Because the CI runs are now faster, we updated the integration test cronjob schedules:

```yaml
# Before: ran every 3 hours (test suite took ~170 min)
schedule: "0 */3 * * *"

# After: runs every 90 minutes (test suite takes ~42 min)
schedule: "0 */1 * * *"   # actually 90 min
```

More frequent runs means catching regressions sooner. A test that breaks at 9:00 AM is now caught by 10:30 AM instead of noon.

## Checklist for Parallelizing Your Suite

Before enabling parallel execution:

```
□ Identify all shared state (static fields, shared beans, shared databases)
□ Audit MockRestServiceServer usage — ensure per-test isolation
□ Find tests that assert on counts or aggregate state
□ Check for implicit ordering dependencies between test classes
□ Review any Kafka/messaging setup for group ID isolation
□ Identify scheduled jobs triggered in tests
□ Run suite 3-5 times in parallel to find flaky tests

After enabling parallel execution:
□ Add @ResourceLock to genuinely shared resources
□ Make assertions scope-isolated (use test run IDs)
□ Reset any static state in @BeforeEach
□ Monitor CI run time variance (high variance = hidden contention)
□ Set thread pool size based on CI runner specs
```

## When NOT to Parallelize

Some test categories are difficult or inadvisable to parallelize:

**End-to-end tests against a shared environment**: If multiple tests write to the same external service or database, you need coordination that becomes more complex than the parallelism is worth.

**Tests with heavy external side effects**: Tests that send emails, create cloud resources, or trigger webhooks can interfere with each other in ways that aren't caught by resource locks.

**Test suites under 5 minutes**: The overhead of debugging parallel race conditions isn't worth it if your suite already runs in under 5 minutes. Parallelize when the pain is real.

For most backend service integration test suites in the 50-500 test range, JUnit 5 parallel execution with proper resource isolation is a well-understood solution that pays for itself quickly.

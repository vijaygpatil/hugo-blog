---
title: "Component Tests: Real Spring Context with Mocked HTTP"
date: 2025-10-20
draft: false
tags: ["java", "spring-boot", "testing", "testcontainers", "mockito", "component-testing", "microservices"]
description: "How to structure component tests in a Spring Boot 3 microservice — a separate Gradle source set, a real application context with Testcontainers for infrastructure, MockRestServiceServer for HTTP dependencies, and @MockitoBean for selective overrides."
---

Unit tests verify individual classes in isolation. Integration tests verify that the full system works end-to-end. Component tests sit between: they exercise the real application logic with real infrastructure (database, cache) but with external HTTP dependencies mocked at the transport level.

The goal is a test that can say: "given this HTTP response from service X, the application writes the correct record to MongoDB." You need a real Spring context, a real database, and controlled HTTP responses. You do not need to call service X over the network.

## Project Structure

Component tests live in their own source set, separate from unit tests and any end-to-end tests:

```
src/
├── main/java/
├── test/java/          ← unit tests
└── componentTest/java/ ← component tests
```

In `build.gradle`:

```groovy
sourceSets {
    componentTest {
        java.srcDirs = ['src/componentTest/java']
        resources.srcDirs = ['src/componentTest/resources']
        compileClasspath += sourceSets.main.output + sourceSets.test.output
        runtimeClasspath += sourceSets.main.output + sourceSets.test.output
    }
}

configurations {
    componentTestImplementation.extendsFrom testImplementation
    componentTestRuntimeOnly.extendsFrom testRuntimeOnly
}

tasks.register('componentTest', Test) {
    description = 'Runs component tests'
    group = 'verification'
    testClassesDirs = sourceSets.componentTest.output.classesDirs
    classpath = sourceSets.componentTest.runtimeClasspath
    useJUnitPlatform()
    shouldRunAfter test
}

check.dependsOn componentTest
```

Dependencies shared with unit tests (JUnit, Mockito, Spring Test) are inherited via `extendsFrom`. Component-test-specific dependencies — Testcontainers, WireMock if you use it — go in `componentTestImplementation`:

```groovy
dependencies {
    componentTestImplementation 'org.springframework.boot:spring-boot-starter-test:3.5.6'
    componentTestImplementation 'org.testcontainers:testcontainers:2.0.1'
    componentTestImplementation 'org.testcontainers:mongodb:2.0.1'
    componentTestImplementation 'org.testcontainers:junit-jupiter:2.0.1'
}
```

Java 21. JUnit 5.14.0 is managed transitively by Spring Boot 3.5.6.

## The Base Test Class

A base class provides the shared infrastructure setup:

```java
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Testcontainers
@ActiveProfiles("componentTest")
public abstract class BaseComponentTest {

    @Container
    static MongoDBContainer mongoDBContainer = new MongoDBContainer("mongo:7.0")
        .withReuse(true);

    @DynamicPropertySource
    static void mongoProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.data.mongodb.uri", mongoDBContainer::getReplicaSetUrl);
    }

    @Autowired
    protected TestRestTemplate restTemplate;
}
```

`withReuse(true)` keeps the container running across test classes during a single Gradle run. Testcontainers uses a container hash to identify reusable containers — the same MongoDB image started with the same configuration reuses the running instance rather than starting a new one.

`@ActiveProfiles("componentTest")` lets you configure test-specific beans — stub API clients, relaxed security — without polluting the main configuration.

## Mocking External HTTP with MockRestServiceServer

For Spring Boot services that use `RestTemplate` or `RestClient` to call external APIs, `MockRestServiceServer` intercepts HTTP calls at the `ClientHttpRequestFactory` level:

```java
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Testcontainers
@ActiveProfiles("componentTest")
public abstract class BaseComponentTest {

    @Container
    static MongoDBContainer mongoDBContainer = new MongoDBContainer("mongo:7.0")
        .withReuse(true);

    @Autowired
    protected RestTemplate externalApiRestTemplate;

    protected MockRestServiceServer mockExternalApi;

    @DynamicPropertySource
    static void mongoProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.data.mongodb.uri", mongoDBContainer::getReplicaSetUrl);
    }

    @BeforeEach
    void setUpMockServer() {
        mockExternalApi = MockRestServiceServer
            .bindTo(externalApiRestTemplate)
            .ignoreExpectOrder(true)
            .build();
    }

    @AfterEach
    void verifyMockServer() {
        mockExternalApi.verify();
        mockExternalApi.reset();
    }
}
```

`ignoreExpectOrder(true)` allows expectations to be satisfied in any order — useful when the test setup involves parallel HTTP calls or a non-deterministic calling sequence.

`verify()` in `@AfterEach` confirms every expected HTTP request was actually made. `reset()` clears expectations so the next test starts clean.

## Writing a Component Test

```java
class ReportProcessingComponentTest extends BaseComponentTest {

    @Autowired
    private ReportRepository reportRepository;

    @Test
    void processingCreatesAuditRecord() {
        // Arrange: set up expected HTTP responses
        mockExternalApi.expect(requestTo(containsString("/api/config/expense-types")))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess(
                """
                {"expenseTypes": [{"code": "MEAL", "name": "Meals"}]}
                """,
                MediaType.APPLICATION_JSON
            ));

        // Act: trigger processing via the real HTTP endpoint
        ResponseEntity<String> response = restTemplate.postForEntity(
            "/reports/process",
            new ProcessingRequest("report-123", "company-abc"),
            String.class
        );

        // Assert
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);

        // Verify the expected database state
        Optional<Report> saved = reportRepository.findById("report-123");
        assertThat(saved).isPresent();
        assertThat(saved.get().getStatus()).isEqualTo(Status.PROCESSED);
        assertThat(saved.get().getAuditEntries()).hasSize(1);
    }
}
```

The test exercises the full request path: HTTP request → Spring controller → service layer → external API call (mocked) → MongoDB write (real). It asserts both the HTTP response and the resulting database state.

## Selective Bean Overrides with @MockitoBean

Sometimes you want the real application context but need to stub a specific bean — a notification sender, an external event publisher, a slow downstream client. `@MockitoBean` (introduced in Spring Boot 3.4 as a replacement for `@MockBean`) replaces the bean with a Mockito mock for the duration of the test:

```java
class NotificationComponentTest extends BaseComponentTest {

    @MockitoBean
    private EmailNotificationService emailNotificationService;

    @Test
    void approvalTriggersNotification() {
        restTemplate.postForEntity(
            "/reports/approve/report-123",
            null,
            String.class
        );

        verify(emailNotificationService, times(1))
            .sendApprovalNotification(eq("report-123"), any());
    }
}
```

`@MockitoBean` creates a new Spring context for classes that use it — if multiple test classes use `@MockitoBean` with different sets of mocked beans, each creates its own context. Consolidate `@MockitoBean` declarations in the base class if you want a single shared context:

```java
// In BaseComponentTest — mocks declared here are shared across all component tests
@MockitoBean
protected EmailNotificationService emailNotificationService;
```

With this, all component tests that extend `BaseComponentTest` share one application context, and `emailNotificationService` is always a mock. Use `Mockito.reset(emailNotificationService)` in `@BeforeEach` to clear recorded interactions between tests.

## Verifying Call Counts

A useful pattern for components that should make exactly N calls to an external API for a given input:

```java
@Test
void configApiIsCalledOncePerCompany() {
    // Set up the mock to accept any number of calls
    mockExternalApi.expect(manyTimes(),
            requestTo(containsString("/api/config")))
        .andRespond(withSuccess("{}", MediaType.APPLICATION_JSON));

    // Process multiple reports for the same company
    restTemplate.postForEntity("/reports/process", new ProcessingRequest("r1", "company-abc"), String.class);
    restTemplate.postForEntity("/reports/process", new ProcessingRequest("r2", "company-abc"), String.class);

    // Verify the config API was called exactly once (cache hit on second call)
    mockExternalApi.verify(requestTo(containsString("/api/config")), times(1));
}
```

This pattern catches cache regressions: if the in-process cache is broken, the mock will record two calls and `times(1)` will fail.

## Running Component Tests

```bash
./gradlew componentTest
```

Component tests are slower than unit tests — Testcontainers adds 5–15 seconds for container startup on first run (cached on subsequent runs). Keep component tests focused on integration correctness rather than exhaustive logic coverage. Unit tests cover logic; component tests cover integration.

The `shouldRunAfter test` declaration in the Gradle task means `./gradlew check` runs unit tests first, then component tests. If unit tests fail, you get fast feedback before waiting for the slower component tests.

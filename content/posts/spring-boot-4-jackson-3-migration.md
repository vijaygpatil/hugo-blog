---
title: "Spring Boot 4 + Jackson 3 Migration Guide"
date: 2025-11-01
tags: ["java", "spring-boot", "jackson", "migration", "backend"]
description: "A practical guide to migrating from Spring Boot 3/Jackson 2 to Spring Boot 4/Jackson 3: package renames, immutable ObjectMapper, exception hierarchy changes, and module removals — with before/after code for each breaking change."
---

Spring Boot 4 ships with Jackson 3, and Jackson 3 is not a minor bump. It's a deliberate API cleanup with breaking changes across package names, core class behavior, exception hierarchies, and bundled modules. The good news: most changes are mechanical and the compiler will catch them. The bad news: a few behavioral changes require actual thought.

This guide covers every breaking change you're likely to hit, with before/after code.

## 1. Package Name: `com.fasterxml.jackson` → `tools.jackson`

This is the most pervasive change. Jackson's top-level package namespace changed from `com.fasterxml.jackson` to `tools.jackson`.

**Before:**
```java
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
```

**After:**
```java
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.SerializationFeature;
import tools.jackson.databind.annotation.JsonDeserialize;
import tools.jackson.databind.annotation.JsonSerialize;
import tools.jackson.core.JsonProcessingException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.annotation.JsonProperty;
import tools.jackson.annotation.JsonIgnore;
import tools.jackson.annotation.JsonInclude;
```

The pattern is uniform: replace `com.fasterxml.jackson` with `tools.jackson` everywhere. Your IDE's global find-and-replace handles the bulk of this, but read through the results — some third-party libraries still use Jackson 2 internally and you don't want to rename those.

**IntelliJ migration script:**
```
Find:    com\.fasterxml\.jackson
Replace: tools.jackson
Scope:   Project source files (exclude tests if you want to verify separately)
```

Do this rename first, before tackling any other changes. It makes the remaining compilation errors specific to actual API changes rather than generic "class not found" errors.

## 2. ObjectMapper Is Now Immutable

This is the most significant behavioral change and the one most likely to cause subtle bugs if you miss it.

In Jackson 2, `ObjectMapper` was mutable — you could call `configure()`, `enable()`, `disable()`, and `registerModule()` on a shared instance at any time, including after it had been used:

```java
// Jackson 2 — this "worked" but was always unsafe
@Bean
public ObjectMapper objectMapper() {
    return new ObjectMapper();
}

// Somewhere else in the codebase:
@Autowired
ObjectMapper mapper;

public void configure() {
    mapper.enable(SerializationFeature.INDENT_OUTPUT);  // mutable mutation
    mapper.registerModule(new JavaTimeModule());
}
```

In Jackson 3, `ObjectMapper` instances are **immutable** after construction. Configuration methods return a new instance rather than mutating the existing one, following the builder pattern:

**Before (Jackson 2):**
```java
@Bean
public ObjectMapper objectMapper() {
    ObjectMapper mapper = new ObjectMapper();
    mapper.registerModule(new JavaTimeModule());
    mapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    mapper.configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    mapper.setSerializationInclusion(JsonInclude.Include.NON_NULL);
    return mapper;
}
```

**After (Jackson 3):**
```java
@Bean
public ObjectMapper objectMapper() {
    return JsonMapper.builder()
        .addModule(new JavaTimeModule())
        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
        .serializationInclusion(JsonInclude.Include.NON_NULL)
        .build();
}
```

`JsonMapper.builder()` returns an `ObjectMapper` configured according to the builder chain. The resulting instance is immutable — calling `configure()` on it would throw an `UnsupportedOperationException`.

### What This Breaks

Any code that modifies a shared `ObjectMapper` after construction fails at runtime:

```java
// This throws UnsupportedOperationException in Jackson 3
objectMapper.registerModule(new KotlinModule());
objectMapper.enable(MapperFeature.ACCEPT_CASE_INSENSITIVE_ENUMS);
```

Hunt for all post-construction modifications:

```bash
# Find places that call configure/enable/disable/register on an ObjectMapper variable
grep -rn "objectMapper\.\(configure\|enable\|disable\|registerModule\|setSerializationInclusion\)" src/
```

Each of these needs to move into the builder chain.

### ObjectMapper Copy Pattern

If you need variants of an ObjectMapper (e.g., one with pretty-printing, one without), use the `copy()` builder:

```java
// Jackson 3: create a variant via copy builder
ObjectMapper prettyMapper = objectMapper.rebuild()
    .enable(SerializationFeature.INDENT_OUTPUT)
    .build();
```

`rebuild()` returns a builder initialized with all settings of the current mapper, letting you create modified variants without touching the original.

## 3. Exception Hierarchy Changes

### `JsonProcessingException` Becomes `JacksonException`

The base class for serialization/deserialization errors changed:

**Before:**
```java
try {
    String json = objectMapper.writeValueAsString(myObject);
} catch (JsonProcessingException e) {
    log.error("Serialization failed", e);
    throw new RuntimeException("Failed to serialize", e);
}
```

**After:**
```java
try {
    String json = objectMapper.writeValueAsString(myObject);
} catch (JacksonException e) {  // broader base class
    log.error("Serialization failed", e);
    throw new RuntimeException("Failed to serialize", e);
}
```

`JacksonException` is the new common base class. `JsonProcessingException` still exists but now extends `JacksonException`. For most catch blocks, updating to `JacksonException` is the right move — it's more semantically accurate ("something Jackson-related failed") than the specific subclass.

### Checked Exceptions Removed from Core APIs

A significant ergonomics improvement: `ObjectMapper`'s core methods no longer declare checked exceptions in Jackson 3.

**Before:**
```java
// Had to declare or catch IOException
public String serialize(Object obj) throws IOException {
    return objectMapper.writeValueAsString(obj);
}

// Or wrap it
public String serialize(Object obj) {
    try {
        return objectMapper.writeValueAsString(obj);
    } catch (JsonProcessingException e) {
        throw new UncheckedIOException(e);
    }
}
```

**After:**
```java
// No checked exception — JacksonException is unchecked
public String serialize(Object obj) {
    return objectMapper.writeValueAsString(obj);
}
```

`JacksonException` extends `RuntimeException`. This removes a lot of boilerplate try-catch blocks from code that never actually recovers from serialization errors. Remove the `throws IOException` declarations from method signatures and the wrapping try-catch blocks from code that only re-throws.

## 4. JSR-310 (Java Time) Module

### Module Removed from Separate Artifact

In Jackson 2, Java 8 date/time support (`LocalDate`, `Instant`, `ZonedDateTime`, etc.) required adding `jackson-datatype-jsr310` as a dependency and registering the module:

```xml
<!-- Jackson 2: separate dependency required -->
<dependency>
    <groupId>com.fasterxml.jackson.datatype</groupId>
    <artifactId>jackson-datatype-jsr310</artifactId>
</dependency>
```

```java
// Jackson 2: manual module registration required
objectMapper.registerModule(new JavaTimeModule());
```

In Jackson 3, Java time support is **built into the core**. The separate artifact is gone, and the module is auto-registered:

```xml
<!-- Jackson 3: no separate dependency needed -->
<!-- Remove jackson-datatype-jsr310 from pom.xml -->
```

```java
// Jackson 3: no explicit registration needed
// But you still need to configure serialization behavior:
JsonMapper.builder()
    .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
    // ...
    .build();
```

If you're migrating, remove `jackson-datatype-jsr310` from your dependencies and remove the `registerModule(new JavaTimeModule())` calls. Keep the `WRITE_DATES_AS_TIMESTAMPS` configuration — that's still required to get ISO 8601 strings instead of numeric timestamps.

### Other Removed Modules

Check your `pom.xml` or `build.gradle` for these Jackson 2 datatype modules — some were consolidated or removed:

| Jackson 2 Artifact | Jackson 3 Status |
|--------------------|------------------|
| `jackson-datatype-jsr310` | Built-in, remove |
| `jackson-datatype-jdk8` | Built-in, remove |
| `jackson-module-parameter-names` | Built-in, remove |
| `jackson-datatype-guava` | Still separate: `tools.jackson.datatype:jackson-datatype-guava` |
| `jackson-datatype-joda` | Still separate (deprecated) |
| `jackson-module-kotlin` | Updated: `tools.jackson.module:jackson-module-kotlin` |

The three modules that were most commonly added via Spring Boot's `spring-boot-starter-json` are now built-in.

## 5. Spring Boot AutoConfiguration Changes

Spring Boot 4's `JacksonAutoConfiguration` reflects the Jackson 3 changes. The auto-configured `ObjectMapper` is now built via `JsonMapper.builder()`.

### Custom ObjectMapper Bean

If you define your own `ObjectMapper` bean, Spring Boot backs off entirely (same as before). The builder approach is now the idiomatic way:

```java
@Configuration
public class JacksonConfig {
    
    @Bean
    @Primary
    public ObjectMapper objectMapper() {
        return JsonMapper.builder()
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .serializationInclusion(JsonInclude.Include.NON_NULL)
            .enable(MapperFeature.ACCEPT_CASE_INSENSITIVE_ENUMS)
            .build();
    }
}
```

### Spring MVC and `HttpMessageConverter`

Spring's `MappingJackson2HttpMessageConverter` has been updated for Jackson 3. If you customize it:

```java
// Before
@Bean
public MappingJackson2HttpMessageConverter converter() {
    MappingJackson2HttpMessageConverter converter = 
        new MappingJackson2HttpMessageConverter();
    converter.setObjectMapper(objectMapper());
    return converter;
}

// After — functionally identical, but ObjectMapper must be built with builder
@Bean
public MappingJackson2HttpMessageConverter converter() {
    return new MappingJackson2HttpMessageConverter(objectMapper());
}
```

## 6. Annotation Changes

### `@JsonCreator` Mode Inference

Jackson 3 changed how `@JsonCreator` mode is inferred for single-argument constructors. If you use `@JsonCreator` without specifying mode, update explicitly:

```java
// Jackson 2: mode was inferred based on parameter count/annotations
@JsonCreator
public MyValue(String value) {
    this.value = value;
}

// Jackson 3: be explicit to avoid ambiguity
@JsonCreator(mode = JsonCreator.Mode.DELEGATING)
public MyValue(String value) {
    this.value = value;
}

// Or for properties-based creation:
@JsonCreator(mode = JsonCreator.Mode.PROPERTIES)
public MyValue(@JsonProperty("value") String value) {
    this.value = value;
}
```

### `@JsonIgnoreProperties` on Class Level

The semantics are unchanged, but the inheritance behavior was clarified. If you extend a class with `@JsonIgnoreProperties` and want different behavior in the subclass, you must re-annotate explicitly.

## 7. Dependency Updates

### Maven

```xml
<!-- Spring Boot 4 manages Jackson 3 versions -->
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>4.0.0</version>
</parent>

<!-- These are managed, just remove version tags -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-json</artifactId>
</dependency>

<!-- If you need explicit Jackson artifacts -->
<dependency>
    <groupId>tools.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
</dependency>
<dependency>
    <groupId>tools.jackson.core</groupId>
    <artifactId>jackson-annotations</artifactId>
</dependency>

<!-- Remove these — now built-in -->
<!-- <dependency>
    <groupId>com.fasterxml.jackson.datatype</groupId>
    <artifactId>jackson-datatype-jsr310</artifactId>
</dependency> -->
```

### Gradle

```groovy
// Remove old Jackson artifacts
configurations.all {
    exclude group: 'com.fasterxml.jackson.datatype', module: 'jackson-datatype-jsr310'
    exclude group: 'com.fasterxml.jackson.module', module: 'jackson-module-parameter-names'
}
```

## Migration Checklist

Work through these in order:

```
□ 1. Package rename
     - Find: com\.fasterxml\.jackson
     - Replace: tools.jackson
     - Exclude: third-party library source/jars

□ 2. ObjectMapper construction
     - Find all `new ObjectMapper()` instances
     - Replace with `JsonMapper.builder()...build()` pattern
     - Find all post-construction configure/enable/disable/registerModule calls
     - Move them into the builder chain

□ 3. Exception handling
     - Replace `catch (JsonProcessingException e)` with `catch (JacksonException e)` 
     - Remove `throws IOException` from methods wrapping ObjectMapper calls
     - Remove unnecessary try-catch that just re-throws unchecked

□ 4. Module dependencies
     - Remove jackson-datatype-jsr310 from pom.xml/build.gradle
     - Remove jackson-datatype-jdk8 from pom.xml/build.gradle
     - Remove jackson-module-parameter-names from pom.xml/build.gradle
     - Remove corresponding registerModule() calls

□ 5. @JsonCreator annotations
     - Find all @JsonCreator usages
     - Add explicit mode = parameter where missing

□ 6. Test ObjectMapper instances
     - Tests often create their own ObjectMappers
     - Apply same builder pattern to test helpers

□ 7. Verify serialization output
     - Run integration tests that check JSON structure
     - Date format tests (ISO 8601 vs timestamps)
     - Null handling tests
     - Enum serialization tests
```

## Common Compilation Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `cannot find symbol: class ObjectMapper (package com.fasterxml.jackson.databind)` | Package rename | Update import to `tools.jackson.databind.ObjectMapper` |
| `cannot find symbol: class JsonProcessingException` | Package rename or exception hierarchy | Update import; consider `JacksonException` |
| `error: writeValueAsString() in ObjectMapper cannot override... checked exception` | `IOException` removed from method signature | Remove `throws IOException` declaration |
| `UnsupportedOperationException: mapper is immutable` | Post-construction mutation | Move configuration to builder |
| `Module not found: JavaTimeModule` | Module now built-in | Remove registration; verify dependency removed |

## After Migration

Once the code compiles and tests pass, run your JSON serialization tests carefully. The behavioral defaults in Jackson 3 are cleaner but may differ from what Jackson 2 produced:

- **Date serialization**: Verify ISO 8601 format if you had `WRITE_DATES_AS_TIMESTAMPS` disabled (should be the same)
- **Null handling**: Default is now `NON_ABSENT` in some contexts (more aggressive null removal)
- **Unknown properties**: Default is still to fail on unknown properties — ensure you have `FAIL_ON_UNKNOWN_PROPERTIES` disabled if needed

Integration tests that validate JSON response bodies are your best coverage here. Run them against real serialized output, not just against Java object equality.

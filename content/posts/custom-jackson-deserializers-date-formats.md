---
title: "Custom Jackson Deserializers for Multiple Date Formats"
date: 2021-03-15
draft: false
tags: ["java", "spring-boot", "jackson", "json", "microservices", "serialization"]
description: "How to write custom Jackson deserializers for date fields that arrive in multiple formats — ZonedDateTime with pattern overrides, context-aware LocalDateTime with repair logic, and a pragmatic receipt date extractor."
---

Working with date fields in a JSON API is rarely clean. Different upstream systems send dates differently: full ISO-8601 timestamps with timezone offset, naive local datetimes, partial date strings, or formats that look like ISO-8601 but are not quite. Spring Boot's default Jackson configuration handles one format well. It does not handle three.

This post covers three custom deserializer patterns we settled on after dealing with these cases in production, each targeting a different level of complexity.

## Setup

```groovy
// build.gradle
implementation 'org.springframework.boot:spring-boot-starter-web:2.4.3'
// Jackson 2.12.2 is managed transitively via Spring Boot 2.4.3
```

Spring Boot 2.4.3 manages jackson-databind 2.11.4. To use 2.12.x features explicitly:

```groovy
implementation 'com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.12.2'
```

The JSR-310 module is needed for `ZonedDateTime`, `LocalDateTime`, and other `java.time` types. Spring Boot auto-configures it when present on the classpath.

## Pattern 1: ZonedDateTime with Fallback String Patterns

The built-in `ZonedDateTimeDeserializer` works well for strict ISO-8601 input. The problem comes when upstream systems deviate slightly — sending `2021-01-15 10:30:00+02:00` (space instead of T) or `2021-01-15T10:30:00.000` (no timezone).

Extending `JSR310DateTimeDeserializerBase` lets you intercept the raw token before the parent class processes it:

```java
public class ZonedDateTimeDeserializerWithStringPatternSupport
        extends JSR310DateTimeDeserializerBase<ZonedDateTime> {

    private static final List<DateTimeFormatter> FALLBACK_PATTERNS = List.of(
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ssXXX"),    // space separator, offset
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSXXX"),
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssXXX")
    );

    protected ZonedDateTimeDeserializerWithStringPatternSupport() {
        super(ZonedDateTime.class, DateTimeFormatter.ISO_ZONED_DATE_TIME);
    }

    @Override
    public ZonedDateTime deserialize(JsonParser parser, DeserializationContext context)
            throws IOException {

        if (parser.hasToken(JsonToken.VALUE_STRING)) {
            String raw = parser.getText().trim();
            // Try the default pattern first
            try {
                return ZonedDateTime.parse(raw, DateTimeFormatter.ISO_ZONED_DATE_TIME);
            } catch (DateTimeParseException ignored) {}

            // Try fallback patterns
            for (DateTimeFormatter formatter : FALLBACK_PATTERNS) {
                try {
                    return ZonedDateTime.parse(raw, formatter);
                } catch (DateTimeParseException ignored) {}
            }

            throw new InvalidDefinitionException(parser,
                "Cannot deserialize ZonedDateTime from: " + raw);
        }

        return super.deserialize(parser, context);
    }

    @Override
    protected ZonedDateTime _fromLong(DeserializationContext context, long timestamp) {
        return Instant.ofEpochMilli(timestamp).atZone(ZoneId.systemDefault());
    }

    @Override
    protected ZonedDateTime _fromDecimal(DeserializationContext context, BigDecimal value) {
        return Instant.ofEpochMilli(value.longValue()).atZone(ZoneId.systemDefault());
    }
}
```

Apply at the field level:

```java
public class ProcessingEvent {

    @JsonDeserialize(using = ZonedDateTimeDeserializerWithStringPatternSupport.class)
    private ZonedDateTime submittedAt;

    @JsonDeserialize(using = ZonedDateTimeDeserializerWithStringPatternSupport.class)
    private ZonedDateTime processedAt;
}
```

This approach tries the standard ISO-8601 parser first, so well-formed dates have no overhead. The fallback list is short and explicit — it matches exactly the patterns you expect, rather than attempting arbitrary format guessing.

## Pattern 2: Context-Aware LocalDateTime with Repair Logic

`ContextualDeserializer` is Jackson's mechanism for deserializers that need to read annotations on the field being deserialized. This is useful when you have a single date field type but different repair rules per field.

A common case: dates stored or transmitted as `LocalDateTime` where the year is occasionally corrupted — sent as `0001`, `9999`, or a negative value. Rather than failing the whole object, you want to repair the date to a sentinel value and flag it for downstream handling.

```java
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.FIELD)
public @interface LocalDateTimeParams {
    boolean fixInvalidYearValue() default false;
}
```

```java
public class LocalDateTimeDeserializer extends JsonDeserializer<LocalDateTime>
        implements ContextualDeserializer {

    private final boolean fixInvalidYearValue;

    public LocalDateTimeDeserializer() {
        this.fixInvalidYearValue = false;
    }

    private LocalDateTimeDeserializer(boolean fixInvalidYearValue) {
        this.fixInvalidYearValue = fixInvalidYearValue;
    }

    @Override
    public JsonDeserializer<?> createContextual(DeserializationContext context,
                                                BeanProperty property) {
        if (property != null) {
            LocalDateTimeParams annotation =
                property.getAnnotation(LocalDateTimeParams.class);
            if (annotation != null) {
                return new LocalDateTimeDeserializer(annotation.fixInvalidYearValue());
            }
        }
        return this;
    }

    @Override
    public LocalDateTime deserialize(JsonParser parser, DeserializationContext context)
            throws IOException {
        String raw = parser.getText().trim();
        try {
            LocalDateTime parsed = LocalDateTime.parse(raw, DateTimeFormatter.ISO_LOCAL_DATE_TIME);
            if (fixInvalidYearValue && isInvalidYear(parsed.getYear())) {
                return LocalDateTime.MIN;  // sentinel: 0001-01-01T00:00:00
            }
            return parsed;
        } catch (DateTimeParseException e) {
            throw new JsonParseException(parser, "Cannot parse LocalDateTime: " + raw, e);
        }
    }

    private boolean isInvalidYear(int year) {
        return year < 1900 || year > 9000;
    }
}
```

Usage:

```java
public class ReportEntry {

    @JsonDeserialize(using = LocalDateTimeDeserializer.class)
    private LocalDateTime transactionDate;

    @LocalDateTimeParams(fixInvalidYearValue = true)
    @JsonDeserialize(using = LocalDateTimeDeserializer.class)
    private LocalDateTime expiryDate;  // upstream sometimes sends year 9999
}
```

`transactionDate` uses the default behaviour — invalid years cause a parse error. `expiryDate` uses repair behaviour — invalid years silently become `LocalDateTime.MIN` for downstream handling.

`ContextualDeserializer.createContextual()` is called once per field during Jackson's initialization phase, not on every deserialization. The returned deserializer instance is cached per field, so there is no per-call overhead from annotation inspection.

## Pattern 3: Receipt Date Extraction

Some upstream systems send dates embedded in longer strings — a datetime where only the date portion is meaningful, a timestamp with trailing metadata, or a mixed-format field where only the first N characters are useful.

The simplest approach: extract by position and parse:

```java
public class ReceiptDateDeserializer extends JsonDeserializer<LocalDate> {

    @Override
    public LocalDate deserialize(JsonParser parser, DeserializationContext context)
            throws IOException {
        String raw = parser.getText();
        if (raw == null || raw.length() < 10) {
            return null;
        }
        // Take the first 10 characters: "YYYY-MM-DD"
        String datePart = raw.substring(0, 10);
        try {
            return LocalDate.parse(datePart, DateTimeFormatter.ISO_LOCAL_DATE);
        } catch (DateTimeParseException e) {
            return null;  // treat unparseable dates as absent
        }
    }
}
```

```java
public class Receipt {

    @JsonDeserialize(using = ReceiptDateDeserializer.class)
    private LocalDate receiptDate;  // upstream sends "2021-03-10T00:00:00.000Z"
}
```

This is deliberately minimal. The field comes from a system that always sends ISO-8601 datetimes, and the time portion is always midnight UTC and carries no information. Extracting by position is more robust than parsing the full datetime and discarding the time — it works regardless of whether the time zone suffix changes format.

Returning `null` on parse failure is intentional: the downstream code already handles absent receipt dates gracefully, and logging a warning for every unparseable date from a specific upstream system would be noise.

## Registering Deserializers Globally

If the same deserializer applies to all fields of a type across the application, register it in a `Jackson2ObjectMapperBuilderCustomizer` rather than annotating each field:

```java
@Configuration
public class JacksonConfiguration {

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer customizer() {
        return builder -> builder
            .deserializerByType(ZonedDateTime.class,
                new ZonedDateTimeDeserializerWithStringPatternSupport());
    }
}
```

Field-level `@JsonDeserialize` overrides the global registration for that specific field. Use global registration for a consistent default; use field-level for exceptions to that default.

## What We Found in Practice

The fallback pattern list in the `ZonedDateTime` deserializer needs to be kept short and ordered by expected frequency. Every additional pattern adds a `try/catch` on the hot path for any input that doesn't match the primary format. We kept it to three patterns covering the actual variants observed, not an exhaustive list of all possible date formats.

The `ContextualDeserializer` approach scales well: you add behaviour by annotating fields, not by writing new deserializer classes. The annotation is the documentation — a reviewer reading the field definition can see immediately that this field has repair logic applied.

The receipt date extractor is the kind of deserializer that looks too simple to be worth writing as a class. It is worth it because the extraction logic is in one place, and when the upstream format changes, there is one class to update rather than N scattered string operations.

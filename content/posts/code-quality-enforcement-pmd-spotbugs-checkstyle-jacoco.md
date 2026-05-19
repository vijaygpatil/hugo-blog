---
title: "Code Quality Enforcement in a Java Microservice: PMD, SpotBugs, Checkstyle, and JaCoCo"
date: 2019-05-07
draft: false
tags: ["java", "spring-boot", "code-quality", "pmd", "spotbugs", "checkstyle", "jacoco", "gradle", "microservices"]
description: "How we enforce code quality automatically in a Java microservice — static analysis with PMD and SpotBugs, style enforcement with Checkstyle, and coverage gates with JaCoCo, all wired into the Gradle build."
---

Code review catches a lot of things. It doesn't catch everything, and it doesn't catch the same class of error consistently — different reviewers notice different things, and review thoroughness varies with time pressure. Static analysis tools are not a replacement for code review, but they fill in the gaps for a specific category of problems: things that can be detected mechanically without understanding the code's intent.

This post covers the four tools we use in our Java microservices and how we've configured them. The setup is in Gradle; the principles apply equally to Maven.

## The Four Tools

**PMD** — static analysis that identifies code patterns associated with bugs, performance problems, and complexity. Examples: unused variables, empty catch blocks, methods that are too long or too complex.

**SpotBugs** — bytecode-level bug detection. Works on compiled classes, not source code, which means it can catch things source analysis can't: null dereferences that only manifest at runtime, synchronisation issues, resource leaks.

**Checkstyle** — style enforcement. Not tabs-vs-spaces debates, but the structural consistency that makes a codebase navigable: naming conventions, line length, import organisation.

**JaCoCo** — test coverage measurement with configurable thresholds that fail the build if coverage drops below defined minimums.

Together they give you automated enforcement of a quality baseline that doesn't depend on any individual reviewer remembering to check.

## Gradle Setup

```groovy
// build.gradle
plugins {
    id 'java'
    id 'org.springframework.boot' version '2.1.5.RELEASE'
    id 'io.spring.dependency-management' version '1.0.7.RELEASE'
    id 'pmd'
    id 'com.github.spotbugs' version '2.0.0'
    id 'checkstyle'
    id 'jacoco'
}
```

All four are available as Gradle plugins. PMD, Checkstyle, and JaCoCo are built into Gradle; SpotBugs requires the community plugin.

## PMD

PMD analyses source code against a set of rules grouped into rulesets. Rather than enabling every rule (which produces enormous noise), we maintain a `ruleset.xml` that specifies exactly what we care about.

```groovy
pmd {
    toolVersion = '6.15.0'
    ignoreFailures = false
    sourceSets = [sourceSets.main]  // main only, not test
    ruleSetFiles = files('config/pmd/ruleset.xml')
    ruleSets = []  // disable built-in rulesets, use ours exclusively
}
```

`ignoreFailures = false` makes PMD violations build-breaking. Without this, violations are reported but ignored.

`sourceSets = [sourceSets.main]` applies PMD to production code only. Test code has different norms — temporary variables, large test methods, relaxed naming — and enforcing production code rules there generates constant false positives.

The ruleset covers three areas we care about most:

```xml
<!-- config/pmd/ruleset.xml -->
<?xml version="1.0"?>
<ruleset name="Custom Rules"
    xmlns="http://pmd.sourceforge.net/ruleset/2.0.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://pmd.sourceforge.net/ruleset/2.0.0
        http://pmd.sourceforge.net/ruleset_2_0_0.xsd">

    <description>Project rules</description>

    <!-- Complexity -->
    <rule ref="category/java/design.xml/CyclomaticComplexity">
        <properties>
            <property name="classReportLevel" value="80"/>
            <property name="methodReportLevel" value="15"/>
        </properties>
    </rule>
    <rule ref="category/java/design.xml/NPathComplexity">
        <properties>
            <property name="reportLevel" value="250"/>
        </properties>
    </rule>
    <rule ref="category/java/design.xml/TooManyMethods">
        <properties>
            <property name="maxmethods" value="20"/>
        </properties>
    </rule>
    <rule ref="category/java/design.xml/TooManyFields">
        <properties>
            <property name="maxfields" value="25"/>
        </properties>
    </rule>

    <!-- Bug-prone patterns -->
    <rule ref="category/java/errorprone.xml/EmptyCatchBlock"/>
    <rule ref="category/java/errorprone.xml/ReturnEmptyArrayRatherThanNull"/>
    <rule ref="category/java/errorprone.xml/EqualsNull"/>

    <!-- Best practices -->
    <rule ref="category/java/bestpractices.xml/UnusedImports"/>
    <rule ref="category/java/bestpractices.xml/UnusedLocalVariable"/>
    <rule ref="category/java/bestpractices.xml/UnusedPrivateField"/>
</ruleset>
```

The complexity thresholds bear explanation. A cyclomatic complexity of 15 per method is generous — a method with 15 branches is already hard to reason about — but we started here rather than at a lower number to avoid a massive initial cleanup. The threshold gives us a ceiling that prevents the worst cases while letting us tighten it over time.

## SpotBugs

SpotBugs analyses compiled bytecode using pattern-matching against known bug signatures. It finds things PMD can't: null pointer dereferences that the compiler accepts but will fail at runtime, double-checked locking done incorrectly, `equals()` and `hashCode()` inconsistencies.

```groovy
spotbugs {
    toolVersion = '3.1.12'
    effort = 'max'
    reportLevel = 'low'
    sourceSets = [sourceSets.main]
    excludeFilter = file('config/spotbugs/exclude.xml')
}

spotbugsMain {
    reports {
        html {
            enabled = true
            destination = file("$buildDir/reports/spotbugs/main.html")
        }
    }
}

spotbugsTest {
    ignoreFailures = true  // test code: report but don't fail
}
```

`effort = 'max'` runs all analyses, including the more expensive ones. Build time impact is minimal for a single-service codebase.

`reportLevel = 'low'` includes low-confidence findings. Some will be false positives, but the false negative cost — a real bug slipping through — is higher.

The exclude filter suppresses specific patterns that are either false positives in our codebase or intentional design choices:

```xml
<!-- config/spotbugs/exclude.xml -->
<FindBugsFilter>
    <!--
        EI_EXPOSE_REP / EI_EXPOSE_REP2: returning/storing mutable objects.
        Suppressed for DTOs and domain objects where defensive copying
        would add overhead for no practical safety benefit.
    -->
    <Match>
        <Bug pattern="EI_EXPOSE_REP,EI_EXPOSE_REP2"/>
    </Match>

    <!--
        CT_CONSTRUCTOR_THROW: throwing from constructor.
        Our validation pattern intentionally throws from constructors.
    -->
    <Match>
        <Bug pattern="CT_CONSTRUCTOR_THROW"/>
    </Match>
</FindBugsFilter>
```

The exclude list should be short and each entry should have a comment explaining why the suppression is intentional. A long exclude list usually means the tool is finding real problems that are being systematically hidden.

## Checkstyle

Checkstyle enforces structural and stylistic rules. We use it for the things that matter — the ones that affect readability and navigability — not for aesthetic preferences.

```groovy
checkstyle {
    toolVersion = '8.22'
    configFile = file('config/checkstyle/checkstyle.xml')
    maxWarnings = 0  // treat warnings as errors
    sourceSets = [sourceSets.main]  // exclude test source
}
```

`maxWarnings = 0` is the important setting. Without it, Checkstyle violations generate warnings that accumulate silently. The build passes but the codebase drifts.

Our `checkstyle.xml` covers three areas:

```xml
<?xml version="1.0"?>
<!DOCTYPE module PUBLIC
    "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
    "https://checkstyle.org/dtds/configuration_1_3.dtd">

<module name="Checker">

    <!-- File-level checks -->
    <module name="FileTabCharacter"/>
    <module name="NewlineAtEndOfFile"/>

    <module name="TreeWalker">

        <!-- Naming conventions -->
        <module name="TypeName"/>          <!-- PascalCase for classes/interfaces -->
        <module name="MemberName"/>        <!-- camelCase for instance variables -->
        <module name="MethodName"/>        <!-- camelCase for methods -->
        <module name="ConstantName"/>      <!-- UPPER_SNAKE_CASE for constants -->
        <module name="LocalVariableName"/> <!-- camelCase for local variables -->

        <!-- Structure -->
        <module name="LineLength">
            <property name="max" value="150"/>
        </module>
        <module name="MethodLength">
            <property name="max" value="100"/>
        </module>
        <module name="ParameterNumber">
            <property name="max" value="8"/>
        </module>

        <!-- Imports -->
        <module name="AvoidStarImport"/>
        <module name="UnusedImports"/>
        <module name="IllegalImport"/>

        <!-- Code hygiene -->
        <module name="EmptyBlock"/>
        <module name="NeedBraces"/>        <!-- braces required even for single-line ifs -->
        <module name="EqualsHashCode"/>    <!-- equals() requires hashCode() and vice versa -->
        <module name="MagicNumber">
            <property name="ignoreNumbers" value="-1, 0, 1, 2"/>
        </module>

    </module>
</module>
```

The 150-character line limit is generous. We settled on it because of long generic type signatures and Spring annotations that legitimately produce long lines, and because a tighter limit generates a lot of noise without materially improving readability.

`NeedBraces` is the one that generates the most pushback. Single-line `if` statements without braces — `if (x) return y;` — are common in Java and rarely a problem in isolation. They become a problem during refactoring: someone adds a line to the body, forgets the braces, and introduces a bug. Requiring braces everywhere is a cheap way to prevent a class of error that shows up in incident postmortems more often than it should.

## JaCoCo

JaCoCo instruments compiled bytecode to track which lines and branches are exercised by the test suite. We use it to enforce minimum coverage thresholds that fail the build if they're not met.

```groovy
jacoco {
    toolVersion = '0.8.4'
}

jacocoTestReport {
    reports {
        xml.enabled = true
        html.enabled = true
    }
}

jacocoTestCoverageVerification {
    violationRules {
        rule {
            element = 'BUNDLE'
            limits {
                limit {
                    counter = 'INSTRUCTION'
                    value = 'COVEREDRATIO'
                    minimum = 0.75
                }
                limit {
                    counter = 'BRANCH'
                    value = 'COVEREDRATIO'
                    minimum = 0.65
                }
                limit {
                    counter = 'LINE'
                    value = 'COVEREDRATIO'
                    minimum = 0.80
                }
                limit {
                    counter = 'COMPLEXITY'
                    value = 'COVEREDRATIO'
                    minimum = 0.65
                }
                limit {
                    counter = 'METHOD'
                    value = 'COVEREDRATIO'
                    minimum = 0.80
                }
                limit {
                    counter = 'CLASS'
                    value = 'COVEREDRATIO'
                    minimum = 0.80
                }
            }
        }
    }
}
```

The thresholds warrant some explanation.

**INSTRUCTION vs LINE** — instruction coverage (75%) is more fine-grained than line coverage (80%). A single line may compile to multiple bytecode instructions; instruction coverage distinguishes partial coverage of a line from full coverage.

**BRANCH coverage (65%)** — lower than line coverage intentionally. Full branch coverage is expensive to achieve and frequently produces tests that exist only to hit the branch rather than to verify behaviour. 65% ensures the important decision points are covered without demanding tests for every null check.

**COMPLEXITY coverage (65%)** — similarly, complex code is hard to fully test. The threshold incentivises keeping complexity low rather than writing tests purely to satisfy the gate.

Wire the verification into the `check` task so it runs with the standard build:

```groovy
check.dependsOn jacocoTestCoverageVerification
jacocoTestCoverageVerification.dependsOn jacocoTestReport
```

## Wiring It Together

All four tools run as part of `./gradlew check`:

```
:compileJava
:processResources
:classes
:pmdMain             ← PMD on production code
:spotbugsMain        ← SpotBugs on production classes
:checkstyleMain      ← Checkstyle on production code
:compileTestJava
:processTestResources
:testClasses
:spotbugsTest        ← SpotBugs on test classes (ignoreFailures=true)
:test
:jacocoTestReport    ← Generate coverage report
:jacocoTestCoverageVerification  ← Check coverage thresholds
:check
```

CI runs `./gradlew check` on every pull request. A PR cannot merge if any of these fail.

The static analysis tools (PMD, SpotBugs, Checkstyle) are intentionally limited to main source. Test code is excluded from all three. Tests operate under different constraints — verbose assertions, repeated setup code, temporary variables that exist only to make assertions readable — and applying production code rules to test code generates consistent noise that trains developers to ignore tool output.

## Suppression Annotations

Occasionally a rule fires on code that is correct and the violation cannot be restructured away. PMD, SpotBugs, and Checkstyle all support suppression annotations for exactly this case:

```java
// PMD
@SuppressWarnings("PMD.TooManyMethods")
public class LargeOrchestrationClass { ... }

// SpotBugs
@SuppressFBWarnings(
    value = "NP_NULL_ON_SOME_PATH",
    justification = "Null is validated by the caller contract"
)
public void process(Thing thing) { ... }

// Checkstyle — comment-based
// CHECKSTYLE:OFF MagicNumber
private static final long RETRY_DELAY_MS = 3000;
// CHECKSTYLE:ON MagicNumber
```

The `justification` field on `@SuppressFBWarnings` is mandatory in our codebase — a suppression without an explanation is treated as a code review failure. The annotation says "I looked at this and decided it's acceptable"; the justification says why.

## What This Caught

In the six months after introducing this setup, the tools identified:

- Seventeen instances of `EmptyCatchBlock` that were swallowing exceptions silently
- Three methods with cyclomatic complexity above 25 — all legitimate candidates for refactoring
- Two SpotBugs findings around null handling that became real bugs in staging before the gates were in place
- Coverage gaps that exposed areas of the codebase with no tests at all

The value is not in any single finding but in the guarantee. Once the gates are in place and passing, a new contribution that regresses any of the measured dimensions fails the build visibly rather than silently accumulating technical debt.

---

The configuration files — `ruleset.xml`, `exclude.xml`, `checkstyle.xml` — are worth putting in a shared repository if you run multiple services. The initial setup cost is roughly half a day; the ongoing overhead per developer per day is essentially zero. The tradeoff is clearly in favour of doing it.

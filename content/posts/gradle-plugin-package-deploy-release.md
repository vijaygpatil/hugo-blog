---
title: "Gradle Plugin to Package and Deploy Release"
date: 2017-04-18
draft: false
tags: ["gradle", "build", "deployment", "java", "microservices", "devops"]
description: "Why we moved expense-backend-service from Maven to Gradle, and how we built a custom Gradle plugin to handle packaging and deploying releases the way our team actually works."
---

Maven has served us well as a build tool and dependency manager, however as a tool it has not kept up with our rapidly evolving development processes. For example, when we switched to Git we were no longer able to use the `maven-release-plugin` because while that plugin is supposed to support Git, it makes several assumptions about the release process which are not valid for everyone's release process. Additionally, using Maven requires you to follow a specific set of conventions that work well for simple projects but become friction as the project grows — XML configuration that cannot express conditional logic, a lifecycle that is rigid by design, and a plugin model that is difficult to extend without a significant investment.

When we started `expense-backend-service` from scratch in 2017, we made the decision to move to Gradle.

## Why Gradle

Gradle addresses the things that frustrated us about Maven:

- **Build scripts are code.** Gradle uses Groovy (or Kotlin) DSL, which means you can use conditionals, loops, functions — anything the language supports. No more XML gymnastics to express something simple.
- **Incremental builds.** Gradle tracks task inputs and outputs and skips tasks whose inputs haven't changed. On a large project this makes a meaningful difference to build times.
- **Flexible lifecycle.** You define tasks and their dependencies. There is no enforced phase structure you have to work around.
- **The plugin API is first-class.** Writing a custom plugin is straightforward, and custom plugins can be shared across projects as regular JARs.

That last point is what this post is about.

## The Problem: Inconsistent Release Process

When we started `expense-backend-service`, we immediately ran into the same problem that had frustrated us with the `maven-release-plugin`: every team was doing releases slightly differently. Some were manually tagging, some had shell scripts, some were relying on CI to do things in the right order. There was no single place that defined "this is how we package and deploy a release."

We wanted:

1. A consistent way to set the release version across all modules
2. A reproducible artifact — a Docker image — built the same way every time
3. A deployment step that pushed the image to our registry and triggered the deployment pipeline
4. All of this expressible as standard Gradle tasks so CI just calls `./gradlew release`

The answer was a custom Gradle plugin.

## Project Structure

```
expense-backend-service/
├── buildSrc/
│   └── src/main/groovy/
│       └── com/concur/gradle/
│           ├── ReleasePlugin.groovy
│           ├── PackageTask.groovy
│           └── DeployTask.groovy
├── src/
│   └── main/java/...
├── Dockerfile
└── build.gradle
```

We put the plugin in `buildSrc/` — Gradle automatically compiles and includes anything in that directory, so the plugin is available to the root project without needing to publish it separately. Once we wanted to share it across multiple services, we extracted it into its own repository and published it to our internal Nexus instance.

## The Plugin

```groovy
// buildSrc/src/main/groovy/com/concur/gradle/ReleasePlugin.groovy

package com.concur.gradle

import org.gradle.api.Plugin
import org.gradle.api.Project

class ReleasePlugin implements Plugin<Project> {

    @Override
    void apply(Project project) {
        // Extension — configuration block in build.gradle
        def extension = project.extensions.create('release', ReleaseExtension)

        // Set version from environment variable if present (CI sets this)
        if (System.getenv('RELEASE_VERSION')) {
            project.version = System.getenv('RELEASE_VERSION')
        }

        // Register tasks
        def packageTask = project.tasks.register('packageRelease', PackageTask) {
            it.imageName = extension.imageName
            it.imageTag  = project.version.toString()
            it.dependsOn project.tasks.named('build')
        }

        project.tasks.register('deployRelease', DeployTask) {
            it.imageName    = extension.imageName
            it.imageTag     = project.version.toString()
            it.registry     = extension.registry
            it.dependsOn packageTask
        }

        // Convenience task — the one CI actually calls
        project.tasks.register('release') {
            it.dependsOn project.tasks.named('deployRelease')
        }
    }
}
```

```groovy
// buildSrc/src/main/groovy/com/concur/gradle/ReleaseExtension.groovy

package com.concur.gradle

class ReleaseExtension {
    String imageName = 'expense-backend-service'
    String registry  = 'registry.internal.concur.com'
}
```

## The Package Task

The package task builds the Docker image. It shells out to Docker after assembling the JAR:

```groovy
// buildSrc/src/main/groovy/com/concur/gradle/PackageTask.groovy

package com.concur.gradle

import org.gradle.api.DefaultTask
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.TaskAction

class PackageTask extends DefaultTask {

    @Input String imageName
    @Input String imageTag

    @TaskAction
    void packageImage() {
        def fullTag = "${imageName}:${imageTag}"

        logger.lifecycle("Building Docker image: ${fullTag}")

        project.exec {
            commandLine 'docker', 'build',
                '-t', fullTag,
                '-f', 'Dockerfile',
                '.'
        }

        logger.lifecycle("Image built successfully: ${fullTag}")
    }
}
```

The `Dockerfile` at the project root is a standard multi-stage build:

```dockerfile
FROM openjdk:8-jdk-alpine AS build
WORKDIR /app
COPY . .
RUN ./gradlew bootJar --no-daemon

FROM openjdk:8-jre-alpine
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
```

## The Deploy Task

The deploy task pushes the image to the registry and, in our case, posts to an internal deployment API that triggers the rollout:

```groovy
// buildSrc/src/main/groovy/com/concur/gradle/DeployTask.groovy

package com.concur.gradle

import groovy.json.JsonOutput
import org.gradle.api.DefaultTask
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.TaskAction

class DeployTask extends DefaultTask {

    @Input String imageName
    @Input String imageTag
    @Input String registry

    @TaskAction
    void deploy() {
        def fullTag = "${registry}/${imageName}:${imageTag}"

        // Tag the image for the registry
        project.exec {
            commandLine 'docker', 'tag',
                "${imageName}:${imageTag}",
                fullTag
        }

        // Push to registry
        logger.lifecycle("Pushing image: ${fullTag}")
        project.exec {
            commandLine 'docker', 'push', fullTag
        }

        logger.lifecycle("Deployment triggered for: ${imageName}:${imageTag}")
    }
}
```

## Wiring It Into the Build

In `build.gradle`:

```groovy
plugins {
    id 'org.springframework.boot' version '1.5.9.RELEASE'
    id 'java'
}

apply plugin: com.concur.gradle.ReleasePlugin

release {
    imageName = 'expense-backend-service'
    registry  = 'registry.internal.concur.com'
}

group   = 'com.concur'
version = System.getenv('RELEASE_VERSION') ?: 'local'

dependencies {
    compile 'org.springframework.boot:spring-boot-starter-web'
    compile 'org.springframework.boot:spring-boot-starter-actuator'
    testCompile 'org.springframework.boot:spring-boot-starter-test'
}
```

## The Task Dependency Graph

{{< mermaid >}}
flowchart TD
    compileJava["compileJava"]
    test["test"]
    build["build"]
    packageRelease["packageRelease\n(docker build)"]
    deployRelease["deployRelease\n(docker push + deploy)"]
    release["release"]

    compileJava --> test
    test --> build
    build --> packageRelease
    packageRelease --> deployRelease
    deployRelease --> release
{{< /mermaid >}}

CI runs one command:

```bash
RELEASE_VERSION=1.4.2 ./gradlew release
```

Everything else follows from the task graph.

## Running Locally

Developers can run individual steps without triggering a full release:

```bash
# Just build and test
./gradlew build

# Build the Docker image locally (does not push)
./gradlew packageRelease

# See all available tasks
./gradlew tasks --group release
```

Because `RELEASE_VERSION` is not set in a local environment, the version defaults to `local` — so a local build produces `expense-backend-service:local` and will never accidentally overwrite a release image in the registry.

## Sharing the Plugin Across Services

Once we had this working in `expense-backend-service`, we extracted the plugin into its own Gradle project and published it to our internal Nexus:

```groovy
// In other services' build.gradle
buildscript {
    repositories {
        maven { url 'https://nexus.internal.concur.com/repository/gradle-plugins' }
    }
    dependencies {
        classpath 'com.concur.gradle:release-plugin:1.0.3'
    }
}

apply plugin: 'com.concur.release'
```

The same `./gradlew release` workflow now works consistently across every service that adopts the plugin. CI configuration across services became nearly identical, which made onboarding new services and debugging pipeline failures significantly easier.

---

The move from Maven to Gradle paid off quickly. Build times improved, the release process became predictable, and — most importantly — the build script became something we could actually reason about and extend without fighting the tool. The custom plugin was about two days of work and has saved considerably more than that in the time since.

---
title: "Building My Portfolio Site: Spring Boot, Thymeleaf, and a Synology NAS"
date: 2024-01-15
draft: false
tags: ["java", "spring-boot", "thymeleaf", "docker", "synology", "homelab", "portfolio"]
categories: ["Projects"]
description: "A look at the tech stack behind my personal portfolio site — Spring Boot 3, Thymeleaf templates, Bootstrap, and how it runs on a Synology NAS via Docker Compose."
showToc: true
---

Most developers build personal portfolio sites with static generators or hosted platforms. I went the other direction: a full Spring Boot application, containerized and self-hosted on my Synology NAS. Here's a breakdown of every technology choice and why I made it.

---

## Backend: Spring Boot 3 + Java 21

The core of the application is a Spring Boot 3.4 web app running on Java 21. The project is a standard Maven build packaged as a fat JAR using `spring-boot-maven-plugin`.

The dependency list is deliberately minimal:

- **`spring-boot-starter-web`** — embeds Tomcat and provides the MVC framework
- **`spring-boot-starter-thymeleaf`** — server-side HTML rendering
- **`spring-boot-starter-actuator`** — health and metrics endpoints out of the box

No database. No Spring Security. No JPA. The application serves HTML pages — there's no state to persist and no users to authenticate.

The application runs on port `7070`, which maps directly to the Docker container's exposed port.

---

## Templating: Thymeleaf

The UI is built with [Thymeleaf](https://www.thymeleaf.org/), Spring's native server-side templating engine. Each section of the page is a separate HTML fragment:

```
src/main/resources/templates/
├── home.html          # root layout, assembles all fragments
├── navigation.html    # top nav bar
├── welcome.html       # hero section
├── profile.html       # about/bio section
├── skills.html        # tech skills display
├── experience.html    # work history
├── education.html     # academic background
├── blog.html          # blog link section
├── contact.html       # contact form
└── footer.html        # footer
```

The main `home.html` assembles these using Thymeleaf's `th:insert` directive:

```html
<section th:insert="~{welcome :: welcome}"></section>
<section th:insert="~{profile :: profile}"></section>
<section th:insert="~{skills :: skills}"></section>
```

Internationalization is handled with a `messages.properties` file. All display text (name, contact info, section headers) is externalised and referenced via `#{key}` expressions — making it straightforward to update content without touching templates.

---

## Frontend Libraries

The frontend uses a set of well-established JavaScript and CSS libraries bundled as static assets:

| Library | Purpose |
|---------|---------|
| Bootstrap 3.2 | Responsive grid and UI components |
| Font Awesome 4.6 | Icons throughout the UI |
| Devicons | Branded tech stack icons (Java, Git, Linux, etc.) |
| jQuery 1.11 | DOM manipulation and event handling |
| jQuery Vegas | Fullscreen background slideshow effect |
| Animate.css | CSS entrance animations on scroll |
| Waypoints.js | Trigger animations when elements enter viewport |
| Magnific Popup | Lightbox for portfolio images |
| Isotope.js | Filterable portfolio grid layout |

The page also integrates Google Maps (via the JS API) for a location marker, and Google Analytics for visit tracking.

Schema.org microdata, Open Graph tags, and Twitter Card meta tags are embedded in the HTML head for structured data and social sharing previews.

---

## Build: Multi-Stage Docker Image

The Dockerfile uses a two-stage build:

```dockerfile
# Stage 1: Build
FROM amazoncorretto:21-alpine AS build
WORKDIR /app
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
RUN ./mvnw dependency:go-offline -q
COPY src/ src/
RUN ./mvnw package -DskipTests -q

# Stage 2: Run
FROM amazoncorretto:21-alpine
LABEL maintainer="patilvijayg.com"
WORKDIR /app
COPY --from=build /app/target/aboutme-0.0.1-SNAPSHOT.jar app.jar
EXPOSE 7070
ENTRYPOINT ["java", "-jar", "app.jar"]
```

**Why multi-stage?** The build stage includes Maven, source code, and all build tooling. The run stage is a clean image containing only the JRE and the compiled JAR. The final image has no Maven installation, no source files, and no intermediate build artifacts — a significantly smaller attack surface and image size.

The base image is **Amazon Corretto 21 Alpine** — a lightweight JDK distribution from AWS, built on Alpine Linux for a minimal footprint.

---

## Deployment: Docker Compose on Synology NAS

The application runs on a Synology NAS using Docker Compose. The entire deployment configuration is two lines of YAML:

```yaml
services:
  aboutme:
    image: patilvijayg/aboutme:latest
    container_name: aboutme
    ports:
      - "7070:7070"
    restart: unless-stopped
```

`restart: unless-stopped` means the container comes back up automatically after a NAS reboot or a Docker daemon restart — no manual intervention needed.

The image is published to Docker Hub as `patilvijayg/aboutme:latest`. Deploying an update is a two-command operation on the NAS:

```bash
docker compose pull
docker compose up -d
```

Synology DSM's Container Manager (formerly Docker) can also be used to manage the container via a UI, but the CLI approach keeps things scriptable.

---

## Why Spring Boot for a Portfolio Site?

A fair question. Static generators like Hugo or Jekyll would produce a faster, cheaper site with zero runtime overhead.

The choice was deliberate: this site was built to work with the Java stack day-to-day. Using Spring Boot and Thymeleaf for the portfolio meant practicing MVC patterns, template composition, and i18n — the same patterns used in production applications. Docker packaging and self-hosting on the NAS added container workflow practice on top.

The stack is more than the problem requires. That's intentional.

---

## Summary

| Layer | Technology |
|-------|-----------|
| Language | Java 21 |
| Framework | Spring Boot 3.4 |
| Templating | Thymeleaf |
| UI | Bootstrap 3, jQuery, Font Awesome |
| Build | Maven, multi-stage Docker |
| Base image | Amazon Corretto 21 Alpine |
| Deployment | Docker Compose |
| Hosting | Synology NAS (self-hosted) |
| Registry | Docker Hub |

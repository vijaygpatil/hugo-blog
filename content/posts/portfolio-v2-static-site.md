---
title: "Rebuilding My Portfolio: Ditching Spring Boot for Pure Static HTML"
date: 2026-04-15
draft: false
tags: ["html5", "css3", "javascript", "docker", "synology", "github-actions", "homelab", "portfolio"]
categories: ["Projects"]
description: "Why I scrapped the Spring Boot portfolio and rebuilt it as a pure static HTML site — and how a simpler deployment pipeline on the Synology NAS made everything better."
showToc: true
---

The [original portfolio](/posts/portfolio-site-tech-stack/) was a Spring Boot application with Thymeleaf templates, a Maven build, a multi-stage Docker image, and a container running on my Synology NAS. It worked, but it was overengineered for what it actually did: serve a single-page site that never changes at runtime.

So I rebuilt it from scratch — no framework, no build step, no container. Just a single `index.html` file deployed via git.

---

## What Changed and Why

The old site had a real backend because it was built to practice the Spring MVC + Thymeleaf stack. That made sense at the time. The new site has different goals: faster loading, simpler deployment, no moving parts to maintain, and modern frontend techniques applied directly without a framework in the way.

The tradeoff is clear: lose server-side rendering, gain zero operational overhead.

---

## The Stack

The entire site is a single `index.html` with locally bundled assets. No npm, no build tools, no compilation.

| Layer | Technology |
|-------|-----------|
| Markup | HTML5 (semantic, Schema.org microdata) |
| Styling | CSS3 (custom properties, flexbox, gradients, animations) |
| Interactivity | Vanilla JavaScript + jQuery |
| UI framework | Bootstrap 3.2 |
| Icons | Font Awesome 4.6 + Devicons |
| Custom fonts | Laila (headings), Raleway (resume), Open Sans (body) |
| PDF generation | html2pdf.js + jsPDF |
| Deployment | GitHub Actions → SSH → `git pull` on NAS |
| Hosting | Synology NAS (Web Station, Nginx) |

---

## HTML5 and Structured Data

The markup uses HTML5 semantic elements throughout and includes three layers of structured metadata:

**Schema.org microdata** on the `<body>` element (`itemtype="http://schema.org/Person"`) annotates the page for search engine parsing — name, job title, employer, skills, social profiles.

**JSON-LD** block in the `<head>` provides the same data in a format Google explicitly prefers for rich results:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Vijay Patil",
  "jobTitle": "Senior Software Engineer",
  "worksFor": { "@type": "Organization", "name": "SAP Concur" },
  "knowsAbout": ["Java", "Spring Boot", "Kubernetes", "AWS"]
}
</script>
```

**Open Graph + Twitter Card** meta tags handle social sharing previews — title, description, image, and URL all specified for both platforms.

---

## CSS3: No Preprocessor Needed

The custom stylesheet (`css/main.css`) uses modern CSS directly — no Sass, no Less, no PostCSS.

The hero section background is a layered CSS gradient with an SVG hexagon tile pattern inlined as a `data:` URI:

```css
#page-welcome {
    background: linear-gradient(135deg, #1c2e4a 0%, #1e3a5f 35%, #1a4980 70%, #1c2e4a 100%);
}
.welcome-hex-bg {
    background-image: url("data:image/svg+xml,...");
    background-size: 56px 100px;
}
```

Pseudo-elements (`::before`, `::after`) add two subtle radial-gradient glows — one blue, one green — layered behind the content without any extra DOM nodes.

The floating tech icons on the hero image are positioned absolutely using percentage-based coordinates, each with a `drop-shadow` filter:

```css
.desk-icon {
    position: absolute;
    filter: drop-shadow(0 0 7px rgba(100,181,246,0.55));
    transition: transform 0.25s ease;
}
.desk-icon-java { top: 1%; left: 13%; }
.desk-icon-k8s  { top: 1%; left: 57%; }
```

Responsive breakpoints use a single media query at `840px` — the layout collapses from a side-by-side hero to a stacked single-column without JavaScript.

---

## Inline SVG Animations

The server rack illustration in the hero is a hand-crafted inline SVG with CSS `<animate>` elements that make the LEDs blink and fan rings pulse at different rates:

```svg
<circle cx="188" cy="46" r="3" fill="#00ff88" opacity="0.9">
    <animate attributeName="opacity" values="0.9;0.2;0.9" dur="2.1s" repeatCount="indefinite"/>
</circle>
```

Each LED has a different `dur` and `begin` offset so they don't blink in sync — giving the rack a realistic "live hardware" feel. The fan grilles are concentric circles with a semi-transparent stroke that pulses opacity to simulate rotation. All of this is pure SVG — no JavaScript, no canvas, no GIF.

---

## PDF Resume Generation

The "Download CV" button generates a PDF client-side using **html2pdf.js** (which wraps html2canvas and jsPDF). A hidden `<div>` in the page holds a fully styled resume layout — Raleway headings, timeline-style experience rows, a QR code pointing to the live profile URL.

When the button is clicked:

1. **QRCode.js** renders a QR code into the hidden resume div
2. **html2pdf** rasterises the div at 2× scale via html2canvas
3. jsPDF packs that into an A4 PDF
4. The browser triggers a download of `Vijay-Patil-Resume.pdf`

No server involved. No API call. The whole resume is generated and downloaded entirely in the browser.

---

## Contact Form: Fetch API

The contact form submits via `fetch()` to a small contact microservice running on the NAS at a separate port:

```javascript
fetch('https://patilvijayg.synology.me:3443/contact', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, message })
})
```

The form handles success, error, and network-failure states inline — no page reload, no redirect. The old Spring Boot site had the same form wired to a `SmtpMailSender` controller on the backend; moving that to a dedicated microservice keeps the portfolio itself completely static.

---

## Deployment: Git Pull Instead of Docker

This is the biggest operational change from v1.

The old site ran as a Docker container. Every update meant building a new image, pushing it to Docker Hub, and pulling it on the NAS. The new site is static files — so the deployment is just a git pull.

The GitHub Actions workflow:

```yaml
- name: Deploy to Synology via SSH
  uses: appleboy/ssh-action@v1.0.0
  with:
    host: ${{ secrets.SYNOLOGY_HOST }}
    username: ${{ secrets.SYNOLOGY_USERNAME }}
    password: ${{ secrets.SYNOLOGY_PASSWORD }}
    port: ${{ secrets.SYNOLOGY_SSH_PORT }}
    script: |
      cd /volume2/web/portfolio
      git fetch origin
      git reset --hard origin/main
      echo "Deployment complete: $(date)"
```

On every push to `main`, GitHub Actions SSHes into the NAS and runs `git reset --hard origin/main`. That's the entire deploy. No build, no image, no registry, no container restart.

Synology Web Station's Nginx serves the files in `/volume2/web/portfolio` directly — same setup as the blog, just a different document root.

---

## Custom Fonts

The site uses three typefaces, all self-hosted (no Google Fonts CDN dependency at render time):

- **Laila** — decorative serif for the hero name and nav labels; loaded from `fonts/laila-bold.woff` and `fonts/laila-regular.woff`
- **Raleway** — geometric sans for the hidden resume PDF layout
- **Open Sans** — body text for the resume PDF

Laila is loaded via Google Fonts for the live site (acceptable CDN dependency there), while Raleway and Open Sans are linked via Google Fonts only in the hidden PDF template — they don't affect the main page render path.

---

## What Was Dropped

Compared to v1, the rebuild removed:

- Spring Boot, Thymeleaf, Maven — no JVM, no startup time, no heap
- Docker container and Docker Hub registry — no image builds
- Multi-stage Dockerfile — not needed for static files
- Server-side i18n (`messages.properties`) — content is now inline HTML
- `spring-boot-starter-actuator` — health endpoints replaced by the GitHub Actions curl health check

The contact form's SMTP handler moved to a dedicated microservice. Everything else the backend was doing (rendering templates, serving static assets) is now handled by Nginx directly.

---

## Summary

| | v1 (Spring Boot) | v2 (Static) |
|--|--|--|
| Runtime | JVM + Tomcat | None (Nginx) |
| Build | Maven + Docker | None |
| Deploy | Docker Hub → `docker compose pull` | `git reset --hard` via SSH |
| Time to deploy | ~2 min | ~10 sec |
| Fonts | System / CDN only | Self-hosted (Laila, Raleway) |
| Animations | CSS (Animate.css) | CSS + inline SVG `<animate>` |
| Resume PDF | Not supported | Client-side via html2pdf.js |
| Structured data | Schema.org microdata | Microdata + JSON-LD |
| Container | Yes (`restart: unless-stopped`) | No |

The static rebuild is faster to load, faster to deploy, and has nothing to break at 2am. The Spring Boot version was the right choice when practicing that stack. The static version is the right choice for a portfolio that just needs to be live and maintainable with zero effort.

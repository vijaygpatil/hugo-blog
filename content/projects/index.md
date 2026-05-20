---
title: "Projects"
date: 2026-05-20
layout: "simple"
---

A selection of personal projects — things I built because I wanted to solve a real problem, learn something properly, or just see if it was possible. Most of them live on my home lab and see daily use.

---

## MCP Toolserver for Claude

**Domain-specific tooling that turns Claude into an engineering expert for my team's daily work.**

I built a custom MCP (Model Context Protocol) server that gives Claude deep knowledge of my team's engineering stack: which Elasticsearch indices to query, which fields hold what data, how to format SQL queries for our database schema, which procedures to follow for pre-deployment checks. The result is a Claude that can answer on-call questions in minutes instead of thirty minutes of manual log archaeology.

The server exposes purpose-built tools — not generic search wrappers — each encoding the tribal knowledge that usually lives in engineers' heads. Health checks, integration test analysis, support triage, database investigation: all available as structured, reusable tools.

→ [Read the full writeup](/posts/building-mcp-toolserver-claude/)

---

## Portfolio Site v2 — Pure Static HTML

**A complete rebuild of my personal portfolio: from Spring Boot to zero-dependency static HTML.**

After running a Spring Boot/Thymeleaf portfolio for two years I decided the complexity wasn't earning its keep. The rebuild: plain HTML5, CSS3, vanilla JavaScript, zero frameworks, zero build tools. The deployment pipeline is a GitHub Actions workflow that pushes to my Synology NAS on every commit. Faster to load, easier to maintain, and the entire site fits in a handful of files.

→ [Read the rebuild story](/posts/portfolio-v2-static-site/) · [Earlier Spring Boot version](/posts/portfolio-site-tech-stack/)

---

## This Blog — Hugo on Synology NAS

**A self-hosted Hugo blog with GitHub Actions CI/CD on a home Synology NAS.**

I run this blog on hardware I own. Hugo generates the static site, GitHub Actions deploys it automatically on every push, and a Synology NAS serves it behind an nginx reverse proxy. The whole pipeline — edit, commit, push, deploy — takes about 45 seconds and involves no third-party hosting. I wrote up the full setup for anyone who wants to do the same.

→ [Read the setup guide](/posts/synology-nas-blog-setup/)

---

## Whole-House Hi-Res Audio

**A whole-house audio system delivering 32-bit/384kHz audio to every room in sync.**

This one started as a curiosity and turned into something I use every day. Lyrion Music Server runs on the Synology NAS, PiCorePlayer instances on Raspberry Pis handle the endpoints, and WIIM amplifiers drive the speakers. Every room in the house plays the same music at exactly the same moment — no echo, no drift — at the full resolution of the source file.

The system handles 32-bit/384kHz FLAC, DSD, Tidal, and Spotify. No compression, no resampling, no subscription to a streaming service to hear what you already own at full quality.

→ [Read the full build](/posts/whole-house-audio-lyrion/)

---

*More engineering notes and project writeups in [Posts](/posts/).*

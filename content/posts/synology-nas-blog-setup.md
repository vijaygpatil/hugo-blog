---
title: "How I Set Up This Blog on My Synology NAS"
date: 2026-05-12
draft: false
tags: ["homelab", "synology", "hugo", "self-hosting"]
categories: ["Homelab"]
description: "A quick walkthrough of how I set up this Hugo blog hosted on my Synology NAS with automatic deployment via GitHub Actions."
showToc: true
---

This blog runs on my Synology NAS using Hugo and GitHub Actions. Here's the short version of how it works.

## The Stack

- **[Hugo](https://gohugo.io/)** — static site generator, writes posts in Markdown
- **[PaperMod](https://github.com/adityatelange/hugo-PaperMod)** — clean, fast theme built for technical blogs
- **Synology Web Station** — serves the static HTML files
- **GitHub Actions** — automatically builds and deploys on every `git push`

## How Deployment Works

1. Write a post in VS Code (Markdown)
2. `git push` to GitHub
3. GitHub Action triggers: builds Hugo site, SCPs files to NAS
4. Post is live in ~30 seconds

No Docker, no Node.js, no maintenance overhead. Just files on a NAS.

## Why Hugo Over Ghost or WordPress?

I wanted something lightweight with no runtime dependencies. Hugo generates plain HTML — nothing to update, nothing to break, nothing to secure beyond the NAS itself.

More homelab posts coming soon.

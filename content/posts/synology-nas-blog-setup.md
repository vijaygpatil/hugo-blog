---
title: "How I Set Up This Blog on My Synology NAS"
date: 2024-11-03
draft: false
tags: ["homelab", "synology", "hugo", "github-actions", "self-hosting"]
categories: ["Homelab"]
description: "A complete walkthrough of how I set up this Hugo blog on a Synology NAS with automatic deployment via GitHub Actions — from zero to live in under an hour."
showToc: true
---

This blog runs on my Synology NAS. Posts are written in Markdown on my Mac, committed to GitHub, and automatically deployed to the NAS via GitHub Actions. No Docker, no Node.js, no maintenance overhead.

Here's every detail of how I set it up.

---

## Why This Stack

I looked at Ghost and WordPress first. Both are capable, but both require a running server process, a database, and ongoing updates. I didn't want to manage any of that on my NAS.

Hugo generates plain HTML files. There's nothing to update, nothing to break at 2am, and nothing to secure beyond the NAS itself. Synology Web Station can serve static files natively — no PHP, no database required.

The full stack:

| Component | Tool | Why |
|-----------|------|-----|
| Static site generator | [Hugo](https://gohugo.io/) | Fast, no runtime deps, Markdown-based |
| Theme | [PaperMod](https://github.com/adityatelange/hugo-PaperMod) | Clean, dark mode, code highlighting, ToC |
| Hosting | Synology Web Station | Already on my NAS, serves static files |
| Deployment | GitHub Actions | Automated on every `git push` |
| Domain | Synology DDNS (`patilvijayg.synology.me`) | Free with Synology account |

---

## Prerequisites

**On the Mac:**

```bash
brew install hugo
hugo version
# hugo v0.161.1+extended darwin/arm64
```

**On the NAS:**
- Web Station installed (from Package Center)
- SSH enabled: DSM → Control Panel → Terminal & SNMP → Enable SSH service
- A user account with SSH access and write permissions to `/volume2/web/`

---

## Step 1: Create the Hugo Project

```bash
cd ~/IdeaProjects
hugo new site hugo-blog
cd hugo-blog
```

This scaffolds the project structure:

```
hugo-blog/
├── archetypes/       # post templates
├── content/          # your posts go here
├── layouts/          # custom templates (empty for now)
├── static/           # images, files
├── themes/           # theme lives here
└── hugo.toml         # site configuration
```

---

## Step 2: Add the PaperMod Theme

PaperMod is added as a git submodule — this means the theme stays linked to its upstream repo and can be updated independently.

```bash
git init
git submodule add --depth=1 https://github.com/adityatelange/hugo-PaperMod themes/PaperMod
git add .gitmodules themes/PaperMod
git commit -m "chore: add PaperMod theme as submodule"
```

The `--depth=1` flag does a shallow clone — you get the latest version without the full git history, which keeps the repo small.

---

## Step 3: Configure the Site

Replace `hugo.toml` with the full site config:

```toml
baseURL = "https://blog.patilvijayg.synology.me/"
locale = "en-us"
title = "Vijay's Homelab & Tech Blog"
theme = "PaperMod"

[params]
  description = "Homelab experiments, DIY projects, and technical notes on AI and software engineering"
  ShowReadingTime = true
  ShowToc = true
  defaultTheme = "auto"
  homeInfoParams = { Title = "Hi, I'm Vijay 👋", Content = "Welcome to my homelab and tech blog. I write about DIY projects, AI experiments, and software engineering." }

[taxonomies]
  tag = "tags"
  category = "categories"

[outputs]
  home = ["HTML", "RSS", "JSON"]

[markup]
  [markup.highlight]
    noClasses = false
    lineNos = false
```

Key params:
- `defaultTheme = "auto"` — follows the OS light/dark preference
- `ShowReadingTime = true` — shows estimated read time on each post
- `ShowToc = true` — enables table of contents (per-post `showToc` overrides this)
- `[outputs]` — generates RSS feed and JSON index (used for search)
- `[markup.highlight]` — enables proper syntax highlighting in code blocks

---

## Step 4: Create a Post Archetype

The archetype is a template that `hugo new` uses when creating posts. Replace `archetypes/default.md`:

```markdown
---
title: "{{ replace .File.ContentBaseName "-" " " | title }}"
date: {{ .Date }}
draft: true
tags: []
categories: []
description: ""
showToc: true
---

Write your post here.
```

Now `hugo new posts/my-post.md` auto-fills the title from the filename and sets `draft: true` so you don't accidentally publish unfinished posts.

---

## Step 5: Create the GitHub Repository

Create a new repo at `github.com/new` named `hugo-blog`. Don't initialize with README — the local repo already has commits.

```bash
git remote add origin https://github.com/vijaygpatil/hugo-blog.git
git branch -M main
git push -u origin main
```

The `themes/PaperMod` directory shows as a submodule link (not the files) on GitHub — that's correct behavior for submodules.

---

## Step 6: Add the GitHub Actions Workflow

This is the core of the automated deployment. Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Synology NAS

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout code
      uses: actions/checkout@v4
      with:
        submodules: true        # required — fetches PaperMod theme

    - name: Setup Hugo
      uses: peaceiris/actions-hugo@v3
      with:
        hugo-version: 'latest'

    - name: Build Hugo site
      run: hugo --minify         # outputs to public/

    - name: Prepare target directory on NAS
      uses: appleboy/ssh-action@v1.0.0
      with:
        host: ${{ secrets.SYNOLOGY_HOST }}
        username: ${{ secrets.SYNOLOGY_USERNAME }}
        password: ${{ secrets.SYNOLOGY_PASSWORD }}
        port: ${{ secrets.SYNOLOGY_SSH_PORT }}
        script: |
          mkdir -p /volume2/web/blog

    - name: Copy built files to Synology
      uses: appleboy/scp-action@v0.1.7
      with:
        host: ${{ secrets.SYNOLOGY_HOST }}
        username: ${{ secrets.SYNOLOGY_USERNAME }}
        password: ${{ secrets.SYNOLOGY_PASSWORD }}
        port: ${{ secrets.SYNOLOGY_SSH_PORT }}
        source: "public/*"
        target: "/volume2/web/blog/"
        strip_components: 1     # copies contents of public/, not public/ itself

    - name: Health Check
      run: |
        sleep 10
        HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://blog.patilvijayg.synology.me/ || echo "000")
        if [ "$HTTP_STATUS" = "200" ]; then
          echo "✅ Blog is accessible (HTTP $HTTP_STATUS)"
        else
          echo "⚠️  Blog returned HTTP status $HTTP_STATUS"
        fi
```

**What each step does:**
1. **Checkout** — clones the repo including the PaperMod submodule (`submodules: true` is essential)
2. **Setup Hugo** — installs Hugo on the GitHub Actions runner
3. **Build** — `hugo --minify` generates the full static site into `public/`
4. **SSH into NAS** — creates `/volume2/web/blog/` if it doesn't exist
5. **SCP files** — copies everything from `public/` to `/volume2/web/blog/` on the NAS
6. **Health check** — curls the live URL 10 seconds after deploy to confirm it's up

---

## Step 7: Configure GitHub Secrets

Go to the repo on GitHub → Settings → Secrets and variables → Actions → New repository secret.

Add these four secrets:

| Secret | Value |
|--------|-------|
| `SYNOLOGY_HOST` | Your NAS hostname (e.g. `patilvijayg.synology.me`) |
| `SYNOLOGY_USERNAME` | SSH username on your NAS |
| `SYNOLOGY_PASSWORD` | SSH password for that user |
| `SYNOLOGY_SSH_PORT` | SSH port (Synology default is `22`) |

These are the same secrets used in my other repos (`portfolio`, `SelfStudy`) — the naming is identical so they're easy to reuse across projects.

---

## Step 8: Configure Synology Web Station

This is a one-time setup in DSM.

**1. Install Web Station** (if not already installed):
DSM → Package Center → search "Web Station" → Install

**2. Create a Virtual Host**:
Web Station → Virtual Host → Create

| Field | Value |
|-------|-------|
| Hostname | `blog.patilvijayg.synology.me` |
| Document root | `/volume2/web/blog` |
| HTTP port | `80` |
| HTTPS port | `443` |
| Backend server | Nginx |

Click OK. Web Station will now serve whatever files are in `/volume2/web/blog/`.

**3. Verify SSH is enabled**:
DSM → Control Panel → Terminal & SNMP → Enable SSH service

This must be on for the GitHub Actions SSH step to connect.

---

## Step 9: First Deploy

Push anything to `main` to trigger the workflow:

```bash
git add .
git commit -m "ci: add deploy workflow"
git push
```

Go to the repo on GitHub → Actions tab. Watch the workflow run. On first run, you might see an SSH authentication error if the password secret is wrong — just correct it in Settings → Secrets and re-run the job.

Once all steps show green checkmarks, the blog is live.

---

## Troubleshooting: SSH Authentication Failure

The first deploy failed with:

```
ssh: handshake failed: ssh: unable to authenticate,
attempted methods [none password], no supported methods remain
```

This meant `SYNOLOGY_PASSWORD` was set to the wrong value. Fix: go to Settings → Secrets → SYNOLOGY_PASSWORD → Update → enter the correct password → re-run the failed workflow.

---

## Day-to-Day Posting Workflow

Once everything is set up, creating a new post takes about 30 seconds of setup:

```bash
# 1. Create the post file
hugo new posts/my-post-title.md

# 2. Write in VS Code
code content/posts/my-post-title.md

# 3. Preview locally (live reload)
hugo server
# open http://localhost:1313

# 4. Set draft: false in the front matter when ready

# 5. Publish
git add content/posts/my-post-title.md
git commit -m "post: my post title"
git push
# GitHub Action builds and deploys in ~30 seconds
```

The `hugo server` command starts a local dev server with live reload — every time you save the Markdown file, the browser refreshes automatically. Run it in a separate terminal while you write.

---

## .gitignore

```
public/
resources/
.hugo_build.lock
.DS_Store
```

The `public/` directory is Hugo's build output — never commit it. GitHub Actions builds it fresh on every deploy.

---

## What This Cost

- **Synology NAS**: already owned
- **Synology DDNS**: free with Synology account
- **GitHub**: free (public or private repo)
- **GitHub Actions**: free tier covers this easily (~2 minutes per deploy)
- **Hugo**: free, open source
- **PaperMod**: free, open source

Total ongoing cost: **$0/month**.

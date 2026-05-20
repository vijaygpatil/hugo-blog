# Unsplash Feature Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a feature image to each post in `content/posts/` by fetching the best-matching photo from Unsplash and converting each flat `.md` post into a Hugo page bundle.

**Architecture:** A single Python script reads each post's tags from front matter, queries the Unsplash API, downloads the top photo as `feature.jpg`, converts the flat `.md` file into a page bundle directory (`posts/<slug>/index.md` + `feature.jpg`). Congo theme auto-detects `feature*` images in page bundles — no front matter changes needed.

**Tech Stack:** Python 3, `requests` (HTTP), `python-frontmatter` (YAML front matter parsing), Unsplash REST API v1

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `scripts/add_feature_images.py` | Create | Main script: reads posts, queries Unsplash, downloads images, converts to page bundles |
| `content/posts/<slug>/index.md` | Create (×13) | Post content moved from flat `.md` into bundle folder |
| `content/posts/<slug>/feature.jpg` | Create (×13) | Unsplash photo, named so Congo auto-detects it |

---

### Task 1: Install dependencies

**Files:**
- No files changed

- [ ] **Step 1: Install required Python packages**

```bash
pip3 install requests python-frontmatter
```

Expected output:
```
Successfully installed requests-2.x.x python-frontmatter-1.x.x
```

- [ ] **Step 2: Verify installation**

```bash
python3 -c "import requests; import frontmatter; print('OK')"
```

Expected: `OK`

---

### Task 2: Write the script

**Files:**
- Create: `scripts/add_feature_images.py`

- [ ] **Step 1: Create the scripts directory**

```bash
mkdir -p /Users/i861347/IdeaProjects/hugo-blog/scripts
```

- [ ] **Step 2: Write the script**

Create `/Users/i861347/IdeaProjects/hugo-blog/scripts/add_feature_images.py` with this content:

```python
#!/usr/bin/env python3
"""
Adds feature images to Hugo posts by fetching photos from Unsplash.
Converts flat .md posts into page bundles:
  content/posts/foo.md  →  content/posts/foo/index.md
                                              feature.jpg
"""

import os
import sys
import shutil
import requests
import frontmatter

POSTS_DIR = os.path.join(os.path.dirname(__file__), "..", "content", "posts")
UNSPLASH_API = "https://api.unsplash.com/search/photos"

# Keyword overrides per post slug (slug = filename without .md)
KEYWORD_OVERRIDES = {
    "athena-query-optimization":     "sql database query",
    "building-mcp-toolserver-claude": "artificial intelligence tools",
    "claude-agent-view-explained":    "ai automation productivity",
    "dynamodb-101":                   "database architecture",
    "git-worktrees":                  "git developer workflow",
    "intellij-idea-tour":             "java programming ide",
    "parallel-integration-tests":     "software testing ci",
    "portfolio-site-tech-stack":      "java spring web",
    "portfolio-v2-static-site":       "static website html",
    "redis-bandwidth-hidden-constraint": "redis server performance",
    "spring-boot-4-jackson-3-migration": "java spring boot",
    "synology-nas-blog-setup":        "nas homelab server",
    "whole-house-audio-lyrion":       "audio music home",
}


def keywords_for_post(slug, tags):
    if slug in KEYWORD_OVERRIDES:
        return KEYWORD_OVERRIDES[slug]
    # Fall back to first two tags joined
    return " ".join(tags[:2]) if tags else slug.replace("-", " ")


def fetch_photo_url(query, access_key):
    params = {
        "query": query,
        "per_page": 1,
        "orientation": "landscape",
        "order_by": "relevant",
    }
    headers = {"Authorization": f"Client-ID {access_key}"}
    resp = requests.get(UNSPLASH_API, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return None
    # Prefer regular size (1080px wide); fall back to full
    urls = results[0].get("urls", {})
    return urls.get("regular") or urls.get("full")


def download_image(url, dest_path):
    resp = requests.get(url, timeout=30, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def convert_to_bundle(md_path, access_key):
    slug = os.path.splitext(os.path.basename(md_path))[0]
    bundle_dir = os.path.join(POSTS_DIR, slug)
    index_path = os.path.join(bundle_dir, "index.md")
    feature_path = os.path.join(bundle_dir, "feature.jpg")

    # Skip if bundle already exists
    if os.path.isdir(bundle_dir):
        print(f"  [SKIP] {slug} — bundle already exists")
        return

    post = frontmatter.load(md_path)
    tags = post.get("tags", [])
    query = keywords_for_post(slug, tags)

    print(f"  [{slug}] querying Unsplash: '{query}'")
    photo_url = fetch_photo_url(query, access_key)
    if not photo_url:
        print(f"  [WARN] {slug} — no photo found for '{query}', skipping")
        return

    os.makedirs(bundle_dir)

    # Move post content into bundle
    shutil.move(md_path, index_path)

    # Download feature image
    print(f"  [{slug}] downloading image...")
    download_image(photo_url, feature_path)
    print(f"  [{slug}] done → {bundle_dir}/")


def main():
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        print("ERROR: Set UNSPLASH_ACCESS_KEY environment variable")
        print("  export UNSPLASH_ACCESS_KEY=your_access_key_here")
        sys.exit(1)

    posts_dir = os.path.abspath(POSTS_DIR)
    if not os.path.isdir(posts_dir):
        print(f"ERROR: posts directory not found: {posts_dir}")
        sys.exit(1)

    md_files = [
        f for f in os.listdir(posts_dir)
        if f.endswith(".md") and not f.startswith("_")
    ]

    if not md_files:
        print("No flat .md posts found — all posts may already be bundles.")
        sys.exit(0)

    print(f"Found {len(md_files)} posts to process:\n")
    for md_file in sorted(md_files):
        convert_to_bundle(os.path.join(posts_dir, md_file), access_key)

    print("\nDone.")


if __name__ == "__main__":
    main()
```

---

### Task 3: Run the script

**Files:**
- Modifies: `content/posts/` (converts flat `.md` files to page bundles)

- [ ] **Step 1: Set your Unsplash Access Key**

```bash
export UNSPLASH_ACCESS_KEY=your_access_key_here
```

Replace `your_access_key_here` with the Access Key from your Unsplash developer app.

- [ ] **Step 2: Run the script (dry preview first)**

```bash
cd /Users/i861347/IdeaProjects/hugo-blog
python3 scripts/add_feature_images.py
```

Expected output (one line per post):
```
Found 13 posts to process:

  [athena-query-optimization] querying Unsplash: 'sql database query'
  [athena-query-optimization] downloading image...
  [athena-query-optimization] done → content/posts/athena-query-optimization/
  ...
Done.
```

- [ ] **Step 3: Verify the output structure**

```bash
ls content/posts/athena-query-optimization/
```

Expected:
```
feature.jpg  index.md
```

```bash
ls content/posts/ | head -5
```

Expected: only directories, no `.md` files remaining.

---

### Task 4: Test locally with Hugo

**Files:**
- No files changed

- [ ] **Step 1: Start Hugo dev server**

```bash
cd /Users/i861347/IdeaProjects/hugo-blog
hugo server -D
```

(`-D` includes draft posts so you can see images on all posts)

- [ ] **Step 2: Open the posts list**

Open `http://localhost:1313/posts/` in your browser.

Verify: each post card shows a feature image thumbnail.

- [ ] **Step 3: Open an individual post**

Click any post. Verify: the feature image appears at the top of the article.

- [ ] **Step 4: Stop the server**

```
Ctrl+C
```

---

### Task 5: Commit

**Files:**
- `scripts/add_feature_images.py`
- `content/posts/` (all converted bundles)

- [ ] **Step 1: Stage and commit**

```bash
cd /Users/i861347/IdeaProjects/hugo-blog
git add scripts/add_feature_images.py content/posts/
git commit -m "feat: add Unsplash feature images to all posts via page bundles"
```

Expected:
```
[main xxxxxxx] feat: add Unsplash feature images to all posts via page bundles
 27 files changed, ...
```

---

## Notes

**If a post gets a bad image:** Re-run the script after deleting that post's bundle directory. Or edit `KEYWORD_OVERRIDES` in the script with a better search term, delete the bundle dir, and re-run.

**Adding new posts in future:** Write new posts as page bundles from the start (`content/posts/new-post/index.md` + `feature.jpg`). The script only processes flat `.md` files and will skip existing bundles.

**Unsplash rate limit:** Free accounts allow 50 requests/hour. 13 posts = 13 requests, well within limit.

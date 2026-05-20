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
    "athena-query-optimization":        "sql database query",
    "building-mcp-toolserver-claude":   "artificial intelligence tools",
    "claude-agent-view-explained":      "ai automation productivity",
    "dynamodb-101":                     "database architecture",
    "git-worktrees":                    "git developer workflow",
    "intellij-idea-tour":               "java programming ide",
    "parallel-integration-tests":       "software testing ci",
    "portfolio-site-tech-stack":        "java spring web",
    "portfolio-v2-static-site":         "static website html",
    "redis-bandwidth-hidden-constraint": "redis server performance",
    "spring-boot-4-jackson-3-migration": "java spring boot",
    "synology-nas-blog-setup":          "nas homelab server",
    "whole-house-audio-lyrion":         "audio music home",
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

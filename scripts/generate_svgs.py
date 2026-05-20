#!/usr/bin/env python3
"""
Generates SVG feature images for Hugo posts and converts flat .md files to page bundles.
Each SVG has a dark background, category accent color, topic-specific icon, and post title.
"""

import os
import shutil
import frontmatter

POSTS_DIR = os.path.join(os.path.dirname(__file__), "..", "content", "posts")

# Category accent colors
COLORS = {
    "aws":      "#F59E0B",   # orange-amber  — AWS/Cloud
    "homelab":  "#FB923C",   # orange        — Homelab/Self-hosting
    "java":     "#4ADE80",   # green         — Java/Spring Boot
    "ai":       "#A78BFA",   # purple        — AI/Developer Tools
    "git":      "#A78BFA",   # purple        — Git tools
}

# Per-post config: (category_key, icon_path_d, icon_label)
# Icons are simple SVG path shapes drawn on a 64x64 viewBox centered at (32,32)
POSTS = {
    # ── AWS / Cloud ──────────────────────────────────────────────────────────
    "athena-query-optimization": (
        "aws",
        # Database cylinder + lightning bolt
        "M12,14 Q32,8 52,14 L52,50 Q32,56 12,50 Z M12,14 Q32,20 52,14 M12,26 Q32,32 52,26 M12,38 Q32,44 52,38"
        " M38,20 L34,32 L40,32 L28,48 L32,36 L26,36 Z",
        "SQL",
    ),
    "dynamodb-101": (
        "aws",
        # Three stacked disks
        "M8,20 Q32,12 56,20 L56,28 Q32,36 8,28 Z"
        " M8,28 L8,36 Q32,44 56,36 L56,28"
        " M8,36 L8,44 Q32,52 56,44 L56,36",
        "DynamoDB",
    ),
    "aws-cloudformation-infrastructure-as-code": (
        "aws",
        # Stack of boxes (IaC layers)
        "M32,6 L54,18 L54,42 L32,54 L10,42 L10,18 Z"
        " M10,18 L32,30 L54,18 M32,30 L32,54"
        " M20,12 L42,24 M44,12 L22,24",
        "CloudFormation",
    ),
    "redis-bandwidth-hidden-constraint": (
        "aws",
        # Network bandwidth bars + warning
        "M8,44 L8,32 L16,32 L16,44 Z M20,44 L20,24 L28,24 L28,44 Z M32,44 L32,16 L40,16 L40,44 Z M44,44 L44,28 L52,28 L52,44 Z"
        " M32,8 L36,18 L28,18 Z M32,13 L32,16 M32,17 L32,18",
        "Redis BW",
    ),
    "sqs-long-polling-graceful-shutdown-visibility-timeout-dlq": (
        "aws",
        # Queue arrows
        "M8,24 L24,24 M24,20 L32,24 L24,28 Z"
        " M8,32 L24,32 M24,28 L32,32 L24,36 Z"
        " M8,40 L24,40 M24,36 L32,40 L24,44 Z"
        " M36,24 L52,24 M44,20 L52,24 L44,28 Z"
        " M36,40 L52,40 M44,36 L52,40 L44,44 Z",
        "SQS",
    ),

    # ── Homelab / Self-hosting ────────────────────────────────────────────────
    "synology-nas-blog-setup": (
        "homelab",
        # NAS box with drives
        "M8,16 L56,16 L56,48 L8,48 Z"
        " M12,22 L28,22 L28,30 L12,30 Z M12,34 L28,34 L28,42 L12,42 Z"
        " M36,26 A4,4 0 1,1 36,25.9 M48,26 A4,4 0 1,1 48,25.9"
        " M36,38 A4,4 0 1,1 36,37.9 M48,38 A4,4 0 1,1 48,37.9",
        "NAS",
    ),
    "whole-house-audio-lyrion": (
        "homelab",
        # Speaker + sound waves
        "M14,22 L22,22 L30,14 L30,50 L22,42 L14,42 Z"
        " M34,24 Q42,32 34,40 M38,20 Q50,32 38,44 M42,16 Q58,32 42,48",
        "Audio",
    ),
    "portfolio-site-tech-stack": (
        "homelab",
        # Monitor + Docker whale simplified
        "M8,12 L56,12 L56,40 L8,40 Z M20,40 L20,48 L44,48 L44,40"
        " M14,44 L50,44"
        " M24,28 Q32,20 40,28 Q44,32 40,36 Q32,44 24,36 Q20,32 24,28 Z",
        "Portfolio",
    ),
    "portfolio-v2-static-site": (
        "homelab",
        # Browser window + </> tag
        "M6,12 L58,12 L58,52 L6,52 Z M6,20 L58,20 M12,16 A2,2 0 1,1 12,15.9 M18,16 A2,2 0 1,1 18,15.9 M24,16 A2,2 0 1,1 24,15.9"
        " M18,34 L24,28 L18,22 M46,34 L40,28 L46,22 M26,36 L38,20",
        "Static Site",
    ),

    # ── AI / Developer Tools ──────────────────────────────────────────────────
    "building-mcp-toolserver-claude": (
        "ai",
        # Circuit board / MCP nodes
        "M16,16 A6,6 0 1,1 16,15.9 M48,16 A6,6 0 1,1 48,15.9 M16,48 A6,6 0 1,1 16,47.9 M48,48 A6,6 0 1,1 48,47.9 M32,32 A6,6 0 1,1 32,31.9"
        " M16,22 L16,42 M48,22 L48,42 M22,16 L42,16 M22,48 L42,48"
        " M20,28 L26,32 M38,32 L44,28 M20,36 L26,32 M38,32 L44,36",
        "MCP",
    ),
    "claude-agent-view-explained": (
        "ai",
        # Multiple agent bubbles
        "M20,20 A10,10 0 1,1 20,19.9 M44,20 A10,10 0 1,1 44,19.9 M32,42 A10,10 0 1,1 32,41.9"
        " M26,26 L28,34 M38,26 L36,34"
        " M17,16 L14,10 M47,16 L50,10",
        "Agents",
    ),
    "intellij-idea-tour": (
        "ai",
        # IDE window with code lines
        "M8,8 L56,8 L56,56 L8,56 Z M8,18 L56,18 M14,14 A2,2 0 1,1 14,13.9 M20,14 A2,2 0 1,1 20,13.9 M26,14 A2,2 0 1,1 26,13.9"
        " M16,26 L36,26 M16,32 L44,32 M16,38 L30,38 M16,44 L40,44",
        "IntelliJ",
    ),
    "git-worktrees": (
        "git",
        # Git branch tree
        "M32,8 L32,24 M32,24 L18,40 M32,24 L46,40"
        " M32,6 A4,4 0 1,1 32,5.9 M18,42 A4,4 0 1,1 18,41.9 M46,42 A4,4 0 1,1 46,41.9"
        " M18,48 L18,54 M46,48 L46,54 M18,56 A4,4 0 1,1 18,55.9 M46,56 A4,4 0 1,1 46,55.9",
        "Worktrees",
    ),
    "useful-git-tips-tricks-workflow": (
        "git",
        # Git commit graph
        "M12,16 A4,4 0 1,1 12,15.9 M12,32 A4,4 0 1,1 12,31.9 M12,48 A4,4 0 1,1 12,47.9"
        " M12,20 L12,28 M12,36 L12,44"
        " M32,24 A4,4 0 1,1 32,23.9 M32,40 A4,4 0 1,1 32,39.9"
        " M16,18 L28,24 M16,46 L28,40"
        " M36,26 L52,26 M36,42 L52,42"
        " M52,16 A4,4 0 1,1 52,15.9 M52,32 A4,4 0 1,1 52,31.9 M52,48 A4,4 0 1,1 52,47.9"
        " M52,20 L52,28 M52,36 L52,44",
        "Git Tips",
    ),

    # ── Java / Spring Boot ────────────────────────────────────────────────────
    "spring-boot-4-jackson-3-migration": (
        "java",
        # JSON curly braces + arrow
        "M24,12 L18,12 Q12,12 12,18 L12,28 Q12,32 8,32 Q12,32 12,36 L12,46 Q12,52 18,52 L24,52"
        " M40,12 L46,12 Q52,12 52,18 L52,28 Q52,32 56,32 Q52,32 52,36 L52,46 Q52,52 46,52 L40,52"
        " M26,32 L38,32 M34,28 L38,32 L34,36",
        "Jackson",
    ),
    "parallel-integration-tests": (
        "java",
        # Parallel test tracks
        "M8,16 L56,16 M8,32 L56,32 M8,48 L56,48"
        " M14,12 L14,36 M14,36 L20,36 A4,4 0 1,1 20,35.9"
        " M28,12 L28,52 M28,52 L34,52 A4,4 0 1,1 34,51.9"
        " M42,12 L42,28 M42,28 L48,28 A4,4 0 1,1 48,27.9",
        "Tests",
    ),
    "audit-trails-mongodb-javers": (
        "java",
        # Audit log lines + checkmark
        "M8,14 L56,14 L56,54 L8,54 Z"
        " M14,22 L50,22 M14,30 L50,30 M14,38 L38,38 M14,46 L32,46"
        " M38,40 L42,46 L52,34",
        "Audit",
    ),
    "code-quality-enforcement-pmd-spotbugs-checkstyle-jacoco": (
        "java",
        # Shield + checkmark
        "M32,6 L52,14 L52,34 Q52,50 32,58 Q12,50 12,34 L12,14 Z"
        " M22,32 L28,38 L42,24",
        "Quality",
    ),
    "component-tests-spring-boot-testcontainers-mock-http": (
        "java",
        # Container box + test beaker
        "M8,20 L56,20 L56,52 L8,52 Z M8,28 L56,28"
        " M18,36 L18,48 M26,32 L26,48 M34,36 L34,48 M42,32 L42,48"
        " M44,10 L50,20 M40,8 L46,18",
        "Testing",
    ),
    "configure-h2-database-spring-boot": (
        "java",
        # Database + H2 letter hint (two pillars + bridge)
        "M12,16 Q32,10 52,16 L52,20 Q32,26 12,20 Z"
        " M12,20 L12,48 M52,20 L52,48"
        " M12,48 Q32,54 52,48 L52,52 Q32,58 12,52 Z"
        " M20,30 L20,38 M30,30 L30,38 M20,34 L30,34"
        " M38,30 L38,38 M44,30 L44,38",
        "H2 DB",
    ),
    "consuming-rest-service-javascript": (
        "java",
        # REST arrows between client and server
        "M6,20 L22,20 L22,44 L6,44 Z M42,20 L58,20 L58,44 L42,44 Z"
        " M22,28 L42,28 M38,24 L42,28 L38,32"
        " M42,36 L22,36 M26,32 L22,36 L26,40",
        "REST JS",
    ),
    "context-propagation-executor-service-threads": (
        "java",
        # Thread lines with context passing
        "M8,16 L20,16 M8,32 L20,32 M8,48 L20,48"
        " M20,16 L32,24 M20,32 L32,32 M20,48 L32,40"
        " M32,24 L44,16 M32,32 L44,32 M32,40 L44,48"
        " M44,16 L56,16 M44,32 L56,32 M44,48 L56,48"
        " M20,14 A3,3 0 1,1 20,13.9 M20,30 A3,3 0 1,1 20,29.9 M20,46 A3,3 0 1,1 20,45.9"
        " M44,14 A3,3 0 1,1 44,13.9 M44,30 A3,3 0 1,1 44,29.9 M44,46 A3,3 0 1,1 44,45.9",
        "Threads",
    ),
    "custom-jackson-deserializers-date-formats": (
        "java",
        # JSON brackets + calendar
        "M16,10 L10,10 Q6,10 6,14 L6,22 Q6,26 2,26 Q6,26 6,30 L6,38 Q6,42 10,42 L16,42"
        " M48,10 L54,10 Q58,10 58,14 L58,22 Q58,26 62,26 Q58,26 58,30 L58,38 Q58,42 54,42 L48,42"
        " M24,16 L40,16 L40,46 L24,46 Z M24,22 L40,22 M28,18 L28,14 M36,18 L36,14"
        " M28,28 L32,28 M28,34 L36,34 M28,40 L34,40",
        "Jackson",
    ),
    "graceful-shutdown-kubernetes-readiness-spring-boot": (
        "java",
        # Kubernetes helm wheel
        "M32,10 A22,22 0 1,1 31.9,10"
        " M32,10 L32,20 M32,44 L32,54 M10,32 L20,32 M44,32 L54,32"
        " M17,17 L24,24 M40,40 L47,47 M47,17 L40,24 M24,40 L17,47"
        " M32,32 A6,6 0 1,1 31.9,32",
        "K8s",
    ),
    "gradle-plugin-package-deploy-release": (
        "java",
        # Elephant head (Gradle mascot simplified) → use build/package box instead
        "M16,8 L48,8 L48,32 L40,32 L40,40 L32,40 L32,56 L16,56 Z"
        " M48,8 L56,16 L56,40 L48,40 L48,32"
        " M32,40 L40,40 M32,56 L40,56 L40,40"
        " M22,18 L42,18 M22,26 L36,26",
        "Gradle",
    ),
    "in-process-caching-guava-cachebuilder": (
        "java",
        # Lightning bolt in a box (cache = fast)
        "M10,10 L54,10 L54,54 L10,54 Z"
        " M36,14 L28,34 L34,34 L28,50 L44,28 L36,28 Z",
        "Cache",
    ),
    "mongodb-schema-migrations-mongock": (
        "java",
        # MongoDB leaf + migration arrow
        "M20,48 Q12,32 20,16 Q32,8 44,16 Q56,24 44,40 Q36,50 32,52 Q28,50 20,48 Z"
        " M28,36 L28,28 M32,28 L28,24 L24,28"
        " M40,24 L40,16 M44,16 L40,12 L36,16",
        "MongoDB",
    ),
    "redis-distributed-locking-redisson-fair-locks": (
        "java",
        # Lock + distributed nodes
        "M24,28 L40,28 L40,46 L24,46 Z M28,28 L28,22 Q28,14 32,14 Q36,14 36,22 L36,28"
        " M32,35 A3,3 0 1,1 31.9,35 M32,38 L32,42"
        " M10,18 A5,5 0 1,1 9.9,18 M54,18 A5,5 0 1,1 53.9,18"
        " M14,22 L24,28 M50,22 L40,28",
        "Redis Lock",
    ),
    "resilience4j-context-propagators-spring-boot3": (
        "java",
        # Circuit breaker switch
        "M8,32 L20,32 M44,32 L56,32"
        " M20,32 Q24,20 32,20 Q40,20 44,32"
        " M28,32 A4,4 0 1,1 27.9,32 M36,32 A4,4 0 1,1 35.9,32"
        " M20,36 L20,44 L44,44 L44,36"
        " M12,28 L12,36 M52,28 L52,36",
        "Circuit",
    ),
    "structured-logging-logstash-logback-mdc": (
        "java",
        # Log lines with ELK stack dots
        "M8,16 L56,16 M8,24 L48,24 M8,32 L52,32 M8,40 L44,40 M8,48 L50,48"
        " M18,10 A4,4 0 1,1 17.9,10 M32,10 A4,4 0 1,1 31.9,10 M46,10 A4,4 0 1,1 45.9,10",
        "Logging",
    ),
    "transactional-event-listener-after-commit": (
        "java",
        # Database + event emission arrows
        "M16,16 Q32,10 48,16 L48,22 Q32,28 16,22 Z M16,22 L16,42 M48,22 L48,42 M16,42 Q32,48 48,42"
        " M48,28 L54,24 M54,24 L58,20 M48,32 L56,32 M48,36 L54,40 M54,40 L58,44",
        "Events",
    ),
}


def hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def make_svg(title, color_hex, icon_path, short_label):
    r, g, b = hex_to_rgb(color_hex)
    # Dim version of accent for background glow
    glow = f"rgba({r},{g},{b},0.15)"

    # Truncate long titles for display
    if len(title) > 42:
        words = title.split()
        line1, line2 = [], []
        for w in words:
            if len(" ".join(line1 + [w])) <= 42:
                line1.append(w)
            else:
                line2.append(w)
        title_svg = (
            f'<text x="50%" y="80%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="ui-monospace,SFMono-Regular,monospace" font-size="13" fill="white" opacity="0.9">'
            f'{" ".join(line1)}</text>\n    '
            f'<text x="50%" y="88%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="ui-monospace,SFMono-Regular,monospace" font-size="13" fill="white" opacity="0.9">'
            f'{" ".join(line2)}</text>'
        )
    else:
        title_svg = (
            f'<text x="50%" y="84%" dominant-baseline="middle" text-anchor="middle" '
            f'font-family="ui-monospace,SFMono-Regular,monospace" font-size="13" fill="white" opacity="0.9">'
            f'{title}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 418" width="800" height="418">
  <defs>
    <radialGradient id="bg" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="{glow}"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </radialGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="800" height="418" fill="#0f172a"/>
  <rect width="800" height="418" fill="url(#bg)"/>

  <!-- Subtle grid -->
  <g stroke="{color_hex}" stroke-width="0.3" opacity="0.08">
    <line x1="0" y1="40" x2="800" y2="40"/>
    <line x1="0" y1="80" x2="800" y2="80"/>
    <line x1="0" y1="120" x2="800" y2="120"/>
    <line x1="0" y1="160" x2="800" y2="160"/>
    <line x1="0" y1="200" x2="800" y2="200"/>
    <line x1="0" y1="240" x2="800" y2="240"/>
    <line x1="0" y1="280" x2="800" y2="280"/>
    <line x1="0" y1="320" x2="800" y2="320"/>
    <line x1="0" y1="360" x2="800" y2="360"/>
    <line x1="0" y1="400" x2="800" y2="400"/>
    <line x1="80" y1="0" x2="80" y2="418"/>
    <line x1="160" y1="0" x2="160" y2="418"/>
    <line x1="240" y1="0" x2="240" y2="418"/>
    <line x1="320" y1="0" x2="320" y2="418"/>
    <line x1="400" y1="0" x2="400" y2="418"/>
    <line x1="480" y1="0" x2="480" y2="418"/>
    <line x1="560" y1="0" x2="560" y2="418"/>
    <line x1="640" y1="0" x2="640" y2="418"/>
    <line x1="720" y1="0" x2="720" y2="418"/>
    <line x1="800" y1="0" x2="800" y2="418"/>
  </g>

  <!-- Accent line top -->
  <rect x="0" y="0" width="800" height="3" fill="{color_hex}" opacity="0.8"/>

  <!-- Icon: scale 64x64 paths to ~200px, centered at (400, 185) -->
  <g transform="translate(400,185) scale(3.1) translate(-32,-32)" filter="url(#glow)">
    <g stroke="{color_hex}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round">
      <path d="{icon_path}"/>
    </g>
  </g>

  <!-- Title -->
  {title_svg}

  <!-- Bottom accent line -->
  <rect x="0" y="415" width="800" height="3" fill="{color_hex}" opacity="0.4"/>
</svg>"""


def convert_to_bundle(md_path, svg_content):
    slug = os.path.splitext(os.path.basename(md_path))[0]
    bundle_dir = os.path.join(POSTS_DIR, slug)
    index_path = os.path.join(bundle_dir, "index.md")
    feature_path = os.path.join(bundle_dir, "feature.svg")

    if os.path.isdir(bundle_dir):
        # Bundle exists — just write/overwrite the SVG
        with open(feature_path, "w") as f:
            f.write(svg_content)
        print(f"  [UPDATE] {slug} — SVG updated")
        return

    os.makedirs(bundle_dir)
    shutil.move(md_path, index_path)
    with open(feature_path, "w") as f:
        f.write(svg_content)
    print(f"  [CREATE] {slug} → bundle + feature.svg")


def main():
    posts_dir = os.path.abspath(POSTS_DIR)

    # Read all post titles
    import frontmatter as fm
    titles = {}
    for filename in os.listdir(posts_dir):
        if filename.endswith(".md") and not filename.startswith("_"):
            slug = filename[:-3]
            path = os.path.join(posts_dir, filename)
            post = fm.load(path)
            titles[slug] = post.get("title", slug.replace("-", " ").title())

    # Also check existing bundles for titles
    for entry in os.listdir(posts_dir):
        bundle_path = os.path.join(posts_dir, entry)
        index_path = os.path.join(bundle_path, "index.md")
        if os.path.isdir(bundle_path) and os.path.exists(index_path):
            slug = entry
            post = fm.load(index_path)
            titles[slug] = post.get("title", slug.replace("-", " ").title())

    print(f"Processing {len(POSTS)} posts...\n")

    for slug, (category, icon_path, label) in POSTS.items():
        color = COLORS[category]
        title = titles.get(slug, slug.replace("-", " ").title())

        svg = make_svg(title, color, icon_path, label)

        # Find the source: flat .md or existing bundle
        flat_md = os.path.join(posts_dir, f"{slug}.md")
        bundle_dir = os.path.join(posts_dir, slug)

        if os.path.exists(flat_md):
            convert_to_bundle(flat_md, svg)
        elif os.path.isdir(bundle_dir):
            feature_path = os.path.join(bundle_dir, "feature.svg")
            with open(feature_path, "w") as f:
                f.write(svg)
            print(f"  [UPDATE] {slug} — SVG written to existing bundle")
        else:
            print(f"  [WARN] {slug} — no .md file or bundle found, skipping")

    print("\nDone.")


if __name__ == "__main__":
    main()

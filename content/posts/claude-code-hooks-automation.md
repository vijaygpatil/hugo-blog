---
title: "Claude Code Hooks: Automate Your AI Workflow Like a Senior Engineer"
date: 2026-05-25
tags: ["claude", "ai", "automation", "developer-tools", "productivity", "homelab"]
description: "A practical guide to Claude Code hooks — what they are, how to configure them, and real automation patterns that make your AI-assisted workflow faster, safer, and smarter."
showToc: true
---

Every senior engineer I know has a set of habits they run on autopilot. Before committing code, they run the formatter. After modifying a service, they run the related tests. When something breaks, they check the logs immediately. These aren't conscious decisions — they're reflexes built from years of painful lessons.

Claude Code hooks let you wire those same reflexes into your AI workflow. Instead of remembering to do things after Claude writes code, hooks do them automatically — before the tool runs, after it completes, when the session starts, or when Claude tries to stop before the job is actually done.

This post is a complete guide: what hooks are, how they work, and the real automation patterns that will change how you work with Claude Code every day.

---

## What Are Hooks?

Hooks are shell commands or prompts that Claude Code executes automatically in response to events. Think of them as lifecycle callbacks — the same concept you've used in frameworks like Spring, React, or Git.

```
User asks Claude to do something
        ↓
  [PreToolUse hook fires] ← validate, block, or modify before it runs
        ↓
  Claude runs the tool
        ↓
  [PostToolUse hook fires] ← react, format, test, log after it completes
        ↓
  Claude prepares to stop
        ↓
  [Stop hook fires] ← verify it actually finished everything
```

Without hooks, Claude Code is a smart assistant that waits for your instructions. With hooks, it becomes an automated workflow system that enforces your standards, runs your checks, and keeps you informed — without you having to ask.

---

## Hook Events: The Full Picture

Claude Code exposes hooks at every meaningful point in its lifecycle:

| Event | When It Fires | What You Can Do |
|---|---|---|
| **SessionStart** | When a session begins | Load project context, set env vars, print status |
| **PreToolUse** | Before any tool runs | Validate, block, or modify the tool call |
| **PostToolUse** | After a tool completes | Run tests, format code, log results |
| **Stop** | When Claude tries to stop | Verify completion, force more work |
| **SubagentStop** | When a subagent finishes | Validate subagent output |
| **UserPromptSubmit** | When you hit Enter | Add context to your prompt automatically |
| **Notification** | When Claude sends a notification | Desktop alerts, Slack pings |
| **PreCompact** | Before context compaction | Preserve critical state |

The two you'll use most are **PreToolUse** and **PostToolUse** — they're the hooks that sit directly around the work Claude actually does.

---

## How Hooks Are Configured

Hooks live in `.claude/settings.json` — either at the global level (`~/.claude/settings.json`) or inside a specific project (`.claude/settings.json` in the project root). Project-level hooks only apply when you're working in that project. Global hooks apply everywhere.

The structure is straightforward:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "prettier --write \"$FILE_PATH\""
          }
        ]
      }
    ]
  }
}
```

Three things to understand here:

**matcher** — which tools trigger this hook. You can match a single tool (`"Write"`), multiple tools (`"Write|Edit"`), all tools (`"*"`), or a regex pattern (`"mcp__.*"` for all MCP tools).

**type** — either `"command"` (run a shell command) or `"prompt"` (ask Claude to evaluate something using AI reasoning).

**command** — the shell command to run. It receives a JSON payload via stdin with everything about the tool call.

---

## Two Kinds of Hooks: Command vs. Prompt

### Command Hooks — Fast and Deterministic

Command hooks run a shell script. They're fast, predictable, and good for things where the answer is clear: run the formatter, execute the tests, check if this file path is safe.

```json
{
  "type": "command",
  "command": "npm test -- --testPathPattern=\"$FILE_PATH\"",
  "timeout": 60
}
```

The hook receives a JSON payload on stdin:

```json
{
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/src/services/UserService.java",
    "content": "..."
  },
  "session_id": "abc123",
  "cwd": "/Users/you/my-project"
}
```

Your script reads this, makes a decision, and exits:
- Exit `0` → everything fine, proceed
- Exit `2` → block this tool call, feed the error message back to Claude

### Prompt Hooks — Smart and Context-Aware

Prompt hooks ask Claude itself to evaluate something. They're good for judgment calls where the answer isn't always the same:

```json
{
  "type": "prompt",
  "prompt": "This tool is about to write to: $TOOL_INPUT. Does this look like it could overwrite a sensitive file (.env, credentials, secrets)? If yes, block it with a clear reason.",
  "timeout": 30
}
```

Use command hooks for speed and certainty. Use prompt hooks for nuance and edge cases.

---

## Real Automation Patterns

Here's where it gets practical. These are patterns that actually change how you work.

### Pattern 1: Auto-Format Code on Every Write

The most common hook. Every time Claude writes or edits a file, automatically run your formatter. No more "I forgot to run Prettier" in code review.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "prettier --write \"$(echo $TOOL_INPUT | jq -r '.file_path')\""
          }
        ]
      }
    ]
  }
}
```

For Java projects using Google Java Format:

```json
{
  "type": "command",
  "command": "google-java-format --replace \"$(echo $TOOL_INPUT | jq -r '.file_path')\""
}
```

### Pattern 2: Run Tests Automatically After Code Changes

Every time Claude modifies a source file, run the tests for that module. You get instant feedback — no switching to a terminal, no remembering to run tests before moving on.

```bash
#!/bin/bash
# post-write-test.sh
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path')

# Only run tests if a source file changed (not config/docs)
if [[ "$FILE" == *"/src/"* && "$FILE" == *".java" ]]; then
  MODULE=$(echo "$FILE" | grep -oP '(?<=/)[^/]+(?=/src)')
  cd "$CLAUDE_PROJECT_DIR"
  ./gradlew ":${MODULE}:test" --tests "*" 2>&1
fi
```

```json
{
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "bash .claude/hooks/post-write-test.sh"
        }
      ]
    }
  ]
}
```

### Pattern 3: Block Writes to Sensitive Files

Never let Claude accidentally overwrite your `.env`, credentials, or secrets files. This hook stops it before it happens — not after.

```bash
#!/bin/bash
# protect-sensitive-files.sh
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path')

SENSITIVE_PATTERNS=(".env" ".env.local" "credentials" "secrets" "id_rsa" "*.pem" "*.key")

for pattern in "${SENSITIVE_PATTERNS[@]}"; do
  if [[ "$FILE" == *"$pattern"* ]]; then
    echo "{\"decision\": \"deny\", \"reason\": \"Blocked: $FILE matches sensitive file pattern '$pattern'. Edit manually if intentional.\"}" >&2
    exit 2
  fi
done

exit 0
```

```json
{
  "PreToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "bash .claude/hooks/protect-sensitive-files.sh",
          "timeout": 5
        }
      ]
    }
  ]
}
```

### Pattern 4: Load Project Context at Session Start

When you open a new session, automatically inject the current state of your project — what's in progress, what tests are failing, what the team is working on. Claude starts informed instead of needing to catch up.

```bash
#!/bin/bash
# session-start.sh

echo "=== Project Status ==="
echo "Branch: $(git branch --show-current)"
echo "Last commit: $(git log -1 --oneline)"
echo ""
echo "=== Unstaged Changes ==="
git status --short
echo ""
echo "=== Recent Test Results ==="
# Show last test run if cached
if [ -f ".claude/last-test-run.txt" ]; then
  tail -20 .claude/last-test-run.txt
fi
```

```json
{
  "SessionStart": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "bash .claude/hooks/session-start.sh"
        }
      ]
    }
  ]
}
```

### Pattern 5: Verify Claude Actually Finished Before Stopping

This one is underrated. Claude sometimes decides it's done when there are still failing tests or unresolved TODOs. A Stop hook forces a verification check before the session ends.

```json
{
  "Stop": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "prompt",
          "prompt": "Before stopping: verify that (1) no tests are failing, (2) no TODO/FIXME comments were left in files you modified, and (3) the original request is fully addressed. If anything is incomplete, continue working instead of stopping.",
          "timeout": 30
        }
      ]
    }
  ]
}
```

This is a prompt hook — it uses Claude's own reasoning to evaluate whether the work is truly done. If it's not, Claude keeps going.

### Pattern 6: Desktop Notification When Claude Needs Your Attention

When you're in a long session and Claude needs permission for something, get a macOS notification instead of having to watch the terminal.

```json
{
  "Notification": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "osascript -e 'display notification \"Claude needs your attention\" with title \"Claude Code\" sound name \"Ping\"'"
        }
      ]
    }
  ]
}
```

### Pattern 7: Log Every Tool Call for Audit

If you want a record of everything Claude did in a session — useful for reviewing AI-assisted work before committing — log every tool call to a file.

```bash
#!/bin/bash
# audit-log.sh
INPUT=$(cat)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TOOL=$(echo "$INPUT" | jq -r '.tool_name')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // "N/A"')

echo "[$TIMESTAMP] $TOOL | $FILE" >> "$CLAUDE_PROJECT_DIR/.claude/audit.log"
exit 0
```

```json
{
  "PostToolUse": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "bash .claude/hooks/audit-log.sh",
          "async": true
        }
      ]
    }
  ]
}
```

Note `"async": true` — the logging runs in the background without blocking Claude's work.

---

## Hooks vs. MCP Tools vs. Skills: What's the Difference?

If you've used MCP tools or Claude Code skills, you might wonder where hooks fit. They solve different problems:

| | **Hooks** | **MCP Tools** | **Skills** |
|---|---|---|---|
| **What it is** | Lifecycle callbacks — run automatically on events | External tools Claude can call on demand | Reusable prompts/instructions Claude follows |
| **When it runs** | Automatically, without you asking | When Claude decides to use it, or you instruct it | When you invoke it with `/skill-name` |
| **Best for** | Enforcing standards, auto-formatting, notifications, protection | Giving Claude access to external systems (databases, APIs, search) | Encoding workflows, checklists, domain knowledge |
| **Example** | Auto-run tests after every file write | Query a log system or database | "Follow these steps when debugging a test failure" |

**The mental model:**

- **MCP tools** extend what Claude *can do* — they add capabilities
- **Skills** encode *how to do things* — they add knowledge and process
- **Hooks** automate *what happens around* Claude's work — they add guardrails and reflexes

In practice, they work best together. An MCP tool gives Claude access to your log system. A skill tells Claude how to investigate a failure pattern. A hook automatically triggers the log check after every test run.

---

## Hooks That Would Change How You Work Day-to-Day

Here are concrete hooks tuned for the kind of backend service engineering work most engineers do:

**On every file write:**
- Run the linter/formatter for that file type
- Run unit tests for the module being modified
- Check if the change introduces any obvious security issues (prompt hook)

**On session start:**
- Print git status, current branch, and recent commits
- Show any currently failing tests
- Remind Claude of any in-progress work from a notes file

**On stop:**
- Verify no TODO comments were left in modified files
- Confirm tests are passing
- Check that the original ask was fully addressed

**On any Bash tool call:**
- Block `rm -rf` without explicit confirmation
- Block force-push commands
- Log destructive operations to an audit file

**On notification:**
- macOS desktop notification so you can step away and come back

---

## Getting Started: Your First Hook in 5 Minutes

1. Create a `.claude` directory in your project if it doesn't exist
2. Create `.claude/settings.json`
3. Add a simple PostToolUse hook — start with the notification one, it's zero-risk:

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "osascript -e 'display notification \"Claude needs your input\" with title \"Claude Code\"'"
          }
        ]
      }
    ]
  }
}
```

4. Restart Claude Code — hooks load at session start
5. Run `/hooks` in Claude Code to verify your hooks are loaded

Once that works, add a formatter hook, then a test hook. Build up gradually — don't try to automate everything at once.

---

## A Few Things to Know

**Hooks run in parallel.** If you have multiple hooks on the same event, they all fire at the same time. Design them to be independent.

**Hooks load at session start.** If you edit your hooks configuration, restart the session for changes to take effect.

**Exit code 2 blocks and feeds back.** If your command hook exits with code `2`, Claude gets the stderr message as feedback and can react to it — useful for things like "this file is protected, here's why."

**Keep hooks fast.** PreToolUse hooks add latency to every tool call. If a hook takes 10 seconds, every Write or Edit will pause for 10 seconds. Use `async: true` for anything that doesn't need to block.

**Test hooks with simple echo commands first.** Before wiring up a real test runner, test that the hook fires correctly with `echo "hook fired" >> /tmp/hook-test.log`.

---

## Summary

Claude Code hooks turn AI-assisted coding from a conversation into an automated workflow. They're the difference between Claude being a smart tool you use and a capable system that enforces your engineering standards automatically.

Start with one hook — a formatter, a notification, or a simple Stop verification. Once you feel how they work, you'll find yourself adding more. The engineers who get the most from Claude Code aren't the ones who ask it the best questions. They're the ones who've wired up the reflexes so the right things happen automatically.

The hooks are there. Use them.

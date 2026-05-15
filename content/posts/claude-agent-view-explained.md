---
title: "Claude Agent View: Run Many AI Sessions at Once Without Losing Your Mind"
date: 2026-05-14
tags: ["ai", "claude", "developer-tools", "productivity", "automation"]
description: "A plain-English breakdown of Claude Code's Agent View feature — what it does, why it matters, and how to use it to delegate multiple tasks to AI in parallel."
---

You know that feeling when you have five things that need doing and you can only do one at a time? Agent View is Claude's answer to that problem — except Claude can actually work on all five simultaneously while you go do something else.

Here's everything you need to know, without the documentation.

## The Problem It Solves

When you use Claude normally, it's a one-conversation-at-a-time tool. You ask, it answers, you ask again. If you want it to investigate a bug *and* review some code *and* run your test suite, you're doing those one after the other — and you're babysitting each one.

Agent View changes that. It's a dashboard for running multiple Claude sessions in parallel, watching them from one screen, and only stepping in when one actually needs you.

Think of it like a manager's view: you assign work to a team, glance at the board occasionally, and only get involved when someone is stuck.

## Opening It

```bash
claude agents
```

That's it. A full-screen terminal UI appears, with a table of sessions and an input at the bottom. Empty at first — until you start dispatching tasks.

## Dispatching Work

Type a task in the input at the bottom and press `Enter`. Claude starts a new background session for that task immediately.

```
Fix the null pointer exception in PaymentService
```

Type another and press `Enter` again. That's a second session running in parallel — not a follow-up to the first one. Each prompt you type creates its own independent Claude session.

You can have several running at once. Each one works autonomously, makes its own tool calls, edits files, runs commands — whatever it needs to do for its task.

## Reading the Dashboard

Each session shows as a row. The icon on the left tells you everything:

| What you see | What it means |
|---|---|
| Animated spinning icon | Claude is actively working |
| Yellow icon | Claude is stuck — it needs your input |
| Green icon | Task done successfully |
| Red icon | Something went wrong |
| Dimmed icon | Idle, waiting for you |

Sessions are grouped so the ones that need you are always at the top. You're not hunting through a list — if it's yellow, it needs attention. If it's green, it's done.

## Checking In Without Fully Diving In

Press `Space` on any row to open a **peek panel** — a summary of what the session is doing or what it's asking, without opening the full conversation. Most of the time this is enough. You can even reply from the peek panel and close it, never leaving the dashboard.

Press `Enter` or `→` to **attach** — the session takes over your terminal like a normal Claude conversation. When you're done, press `←` on an empty prompt to detach and return to the dashboard. The session keeps running in the background.

## Why This Changes How You Work

The real shift is psychological. Instead of waiting on Claude to finish before starting the next thing, you front-load a batch of tasks, go do human-only work, and return to collect results.

**Before Agent View:**
1. Ask Claude to investigate bug → wait → read result → ask it to fix → wait → done.
2. Then start the next task.

**With Agent View:**
1. Dispatch: investigate bug, review PR, update docs, run tests.
2. Go do a meeting, answer emails, get coffee.
3. Come back to four sessions: two green (done), one yellow (needs your decision on something), one still working.
4. Resolve the yellow one in 30 seconds. Done.

The compounding effect is real. Tasks that used to feel sequential become genuinely parallel.

## Sessions Keep Running Without You

This is the part that surprised me most. Background sessions are hosted by a **supervisor process** — separate from your terminal. You can close Agent View, close your shell entirely, start a new Claude session, and your background sessions keep going.

They stop only if your machine sleeps or shuts down. When you come back, sessions that were running show as failed — but run `claude respawn --all` and they restart from exactly where they left off, transcript intact.

## Each Session Gets Its Own Sandbox

When a session starts editing files, Claude automatically moves it into an isolated **git worktree** — a separate branch of your repo under `.claude/worktrees/`. This means two sessions can work on the same codebase at the same time without clobbering each other's changes.

When you're done with a session, delete it and its worktree is cleaned up. But merge or push its changes first — deleting removes the worktree including any uncommitted work.

## Sending an Existing Session to the Background

Already mid-conversation with Claude and want to start something else? Run `/bg` inside the session to push it into the background and open Agent View. You can even add a final instruction: `/bg run the full test suite and fix any failures`.

Or from the shell:

```bash
claude --bg "investigate the flaky checkout test"
```

Claude prints a short session ID and instructions for managing it:

```
backgrounded · 7c5dcf5d
  claude agents             list sessions
  claude attach 7c5dcf5d    open in this terminal
  claude logs 7c5dcf5d      show recent output
  claude stop 7c5dcf5d      stop this session
```

## The Keyboard Shortcuts Worth Memorising

You don't need them all. Just these:

| Key | What it does |
|---|---|
| `↑` / `↓` | Move between sessions |
| `Space` | Peek at a session (quick view + reply) |
| `Enter` | Attach to a session (full conversation) |
| `←` | Detach and return to the dashboard |
| `Ctrl+X` | Stop a session (press twice to delete) |
| `Ctrl+R` | Rename a session |
| `?` | Show all shortcuts |

## One Gotcha: Quota

Each background session uses your Claude subscription quota independently. Run ten sessions in parallel and you're burning through quota ten times as fast. For quick tasks this rarely matters, but for long-running sessions it's worth keeping in mind.

## The Mental Model

Agent View turns Claude from a tool you interact with into a team you manage. You set the direction, check in when needed, and let the sessions do the grind.

It's in research preview (you need Claude Code v2.1.139 or later — check with `claude --version`), but it's already the kind of feature that changes your daily workflow once you start using it. The first time you close your laptop knowing three tasks are in progress and wake up to find them done, you'll understand why.

Try it:

```bash
claude agents
```

Type a task. Walk away. Come back to results.

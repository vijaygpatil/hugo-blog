---
title: "Git Worktrees: Multiple Branches Checked Out Simultaneously"
date: 2023-07-18
tags: ["git", "developer-tools", "workflow", "terminal", "macos"]
description: "Git worktrees let you check out multiple branches at the same time in separate directories — the same repository, no stashing, no context switching. Here's the mental model and the commands you'll actually use."
---

You already know git well. Branches, stashing, rebasing — none of that is new. But there's one feature that most developers never touch and then, once they do, wonder how they lived without it: **git worktrees**.

The short version: worktrees let you have multiple branches checked out simultaneously, each in its own directory, all backed by the same `.git` folder. No cloning the repo twice. No stashing half-finished work because a hotfix just came in. No losing your place.

---

## The Problem Worktrees Solve

You're mid-feature on `feature/payments`. Your terminal looks like this:

```
(feature/payments) $ # three files open in your editor, half-refactored
```

A critical bug lands. You need to fix `main`, build, test, deploy. Your options without worktrees:

1. `git stash` — lose your IDE state, forget what you were doing, deal with stash conflicts later
2. Clone the repo again somewhere — now you have two copies of node_modules, two copies of your build cache, and you have to remember which terminal is which
3. Commit half-done work with a "WIP" message — pollutes history, easy to forget to clean up

With a worktree, you do this:

```bash
git worktree add ../myrepo-hotfix main
cd ../myrepo-hotfix
# fix the bug, commit, push
cd ../myrepo
# back exactly where you were, nothing disturbed
```

Your `feature/payments` branch is still checked out in the original directory. Your editor never knew anything happened.

---

## The Mental Model

Think of your normal repo as having two things:

- The **`.git` directory** — the database: all commits, all branches, all history
- The **working tree** — the files you actually edit

Normally these are coupled: one `.git`, one working tree, one branch checked out at a time.

A worktree decouples them. You still have one `.git` (one database), but you can have **multiple working trees** pointing at it, each checked out to a different branch.

```
myrepo/               ← main working tree (feature/payments checked out)
  .git/               ← the one true database
  src/
  ...

myrepo-hotfix/        ← linked worktree (main checked out)
  src/
  ...                 ← no .git here; just a .git file pointing back
```

The branches are fully isolated. Changes in one working tree don't affect the other. But they share history — a commit in one is immediately visible in the other.

One constraint worth knowing upfront: **you cannot check out the same branch in two worktrees at the same time**. Git enforces this. Each branch can only be active in one working tree.

---

## The Commands

### Create a worktree

```bash
# Check out an existing branch in a new directory
git worktree add ../myrepo-hotfix hotfix/critical-bug

# Create a new branch and check it out in a new directory
git worktree add -b feature/new-thing ../myrepo-new-thing main
```

The directory path is relative to your current location. I use `../reponame-branchname` as a convention — keeps things next to each other on the filesystem and the name tells you what's in it.

### List your worktrees

```bash
git worktree list
```

Output:

```
/Users/you/myrepo           abc1234 [feature/payments]
/Users/you/myrepo-hotfix    def5678 [hotfix/critical-bug]
```

This works from any worktree in the set — the main one or any linked one.

### Remove a worktree

```bash
# From within the main worktree (or any other worktree)
git worktree remove ../myrepo-hotfix
```

This removes the directory and cleans up the internal tracking. If the directory has uncommitted changes, git will refuse — add `--force` if you're sure.

After removing manually (e.g. you just deleted the folder with `rm -rf`):

```bash
git worktree prune
```

This cleans up stale worktree references whose directories no longer exist.

### Lock a worktree

If a worktree is on a network drive or external disk that might not always be mounted, you can lock it to prevent `prune` from cleaning it up:

```bash
git worktree lock ../myrepo-hotfix --reason "on external drive"
git worktree unlock ../myrepo-hotfix
```

You probably won't use this often, but it's there.

---

## A Realistic Workflow

Here's how this plays out in practice.

**Scenario: you're in the middle of a feature and a colleague asks for a review**

```bash
# You're on feature/payments, working
git worktree add ../myrepo-review feature/colleague-work
cd ../myrepo-review

# Review, leave comments, done
cd ../myrepo

# Clean up
git worktree remove ../myrepo-review
```

Total disruption to your feature work: zero.

**Scenario: running two long builds in parallel**

```bash
git worktree add ../myrepo-experiment experiment/new-algorithm
cd ../myrepo-experiment && ./gradlew build &   # running in background
cd ../myrepo && ./gradlew build                # running here
```

Two branches, two builds, same machine.

**Scenario: keeping a clean copy of main always available**

Some people keep a permanent worktree on `main` so they always have a known-good reference:

```bash
git worktree add ../myrepo-main main
```

Now `../myrepo-main` is always on main — update it with `git pull` when needed. Useful for running the test suite against main while you work elsewhere, or for quickly checking what a function looked like before your changes.

---

## What Gets Shared, What Doesn't

**Shared across all worktrees:**
- The full git history and all refs (branches, tags)
- The git config
- Staged changes and the index — wait, no. Each worktree has its own index. This is important: `git add` in one worktree does not affect the staging area in another.
- Stashes — stashes are stored in the shared `.git` and are visible from all worktrees

**Separate per worktree:**
- The working files (obviously)
- The staging area (index)
- `HEAD` — each worktree has its own HEAD pointing to its checked-out branch
- `MERGE_HEAD`, `CHERRY_PICK_HEAD` — mid-operation state is per-worktree

**Not automatically synced:**
- `node_modules`, build artifacts, caches — each worktree has its own, so your first build in a new worktree will take as long as the first build always does. This is a cost worth knowing about.

---

## Worktrees and Your Editor

Most editors handle this fine — you just open the worktree directory as a separate project. In VS Code:

```bash
code ../myrepo-hotfix
```

Opens a new window pointed at the worktree. It's treated as a completely independent project. Language servers, extensions, everything works normally.

JetBrains IDEs (IntelliJ, Rider, etc.) work the same way — open the worktree directory as a new project. The IDE will index it separately.

One thing to be aware of: if your editor is watching files for changes, it's watching the working tree it was opened from. Changes in another worktree won't trigger its file watcher. This is correct behaviour and usually what you want.

---

## The Bare Repository Pattern

For teams who use worktrees heavily, there's a variant worth knowing: the **bare clone**.

A normal clone gives you `.git/` plus a working tree. A bare clone gives you only the git database, with no working tree attached:

```bash
git clone --bare git@github.com:you/myrepo.git myrepo.git
cd myrepo.git
git worktree add ../myrepo-main main
git worktree add ../myrepo-feature feature/payments
```

Now you have a clean separation: `myrepo.git` is purely the database, and all your working trees are explicitly created as worktrees. Nothing lives in the bare repo directory itself.

This is cleaner architecturally and some people find it easier to reason about. The commands are identical. The only difference is the starting point.

---

## Quick Reference

```bash
# Create worktree on existing branch
git worktree add ../dir branch-name

# Create worktree on new branch (branching from current HEAD)
git worktree add -b new-branch ../dir

# Create worktree on new branch from specific point
git worktree add -b new-branch ../dir main

# List all worktrees
git worktree list

# Remove a worktree (directory must be clean)
git worktree remove ../dir

# Remove with uncommitted changes
git worktree remove --force ../dir

# Clean up references to deleted worktree directories
git worktree prune

# Move a worktree to a different path
git worktree move ../dir ../new-dir
```

---

## When to Use Worktrees

Worktrees are worth reaching for when:

- You need to context-switch branches without losing your current state
- You're doing a code review that would benefit from running the code
- You want to run two versions of the app simultaneously (different ports, different configs)
- You want a permanent clean reference copy of main alongside your work

They're probably overkill when:

- The switch is trivial and your working tree is clean
- You're just checking a file on another branch (`git show branch:path/to/file` is faster)
- The repo has very large build artifacts and disk space is a concern

The learning curve is shallow — the commands above are essentially all of it. The shift is more about changing the habit of reaching for `git stash` or `git switch` and reaching for `git worktree add` instead. Once it's in the muscle memory, it's difficult to go back.

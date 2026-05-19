---
title: "Useful Git Tips, Tricks and Workflow"
date: 2014-09-08
draft: false
tags: ["git", "workflow", "rebase", "bash", "tips"]
description: "A collection of Git tips I picked up while levelling up on advanced workflows — getting help, a decent bash prompt, rebasing, interactive staging, and the branching model that actually works."
---

I've been spending the last few weeks going deep on Git — past the basics of commit/push/pull and into the workflows that make a team productive. Here's what I've found useful enough to write down.

## Getting Help

There are basically two ways on the command line to get help.

Git will print a short overview of the call syntax as well as the most important options for you:

```bash
git [command] -h
```

The second is having a look at the man pages themselves:

```bash
git help [command]
```

The man pages are verbose but thorough. When I'm trying to understand an option I haven't used before, `git help rebase` or `git help log` is usually worth opening.

## Git Prompt for Bash

There are many available. I like this one in particular. You have to use Homebrew to install it:

```bash
brew install bash-git-prompt
```

After installing `bash-git-prompt`, copy the following into your `~/.bash_profile` or `~/.bashrc`:

```bash
if [ -f "$(brew --prefix)/opt/bash-git-prompt/share/gitprompt.sh" ]; then
  __GIT_PROMPT_DIR=$(brew --prefix)/opt/bash-git-prompt/share
  GIT_PROMPT_ONLY_IN_REPO=1
  source "$(brew --prefix)/opt/bash-git-prompt/share/gitprompt.sh"
fi
```

Then reload your shell:

```bash
source ~/.bash_profile
```

Your prompt now shows the current branch, whether you have uncommitted changes, how many commits ahead/behind you are from the remote, and whether you're mid-rebase or mid-merge. It looks something like this when everything is clean:

```
(main ✔) $
```

And like this when you have changes:

```
(feature/my-branch ✘ ↑2) $
```

Once you've used it you won't want to go back to a plain prompt.

## Useful Aliases

A few aliases I add to every machine. Put these in `~/.gitconfig` under `[alias]`:

```ini
[alias]
    st = status -s
    lg = log --oneline --graph --decorate --all
    co = checkout
    br = branch
    undo = reset HEAD~1 --mixed
    staged = diff --cached
```

`git lg` in particular is worth having — it shows the full branch graph in a compact form, which is invaluable when you're working with multiple branches and rebasing.

## Interactive Staging

One of the most useful things I learned: you don't have to commit all your changes at once. `git add -p` lets you walk through each hunk of changes and decide interactively what to stage:

```bash
git add -p
```

For each hunk you get a prompt:

```
Stage this hunk [y,n,q,a,d,/,s,?]?
```

- `y` — stage this hunk
- `n` — skip it
- `s` — split into smaller hunks
- `q` — quit, leaving the rest unstaged

This lets you make two logical commits out of work you did in one sitting, which keeps your history clean and makes code review easier.

## Git Rebase

This was the main thing I wanted to understand. Rebase is one of those commands that sounds dangerous until you understand what it's doing, after which it becomes indispensable.

### What Rebase Does

`git merge` takes two branch tips and creates a new merge commit that joins them. `git rebase` does something different: it takes the commits on your branch and replays them on top of another branch, as if you had started from there.

```
Before rebase:

      A---B---C  feature
     /
D---E---F---G  main

After: git rebase main (from feature branch)

              A'--B'--C'  feature
             /
D---E---F---G  main
```

The commits A, B, C become A', B', C' — same changes, new commit hashes, new base. The result is a linear history without a merge commit.

### Basic Rebase

```bash
git checkout feature/my-branch
git rebase main
```

If there are conflicts, Git pauses and asks you to resolve them:

```bash
# Fix the conflicts in your editor, then:
git add <resolved-file>
git rebase --continue

# Or, if you want to give up and go back to before the rebase:
git rebase --abort
```

### Interactive Rebase

Interactive rebase (`-i`) is where the real power is. It lets you rewrite your own commits before sharing them — squash several commits into one, reorder them, edit a commit message, or drop a commit entirely:

```bash
git rebase -i HEAD~4
```

This opens an editor listing the last 4 commits:

```
pick a1b2c3d Fix null check in expense parser
pick e4f5g6h Add unit test for parser
pick i7j8k9l WIP
pick m1n2o3p Clean up logging

# Commands:
# p, pick = use commit
# r, reword = use commit, but edit the commit message
# e, edit = use commit, but stop for amending
# s, squash = use commit, but meld into previous commit
# f, fixup = like squash, but discard this commit's message
# d, drop = remove commit
```

A common workflow: squash the "WIP" commit into the one before it, and reword the result:

```
pick a1b2c3d Fix null check in expense parser
squash e4f5g6h Add unit test for parser
drop i7j8k9l WIP
pick m1n2o3p Clean up logging
```

Save and close, and Git replays the commits in the new order, pausing to let you write a combined message for the squashed pair.

### The Golden Rule of Rebase

**Never rebase commits that have been pushed to a shared branch.**

Rebase rewrites commit history — the commit hashes change. If someone else has based work on those commits, their history diverges from yours and you get a mess. Rebase is safe on your own local branches, or on branches only you are working on. Once something is on `main` or a shared feature branch, use merge.

## A Branching Workflow That Works

The workflow I've settled on, based on what I've read and experimented with:

```
main       — always deployable, protected
develop    — integration branch, features merged here
feature/*  — one branch per feature or ticket
hotfix/*   — branched off main for urgent production fixes
```

Day-to-day flow:

```bash
# Start a new feature
git checkout develop
git pull
git checkout -b feature/expense-parser

# Work, commit, work, commit
# ...

# Before merging, clean up your local commits with interactive rebase
git rebase -i develop

# Merge back to develop (no fast-forward, keeps branch visible in history)
git checkout develop
git merge --no-ff feature/expense-parser
git push origin develop

# Delete the feature branch
git branch -d feature/expense-parser
```

The `--no-ff` flag on the merge creates a merge commit even when a fast-forward is possible. This keeps the feature visible as a unit in the log, which is useful for understanding what changed and why.

## Stashing Work in Progress

When you need to switch context mid-work without committing:

```bash
# Save current changes
git stash

# Do something else (switch branches, pull, whatever)
# ...

# Bring your changes back
git stash pop
```

`git stash list` shows everything you've stashed. `git stash pop` applies the most recent stash and removes it from the list. `git stash apply stash@{2}` applies a specific stash without removing it.

## Finding What Broke Things

Two commands I use constantly when something is broken and I don't know when it was introduced:

**`git log -S "search string"`** — finds commits that added or removed a specific string. If a function call disappeared, this finds the commit that removed it:

```bash
git log -S "parseExpenseRecord"
```

**`git bisect`** — binary search through commit history to find the commit that introduced a bug. You tell it a known-good and known-bad commit, and it checks out commits in the middle for you to test:

```bash
git bisect start
git bisect bad                    # current commit is broken
git bisect good v1.2.0            # this tag was working

# Git checks out a commit in the middle
# Test it, then:
git bisect good    # or: git bisect bad

# Repeat until Git identifies the culprit
git bisect reset   # return to HEAD when done
```

It takes `log₂(n)` steps to find the bad commit among `n` candidates. In a repo with 500 commits between good and bad, you find it in about 9 tests.

---

These are the things that made the biggest difference to how I work with Git day to day. The rebase workflow in particular took some getting used to — the first time I rebased an active branch I made a mess of it — but once it clicked it changed how I think about commits. History is not just a log of what happened; it's documentation you're writing for the next person who reads the code.

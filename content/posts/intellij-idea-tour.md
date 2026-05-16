---
title: "IntelliJ IDEA in 5 Minutes: A Senior Dev's Tour for Beginners"
date: 2023-04-11
tags: ["intellij", "java", "spring-boot", "gradle", "developer-tools", "ide", "microservices"]
description: "A senior developer's 5-minute walkthrough of IntelliJ IDEA for a junior joining a Java Spring Boot Gradle microservices project — the features that matter daily, explained by someone who's used it for 15 years."
---

You've just joined the team. You've got IntelliJ IDEA open for the first time. I've got five minutes. Here's what I actually use every day — not the full manual, just the things that will make you productive immediately on a Java Spring Boot Gradle microservices project.

---

## The Layout

When you first open a project, IntelliJ gives you a few key panels. The ones you'll live in:

- **Project panel** (left) — your file tree. `⌘1` to show/hide it.
- **Editor** (centre) — where you write code. Most of your time is here.
- **Run/Debug panel** (bottom) — output from your running services.
- **Terminal** (bottom) — `⌥F12` to toggle. A full terminal inside the IDE.
- **Git panel** (bottom left) — commit history, branches, changes.

{{< figure src="/images/intellij-layout.png" alt="IntelliJ IDEA main layout with Project panel, Editor, and bottom panels" caption="The main layout — Project panel left, editor centre, tool windows along the bottom." >}}

You can hide everything and just write code. `⇧⌘F12` (Distraction Free Mode) collapses all panels. Hit it again to bring them back.

---

## Opening and Navigating a Project

Never browse the file tree to open a file. Use:

- **`⇧⇧` (Double Shift)** — Search Everywhere. Type any class name, file name, action, setting, or symbol. This is the single most important shortcut in IntelliJ. Learn it first.
- **`⌘O`** — Go to Class. Type `UserService`, hit Enter.
- **`⌘⇧O`** — Go to File. Type `application.yml`, hit Enter.
- **`⌘E`** — Recent Files. Shows everything you had open. Faster than tabs.

{{< figure src="/images/intellij-search-everywhere.png" alt="Search Everywhere dialog in IntelliJ showing class search results" caption="Double Shift opens Search Everywhere — class names, files, actions, settings, all in one place." >}}

On a microservices project you'll have multiple modules. The Project panel shows them all. But you still navigate by name, not by clicking through folders.

---

## Running a Spring Boot Application

In a Gradle Spring Boot project, IntelliJ detects your `@SpringBootApplication` class automatically. A green play button appears in the gutter next to the `main` method.

{{< figure src="/images/intellij-run-gutter.png" alt="Green play button in the gutter next to a Spring Boot main method" caption="The green play button in the gutter — click it to run or debug the application directly." >}}

Click it and choose **Run**. IntelliJ creates a Run Configuration for you automatically. You'll see the Spring Boot startup log in the Run panel at the bottom.

For subsequent runs, use the toolbar at the top right — the green triangle runs, the green bug icon debugs. Or `⌃R` to re-run the last configuration, `⌃D` to debug it.

**Run Configurations** let you set environment variables, VM options, active profiles. Click the dropdown next to the run button → **Edit Configurations**. This is where you set `--spring.profiles.active=local` or add environment variables like `DB_URL`.

{{< figure src="/images/intellij-run-config.png" alt="Run Configuration dialog showing environment variables and Spring profile settings" caption="Run Configurations — set your active Spring profile and environment variables here." >}}

---

## The Gradle Panel

`⌘⇧A` → type "Gradle" → open the Gradle tool window. Or look for the elephant icon on the right edge.

{{< figure src="/images/intellij-gradle-panel.png" alt="Gradle tool window showing tasks tree" caption="The Gradle tool window — expand to find tasks, run them directly, or trigger a full sync." >}}

What I use it for:
- **Reload** (the circular arrow) — whenever you change `build.gradle`, hit this to sync dependencies
- **Tasks → build → build** — full project build
- **Tasks → verification → test** — run all tests
- Double-clicking any task runs it

When a dependency isn't resolving, the first thing I do is hit **Reload All Gradle Projects**. Fixes it 80% of the time.

---

## Writing Code — The Shortcuts That Matter

IntelliJ's code completion is always on. Start typing and it suggests. `Tab` to accept. But the shortcuts that actually change your speed:

**Generate code: `⌘N`**
Inside a class, hit `⌘N`. You get a menu: Constructor, Getter, Setter, toString, equals/hashCode, Override Methods, implement interface methods. You will never write a getter by hand again.

{{< figure src="/images/intellij-generate.png" alt="Generate menu showing options for constructor, getters, setters, toString" caption="`⌘N` inside a class — generate constructors, getters, setters, equals/hashCode in seconds." >}}

**Refactor: `⌃T`**
Rename, Extract Method, Extract Variable, Inline, Change Signature. Rename especially — `⇧F6` renames a symbol everywhere it's used across the entire project. Not just the file. Everywhere.

**Find usages: `⌥F7`**
Click on any method, class, or field and hit `⌥F7`. Shows every place in the codebase that calls or references it. Essential for understanding an unfamiliar codebase.

**Go to definition: `⌘B` or `⌘Click`**
Click on a method call and hit `⌘B`. Jumps to the definition. If it's in a library, it decompiles the bytecode and shows you the source. Works on Spring beans too.

**Go to implementation: `⌘⌥B`**
You're on an interface method. `⌘⌥B` jumps to the implementing class. On a service interface with multiple implementations, it shows you a list.

**Recent locations: `⌘⇧E`**
Like Recent Files but shows you the actual code snippet where you were. Useful when you're jumping between several places.

**Move line: `⇧⌥↑` / `⇧⌥↓`**
Move a line or selected block up or down. Small thing, constant use.

**Duplicate line: `⌘D`**

**Delete line: `⌘⌫`**

---

## Running and Writing Tests

IntelliJ integrates with JUnit and Mockito out of the box. The same green gutter button appears next to `@Test` methods and test classes.

{{< figure src="/images/intellij-test-gutter.png" alt="Green play buttons next to @Test methods in a JUnit test class" caption="Play buttons appear next to each @Test method and the class itself — run one test or all tests in the class." >}}

To run a single test: click the gutter button next to the `@Test` method.
To run all tests in a class: click the gutter button next to the class declaration.
To run all tests in the project: Gradle panel → Tasks → verification → test.

The test results panel shows a tree of passed (green) and failed (red) tests. Click a failed test to see the assertion error and the stack trace. Click the stack trace line to jump directly to that line of code.

{{< figure src="/images/intellij-test-results.png" alt="Test results panel showing passed and failed tests with assertion details" caption="Test results — green passes, red failures. Click a failure to see the full assertion error and jump to the failing line." >}}

**Rerun failed tests only:** There's a button in the test results panel to rerun only the tests that failed. Saves time during a fix-and-test cycle.

**Coverage:** Right-click a test class or directory → **Run with Coverage**. IntelliJ overlays your source files with green (covered) and red (not covered) line highlighting.

---

## Debugging

Put a breakpoint by clicking in the gutter to the left of a line number. A red circle appears. Then run the application or test in debug mode (`⌃D` or the bug icon).

{{< figure src="/images/intellij-breakpoint.png" alt="Red breakpoint circle in the gutter with the debugger paused on that line" caption="A breakpoint in the gutter — the debugger pauses here and you can inspect every variable in scope." >}}

When execution hits the breakpoint, IntelliJ pauses and shows you:

- **Variables panel** — every variable in the current scope, expandable for objects
- **Watches** — expressions you define that are evaluated continuously
- **Frames** — the full call stack

Navigation while paused:
- `F8` — Step Over (next line, don't go into the method)
- `F7` — Step Into (go into the method being called)
- `⇧F7` — Smart Step Into (choose which method call to step into)
- `F9` — Resume (continue to next breakpoint)
- `⌥F9` — Run to Cursor (run until the line your cursor is on)

**Evaluate Expression: `⌥F8`**
While paused, hit `⌥F8` and type any expression. IntelliJ evaluates it in the current context. You can call methods, inspect objects, test logic — without changing your code. I use this constantly.

{{< figure src="/images/intellij-evaluate.png" alt="Evaluate Expression dialog with a Java expression being evaluated in the debugger context" caption="Evaluate Expression — run any Java expression in the current debug context. No print statements needed." >}}

**Conditional breakpoints:** Right-click a breakpoint → add a condition. The debugger only pauses when the condition is true. Essential when you're debugging inside a loop or a method called hundreds of times.

---

## Git Integration

IntelliJ's git integration is good enough that I rarely need the terminal for git.

**`⌘K`** — Commit dialog. Shows all changed files, diff on the right, commit message at the top. You can stage individual files or individual lines (select lines in the diff, right-click → Stage Selected Ranges).

{{< figure src="/images/intellij-commit.png" alt="IntelliJ commit dialog showing changed files list and diff view" caption="The commit dialog — stage files, review diffs, write your commit message, all in one place." >}}

**`⌘⇧K`** — Push. After committing, this opens the push dialog.

**`⌃V`** — VCS Operations popup. Quick access to pull, fetch, branches, stash, revert.

**Git panel (bottom):** Shows the full commit log, branching graph, who changed what. The **Log** tab has a search bar — search by author, message, changed file.

**Local History:** Right-click any file → Local History → Show History. IntelliJ keeps its own timeline of every save, independent of git. Useful when you've made a mess and haven't committed yet.

---

## Spring Boot Specific Features

IntelliJ Ultimate (not Community) has dedicated Spring support:

**Spring Boot run dashboard:** When you have multiple services, they all appear in the Services panel (`⌘8`). Start, stop, and view logs for each service independently.

{{< figure src="/images/intellij-services.png" alt="IntelliJ Services panel showing multiple Spring Boot microservices with run/stop controls" caption="The Services panel — manage all your microservices from one place, start and stop independently." >}}

**Bean navigation:** `⌘B` on a Spring bean reference jumps to its definition. The gutter shows bean injection arrows — click them to navigate between where a bean is defined and where it's injected.

**`application.yml` support:** Property keys are autocompleted. Hover over a key and IntelliJ tells you the type, default value, and description from Spring's metadata. Misspelled properties get flagged immediately.

**Endpoint map:** Tools → HTTP Client, or the Endpoints tab in the Spring panel, lists all `@RequestMapping` endpoints in the project. Click one to navigate to the controller method.

---

## The Things I Do Every Morning

When I sit down:
1. `⌃V` → Fetch — see what's on the remote
2. Check the Git Log panel for what the team pushed overnight
3. `⌃R` — rerun the last test configuration I had running

And the one habit that will save you the most time: **stop using the mouse to navigate**. Double Shift, `⌘O`, `⌘E`, `⌘B`, `⌥F7`. Once these are in your fingers, the file tree becomes something you glance at occasionally, not something you browse through.

---

## Shortcut Cheat Sheet

| Action | Shortcut |
|--------|----------|
| Search Everywhere | `⇧⇧` |
| Go to Class | `⌘O` |
| Go to File | `⌘⇧O` |
| Recent Files | `⌘E` |
| Recent Locations | `⌘⇧E` |
| Find Usages | `⌥F7` |
| Go to Definition | `⌘B` |
| Go to Implementation | `⌘⌥B` |
| Rename | `⇧F6` |
| Generate | `⌘N` |
| Refactor | `⌃T` |
| Run last config | `⌃R` |
| Debug last config | `⌃D` |
| Commit | `⌘K` |
| Push | `⌘⇧K` |
| VCS Operations | `⌃V` |
| Step Over | `F8` |
| Step Into | `F7` |
| Resume | `F9` |
| Evaluate Expression | `⌥F8` |
| Terminal | `⌥F12` |
| Distraction Free Mode | `⇧⌘F12` |

That's it. The rest you'll pick up as you go. But these are the ones I reach for every single day — and the ones that, once you stop thinking about them and just do them, make IntelliJ feel like an extension of how you think rather than a tool you're operating.

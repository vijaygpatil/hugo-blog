---
title: "Building a Domain-Specific MCP Toolserver for Claude"
date: 2026-05-14
tags: ["ai", "mcp", "claude", "developer-tools", "tooling", "productivity"]
description: "How I built a custom MCP server and skills layer that turns Claude into a domain expert for my team's daily engineering work — log investigations, pre-deployment checks, support triage, and database queries."
---

An alert fires at 9 AM. A colleague pastes a Slack message: a user's workflow is stuck, something broke overnight, they need an answer fast. The old process: open the log dashboard, try to remember the right index name, recall which field holds the correlation ID (is it `requestId` or `correlationId`?), write a query, realize the time range is wrong, try again, cross-reference a schema doc to figure out which table join gets you the workflow state, write a SQL query, probably get a column name wrong on the first attempt. Thirty minutes later you have an answer.

That friction doesn't come from the complexity of the problem. It comes from holding too much tribal knowledge in your head — field names, index patterns, schema layouts, query templates — while simultaneously trying to reason about the actual issue.

This is the problem I set out to fix by building a custom MCP toolserver for Claude.

## Why Standard Claude Isn't Enough

Claude is an exceptional reasoning engine, but it's context-blind by default. It doesn't know which Elasticsearch index your service logs to. It doesn't know that your log schema uses `description` instead of `message`, or that your database's UUID columns require a specific hex format in WHERE clauses, or that "check the integration tests before a release" means running four specific queries across two systems in a particular order.

The gap isn't intelligence — Claude has plenty of that. The gap is **domain context**: the accumulated knowledge of how your specific stack is wired, where things live, and what procedures actually work.

The standard approach is to paste that context into every prompt. That's fragile, inconsistent, and doesn't scale. The better approach is to encode that context into a layer of tools and instructions that Claude can always reach for — so it never has to guess.

That's what an MCP toolserver is.

## What MCP Is (and Isn't)

The Model Context Protocol (MCP) is an open standard that lets you expose tools, resources, and prompts to AI assistants like Claude. An MCP server is a process that Claude can call into — you define TypeScript (or Python) functions, register them as tools, and Claude gets to invoke them with structured parameters and receive structured results.

What MCP is **not** is a way to make Claude smarter. It's a way to give Claude hands — the ability to execute real operations against your systems. The intelligence is still Claude's; the execution capability is what you provide.

A well-designed MCP toolserver is like giving Claude a fully equipped workstation tuned for your domain, instead of asking it to do surgery with its bare hands.

## The Two-Layer Design

The system I built has two distinct layers that work together. Understanding the distinction is the key architectural insight.

{{< mermaid >}}
graph TD
    U["👤 Engineer"] -->|"types a question"| CM["CLAUDE.md\nRouting Layer"]
    CM -->|"routes to"| SK["Skills\n(Markdown procedure files)"]
    SK -->|"invokes"| T1["Log Search Tools"]
    SK -->|"invokes"| T2["Health Check Tools"]
    SK -->|"invokes"| T3["Analysis Tools"]
    SK -->|"invokes"| T4["Integration Test Tools"]
    SK -->|"invokes"| T5["Schema + Query Tools"]
    T1 --> ES["Elasticsearch / Logs"]
    T2 --> ES
    T3 --> ES
    T4 --> ES
    T5 --> DB["Database"]
    ES -->|"structured results"| CL["Claude\n(reasoning)"]
    DB -->|"structured results"| CL
    CL -->|"narrative answer"| U

    style CM fill:#f5a623,color:#000
    style SK fill:#7ed321,color:#000
    style CL fill:#4a90e2,color:#fff
{{< /mermaid >}}

### Layer 1: MCP Tools (Execution)

Tools are TypeScript functions that know how to do one thing well. Each tool encapsulates:

- **Which system to query** — the right Elasticsearch index, the right database connection, the right API endpoint
- **Which fields to use** — no caller ever needs to remember that log timestamps live in `@timestamp` or that a specific service uses `description` instead of `message`
- **How to authenticate** — credentials are managed by the server, never exposed to the calling context
- **What results mean** — tools return structured, normalized data, not raw API responses

I organized tools into five categories that map to the main types of work my team does:

**Log Search Tools**

The foundation. These wrap Elasticsearch queries with domain-specific defaults:

- `quick_search` — full-text search across all fields, returns compact results by default. The key feature: for well-known services it knows exactly which 15 fields matter; for anything else it auto-retries with full field output if results look empty.
- `trace_request` — finds all log entries for a given correlation ID or request ID, following a request across services
- `scroll_search_logs` — handles large result sets that exceed normal query limits, useful for counting patterns across thousands of events
- `get_log_context` — given a timestamp, returns N entries before and after it — invaluable for understanding what surrounded a specific event

**Health Check Tools**

Operational monitoring queries built for deployment events:

- `service_health_check` — post-deployment error summary, excluding known/expected errors so signal isn't buried in noise
- `pipeline_health_check` — migration health: successful migrations, failed migrations, "no data found" cases, stuck migrations, processing times

**Analysis Tools**

Higher-level tools that investigate specific types of problems end-to-end:

- `analyze_api_failure` — investigates failed API calls by searching logs for the correlation ID, identifying the error type, explaining the root cause, and listing which fields the endpoint supports vs. rejects

**Integration Test Tools**

This category is particularly valuable before any deployment. These tools answer: "is it safe to ship?"

A bit of context on how this works: our services run a full integration test suite on a scheduled cadence in a dedicated non-production environment. Each test run executes in its own pod, and every test request carries a correlation ID that flows through the service logs. That means you can trace exactly what the service did — or failed to do — for any individual test. The tools below are built on top of that structure.

- `integration_test_summary` — finds recent test runs, reports pass/fail/skip counts, identifies which pod ran them
- `integration_test_errors` — gets the actual exception messages from a specific test run
- `integration_test_trace` — traces a single failing test by correlation ID to find exactly what happened in the service when the test ran
- `integration_test_version_analysis` — the most powerful one: groups test runs by application version, identifies tests that have **never passed** in the current version (critical failures vs. flaky tests), shows the last time each failing test passed and in which version
- `integration_test_reporter` — orchestrates all the above into a single comprehensive markdown report: summary table, per-test analysis with Kibana links, root cause categories, recommendations

**Schema + Query Tools**

The database investigation layer. This one has an interesting design I'll cover in the design decisions section:

- `execute_query` / `describe_table` — direct SQL execution (integration environment only) and schema inspection

### Layer 2: Skills (Intent)

Tools are powerful but passive — they do nothing on their own. Skills are what activate them.

A skill is a Markdown file that Claude reads at invocation time. It tells Claude:

- **When to activate** — what patterns in the user's message trigger this skill
- **What the goal is** — what a good answer looks like for this type of question
- **Which tools to call** — in what order, with what parameters
- **How to interpret results** — what to look for, what counts as an error vs. noise
- **How to format the answer** — what to include in the response and what to leave out

Here's a simplified example of what a skill definition looks like:

{{< highlight markdown >}}
---
name: integration-test-report
description: >
  Generate a pre-deployment integration test report. Trigger on phrases like
  "check integration tests", "safe to deploy?", "pre-deployment check".
---

# Integration Test Report

1. Call `integration_test_summary` with timeRange: "2h"
2. Identify the most recent test run
3. Call `integration_test_version_analysis` with timeRange: "7d"
4. For any critical failures (never passed in current version):
   - Call `integration_test_trace` for each failing test
5. Call `integration_test_reporter` to generate full markdown report
6. Summarize: total tests, critical failures, last pass for each failing test,
   go/no-go recommendation
{{< /highlight >}}

The skill doesn't contain logic — it contains *procedure*. Claude supplies the reasoning; the skill supplies the domain-specific workflow.

{{< mermaid >}}
sequenceDiagram
    participant E as Engineer
    participant C as Claude
    participant S as Skill
    participant T as Tools
    participant SY as Systems

    E->>C: "check integration tests before deployment"
    C->>S: load integration-test-report skill
    S-->>C: procedure: call these tools in this order
    C->>T: integration_test_summary(timeRange: 2h)
    T->>SY: query log index
    SY-->>T: test run results
    T-->>C: structured summary
    C->>T: integration_test_version_analysis(timeRange: 7d)
    T->>SY: query by version
    SY-->>T: failure history
    T-->>C: critical failures identified
    C->>T: integration_test_reporter()
    T-->>C: markdown report generated
    C-->>E: go/no-go recommendation + report
{{< /mermaid >}}

**Tools without skills are just API calls. Skills without tools are just prompts. Together they create something that behaves like a domain expert who knows exactly which systems to check and in what order.**

### The CLAUDE.md Routing Layer

There's a third piece that ties it together: a `CLAUDE.md` file at the project level. This is Claude Code's mechanism for project-specific instructions — it's loaded at session start and stays in context throughout.

My `CLAUDE.md` does several things:

- **Maps question types to skills** — "if the user pastes a Slack support message, invoke the ask-support-question skill"
- **Sets field name conventions** — "use `description` not `message`, use `application` not `app`"
- **Defines time window limits** — "never use time ranges larger than 24h for Elasticsearch queries — they will time out"
- **Specifies environment routing** — which MCP server prefix to use for which deployment environment
- **Identifies the schema doc location** — "before generating any SQL query, read the XML schema file from this directory"

Without `CLAUDE.md`, you'd need to repeat these instructions in every conversation. With it, Claude arrives at each session already knowing the rules.

## Before and After

Three examples that show what this actually changes:

| Scenario | Before | After |
|---|---|---|
| Log Investigation | ~20 min | ~30 sec |
| Pre-Deployment Check | ~15 min | ~2 min |
| Support Question Triage | ~20 min | ~3 min |

### Log Investigation

**Before:** Receive a correlation ID in a Slack message. Open Elasticsearch, navigate to the right index (which one was it again — `log-2` or `data-2`?), construct a query using the right field names, scan results across multiple services, try to reconstruct the timeline manually. 15-20 minutes.

**After:** Paste the correlation ID into the conversation. The `trace_request` tool queries the right index with the right field names, returns all matching log entries sorted chronologically, Claude reads them and gives you a narrative of exactly what happened. 30 seconds.

### Pre-Deployment Check

**Before:** Before releasing a new version: manually check the integration test dashboard (is the test pod still running? did it finish?), open the version history to see which tests were failing before this version and which are new failures, check error rates in the service health dashboard, check the deployment history to see when the current version went out. Four tabs, 15 minutes, easy to miss something.

**After:** "Check integration tests before deployment." The `integration_test_version_analysis` tool identifies every test that has never passed in the current version. The `integration_test_reporter` generates a full markdown report with per-test analysis, Kibana links, and a go/no-go recommendation. Saved to a file. 2 minutes.

### Support Question Triage

**Before:** A support message arrives: something isn't working for a user and a colleague needs an answer fast. Find the user in the system (which field is the login ID again?), trace their state across several related tables, figure out what's blocking them and why. Requires knowing 4-5 table names and their join columns from memory. 20+ minutes.

**After:** Paste the support message. The `ask-support-question` skill detects the question type, reads the relevant schema docs to generate correct SQL for each table, and Claude interprets the results to identify the root cause. Ready-to-run queries included. Under 3 minutes.

## Key Design Decisions

A few decisions that made this work well — and would have made it not work if I'd gotten them wrong:

### Tools Own Their Field Knowledge

Every tool hardcodes the field names, index patterns, and conventions for its domain. Callers — including Claude — never need to know that one service uses `description` instead of `message`, or that aggregation queries need a `.keyword` suffix on text fields, or that time range queries over 24 hours will time out.

This sounds obvious but it's the single most important reliability decision. Before this pattern, roughly 30% of queries failed because Claude used the wrong field name. After: essentially zero.

### Schema Docs as Executable Context

The database schema is stored as XML files — one per table, covering hundreds of tables across the system. Each file contains every column, its data type, its nullable status, and all foreign key relationships.

Rather than trying to memorize this or embed it in prompts, the CLAUDE.md instructs Claude to read the relevant XML file before generating any SQL query. Combined with a reusable query library of known-correct queries for common investigations, this means SQL queries are correct on the first attempt almost every time.

The query library is a simple Markdown file with sections for each common investigation pattern. When a new investigation requires a query that doesn't exist in the library, Claude builds it from the schema docs and the library gets updated. It's a living document that gets better with use.

### Skills Are the ROI

Individual tools are useful. The compounding value comes from skills that chain tools together into coherent investigations.

The `release_monitor` skill is a good example: it calls the version-based failure analysis, traces the most critical failing tests individually, fetches the git diff between the last-passing version and the current one, and writes a comprehensive markdown report. None of those tools individually answers "is this deployment safe?" — but the skill does.

When I think about what made the investment worthwhile, it's not the tool count, it's that every common investigation pattern now has a skill. The list of things Claude can do end-to-end without me guiding it through each step is what changed the daily experience.

### Keep Skills Narrow and Composable

Early versions of the skills were too broad — one skill that tried to handle "any production issue" would balloon into a decision tree that was hard to maintain and inconsistent in behavior.

The current approach: one skill per question type, each skill does one investigation pattern well. The `ask-support-question` skill handles support triage. The `integration-test-report` skill handles pre-deployment checks. The `service-deploy-snapshot` skill handles the before/after deployment health comparison. Narrow scope = predictable behavior = trustworthy output.

## What Generalizes

This architecture isn't specific to my domain. The pattern applies to any team that has:

- **Specialized data stores** with non-obvious field names, index patterns, or query conventions
- **Repetitive investigation workflows** that involve multiple systems in a known order
- **Accumulated tribal knowledge** about how things are wired that lives in people's heads rather than in documentation
- **Schema or API docs** that are authoritative but verbose — too large to paste into a prompt every time

The components you need to build:

1. **MCP server** — one TypeScript (or Python) project that registers tools with the MCP SDK
2. **Tool categories** — organize by the type of work they support (search, health, analysis, testing, schema)
3. **Skills directory** — Markdown files, one per investigation pattern, stored where Claude Code can find them
4. **CLAUDE.md** — project-level config that routes question types to skills and sets field conventions
5. **A query/template library** — for any domain involving structured queries, a living library of known-correct examples

The investment is upfront. Writing the first tool is slow — you have to figure out the right abstractions, decide what to hardcode vs. parameterize, understand the MCP tool registration API. Writing the tenth tool is fast. Writing the twentieth is trivial. The skills compound faster than the tools because each new skill can reuse existing tools in new combinations.

The result, after a few months of building: an AI assistant that doesn't just answer questions but actively investigates them, using the same tools and following the same procedures a senior engineer on the team would use. Not because it's smarter than before — but because it finally knows where everything is.

---

*The Model Context Protocol specification and SDK are available at [modelcontextprotocol.io](https://modelcontextprotocol.io). Claude Code's CLAUDE.md documentation is at [docs.anthropic.com](https://docs.anthropic.com).*

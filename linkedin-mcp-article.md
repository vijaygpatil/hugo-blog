# Building a Domain-Specific MCP Toolserver for Claude

An alert fires at 9 AM. A colleague pastes a Slack message: a user's workflow is stuck, something broke overnight, they need an answer fast. The old process: open the log dashboard, try to remember the right index name, recall which field holds the correlation ID (is it `requestId` or `correlationId`?), write a query, realize the time range is wrong, try again, cross-reference a schema doc to figure out which table join gets you the workflow state, write a SQL query, probably get a column name wrong on the first attempt. Thirty minutes later you have an answer.

That friction doesn't come from the complexity of the problem. It comes from holding too much tribal knowledge in your head — field names, index patterns, schema layouts, query templates — while simultaneously trying to reason about the actual issue.

This is the problem I set out to fix by building a custom MCP toolserver for Claude.

---

## Why Standard Claude Isn't Enough

Claude is an exceptional reasoning engine, but it's context-blind by default. It doesn't know which Elasticsearch index your service logs to. It doesn't know that your log schema uses `description` instead of `message`, or that your database's UUID columns require a specific hex format in WHERE clauses, or that "check the integration tests before a release" means running four specific queries across two systems in a particular order.

The gap isn't intelligence — Claude has plenty of that. The gap is **domain context**: the accumulated knowledge of how your specific stack is wired, where things live, and what procedures actually work.

The standard approach is to paste that context into every prompt. That's fragile, inconsistent, and doesn't scale. The better approach is to encode that context into a layer of tools and instructions that Claude can always reach for — so it never has to guess.

That's what an MCP toolserver is.

---

## What MCP Is (and Isn't)

The Model Context Protocol (MCP) is an open standard that lets you expose tools, resources, and prompts to AI assistants like Claude. An MCP server is a process that Claude can call into — you define TypeScript (or Python) functions, register them as tools, and Claude gets to invoke them with structured parameters and receive structured results.

What MCP is **not** is a way to make Claude smarter. It's a way to give Claude hands — the ability to execute real operations against your systems. The intelligence is still Claude's; the execution capability is what you provide.

A well-designed MCP toolserver is like giving Claude a fully equipped workstation tuned for your domain, instead of asking it to do surgery with its bare hands.

---

## The Two-Layer Design

The system I built has two distinct layers that work together. Understanding the distinction is the key architectural insight.

[ INSERT ARCHITECTURE DIAGRAM IMAGE HERE ]
*The full flow: engineer's question → CLAUDE.md routing → Skills → Tools → Systems → Claude reasoning → answer*

### Layer 1: MCP Tools (Execution)

Tools are TypeScript functions that know how to do one thing well. Each tool encapsulates:

- **Which system to query** — the right Elasticsearch index, the right database connection, the right API endpoint
- **Which fields to use** — no caller ever needs to remember that a specific service uses `description` instead of `message`
- **How to authenticate** — credentials are managed by the server, never exposed to the calling context
- **What results mean** — tools return structured, normalized data, not raw API responses

I organized tools into five categories that map to the main types of work my team does:

**Log Search Tools**
The foundation. These wrap Elasticsearch queries with domain-specific defaults. `quick_search` does full-text search and knows which fields matter for each service. `trace_request` follows a request across services by correlation ID. `get_log_context` returns entries before and after a specific timestamp — invaluable for understanding what surrounded an event.

**Health Check Tools**
Operational monitoring queries built for deployment events. Post-deployment error summaries that exclude known noise, pipeline health checks that surface stuck or failed migrations.

**Analysis Tools**
Higher-level tools that investigate specific problem types end-to-end — API failure investigation that identifies the error type, explains the root cause, and lists which fields the endpoint supports vs. rejects.

**Integration Test Tools**
This category is particularly valuable before any deployment. Our services run a full integration test suite on a scheduled cadence in a non-production environment. Each test request carries a correlation ID that flows through the service logs, so you can trace exactly what happened for any individual test.

- `integration_test_summary` — finds recent test runs, reports pass/fail/skip counts
- `integration_test_errors` — gets the actual exception messages from a specific run
- `integration_test_trace` — traces a single failing test by correlation ID
- `integration_test_version_analysis` — the most powerful one: groups runs by application version, identifies tests that have **never passed** in the current version (critical failures vs. flaky tests), shows the last time each failing test passed
- `integration_test_reporter` — orchestrates all the above into a single comprehensive markdown report

**Schema + Query Tools**
Direct SQL execution and schema inspection for database investigations.

### Layer 2: Skills (Intent)

Tools are powerful but passive — they do nothing on their own. Skills are what activate them.

A skill is a Markdown file that Claude reads at invocation time. It tells Claude when to activate, what a good answer looks like, which tools to call and in what order, how to interpret results, and how to format the response.

Here's a simplified example:

```
name: integration-test-report
description: Generate a pre-deployment integration test report.
Trigger on: "check integration tests", "safe to deploy?", "pre-deployment check"

Steps:
1. Call integration_test_summary with timeRange: "2h"
2. Identify the most recent test run
3. Call integration_test_version_analysis with timeRange: "7d"
4. For any critical failures: call integration_test_trace for each failing test
5. Call integration_test_reporter to generate full markdown report
6. Summarize: total tests, critical failures, go/no-go recommendation
```

The skill doesn't contain logic — it contains *procedure*. Claude supplies the reasoning; the skill supplies the domain-specific workflow.

[ INSERT SEQUENCE DIAGRAM IMAGE HERE ]
*The sequence: engineer asks → Claude loads skill → skill drives tool calls → systems return data → Claude synthesizes answer*

**Tools without skills are just API calls. Skills without tools are just prompts. Together they create something that behaves like a domain expert who knows exactly which systems to check and in what order.**

### The CLAUDE.md Routing Layer

There's a third piece that ties it together: a `CLAUDE.md` file at the project level. This is Claude Code's mechanism for project-specific instructions — loaded at session start and stays in context throughout.

It maps question types to skills, sets field name conventions, defines time window limits for queries, specifies environment routing, and identifies schema doc locations. Without it, you'd repeat these instructions in every conversation. With it, Claude arrives already knowing the rules.

---

## Before and After

| Scenario | Before | After |
|---|---|---|
| Log Investigation | ~20 min | ~30 sec |
| Pre-Deployment Check | ~15 min | ~2 min |
| Support Question Triage | ~20 min | ~3 min |

**Log Investigation**
Receive a correlation ID in a Slack message. Before: open Elasticsearch, find the right index, construct a query with the right field names, reconstruct the timeline manually. 15–20 minutes. After: paste the correlation ID, get a narrative of exactly what happened. 30 seconds.

**Pre-Deployment Check**
Before: manually check the test dashboard, open version history to see which failures are new vs. pre-existing, check error rates, check deployment history. Four tabs, 15 minutes. After: "Check integration tests before deployment." Version analysis identifies every test that has never passed in the current version. Full report generated with per-test analysis and a go/no-go recommendation. 2 minutes.

**Support Question Triage**
Before: find the user across several related tables, trace their state, figure out what's blocking them. Requires knowing 4–5 table names and join columns from memory. 20+ minutes. After: paste the support message, get ready-to-run queries and a root cause analysis. Under 3 minutes.

---

## Key Design Decisions

**Tools own their field knowledge.** Every tool hardcodes the field names, index patterns, and conventions for its domain. Callers — including Claude — never need to know that one service uses `description` instead of `message`. Before this pattern, roughly 30% of queries failed because Claude used the wrong field name. After: essentially zero.

**Schema docs as executable context.** The database schema is stored as XML files — one per table, every column and foreign key relationship. Rather than embedding this in prompts, the CLAUDE.md instructs Claude to read the relevant XML file before generating any SQL query. Combined with a reusable query library of known-correct queries, SQL is correct on the first attempt almost every time. The query library grows with use — a living document.

**Skills are the ROI.** Individual tools are useful. The compounding value comes from skills that chain tools into coherent investigations. The `release_monitor` skill calls version failure analysis, traces critical failing tests, fetches the git diff between the last-passing and current version, and writes a comprehensive report. None of those tools individually answers "is this deployment safe?" — but the skill does.

**Keep skills narrow and composable.** Early versions were too broad — one skill for "any production issue" ballooned into an unmaintainable decision tree. Current approach: one skill per question type. The `ask-support-question` skill handles support triage. The `integration-test-report` skill handles pre-deployment checks. Narrow scope = predictable behavior = trustworthy output.

---

## What Generalizes

This architecture applies to any team that has:

- **Specialized data stores** with non-obvious field names, index patterns, or query conventions
- **Repetitive investigation workflows** that involve multiple systems in a known order
- **Accumulated tribal knowledge** that lives in people's heads rather than in documentation
- **Schema or API docs** that are authoritative but too large to paste into a prompt every time

The components you need:

1. **MCP server** — one TypeScript or Python project that registers tools with the MCP SDK
2. **Tool categories** — organized by work type (search, health, analysis, testing, schema)
3. **Skills directory** — Markdown files, one per investigation pattern
4. **CLAUDE.md** — project-level config that routes question types to skills
5. **A query/template library** — for any domain involving structured queries, a living library of known-correct examples

The investment is upfront. Writing the first tool is slow. Writing the tenth is fast. Writing the twentieth is trivial. Skills compound faster than tools because each new skill reuses existing tools in new combinations.

The result: an AI assistant that doesn't just answer questions but actively investigates them, using the same tools and following the same procedures a senior engineer on the team would use. Not because it's smarter than before — but because it finally knows where everything is.

---

*The Model Context Protocol specification and SDK are available at modelcontextprotocol.io. Claude Code's CLAUDE.md documentation is at docs.anthropic.com.*

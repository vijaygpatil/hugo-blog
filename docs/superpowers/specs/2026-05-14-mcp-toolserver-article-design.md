# MCP Toolserver Article Design

**Goal:** A practical walkthrough article (Hugo blog + LinkedIn) explaining how to build a domain-specific MCP toolserver for Claude — using the author's real project as the concrete example.

**Audience:** Developer tools and AI/tooling enthusiasts who want to extend Claude with custom tooling.

**Payoff:** Readers understand the two-layer MCP server + skills architecture well enough to design something similar for their own domain.

**Tone:** Practical walkthrough — not personal narrative, not thought leadership. Concrete, technical, honest about the design decisions.

---

## Structure

### 1. Opening — The Problem (3-4 sentences)
A concrete "before" scenario: an alert fires, a colleague pastes a Slack message with a production issue. Before this system: open the log dashboard, remember the right index name, recall the correct field names, write a query, cross-reference a schema doc, write a SQL query, repeat across 4 tabs. Name the friction specifically.

### 2. The Insight — Why Standard Claude Isn't Enough
Claude is powerful but context-blind for domain-specific work. It doesn't know your log field names, your schema, your deployment tooling. The gap isn't intelligence — it's context. Introduce the solution: a custom MCP toolserver that encodes your domain.

### 3. The Two-Layer Architecture (core technical section)

**Layer 1 — MCP Tools (execution)**
TypeScript functions registered as MCP tools. Each tool encapsulates: which data store to query, which fields to use, how to authenticate, what results mean. Grouped into categories:
- Log search tools: quick search, trace by correlation ID, scroll for large datasets
- Health check tools: post-deployment snapshot, error rate analysis, notification failure analysis
- Analysis tools: API failure investigation, user-facing feature analysis (matching, deeplinks)
- Integration test tools: test summary, failure trace, version-based failure analysis, full pre-deployment report
- Schema + query tools: XML schema doc reader, reusable query library, SQL query generation

**Layer 2 — Skills (intent)**
Markdown files that tell Claude when to use which tools and how to chain them. A skill is triggered by context — a Slack message, a deployment event, a customer report. Skills orchestrate multiple tool calls, interpret results, and format the answer. Tools without skills = API calls. Skills without tools = prompts. Together = domain expert behavior.

### 4. Before/After Scenarios (3 examples)
1. Log investigation: correlation ID → full trace in one response vs. 15 min of dashboard-switching
2. Pre-deployment check: one skill invocation → health snapshot + test summary + go/no-go vs. 4 manual dashboards
3. Support question: paste Slack message → diagnosis + ready-to-run SQL vs. 20 min of grepping + schema hunting

### 5. Key Design Decisions (3-4 lessons)
- Tools handle auth and field knowledge — callers never need to know index names or field names
- Schema docs as context — XML schema files + query library = correct SQL first time
- Skills are the ROI — chaining tools is where the value compounds
- CLAUDE.md as routing layer — project config that ensures the right skill fires without explicit prompting

### 6. Close — What Generalizes
Any team with domain-specific tooling, specialized logs, or proprietary schemas can apply this pattern. MCP protocol = interface. Skills = domain knowledge as prompts. Tools = execution layer. Together they turn a general-purpose AI into something that feels native to your stack.

---

## Constraints
- Zero references to any specific company, product name, or proprietary system
- Generic domain language: "log dashboard", "the service", "the schema", "the API" — not specific names
- No screenshots that reveal internal tooling names
- Code snippets should use generic placeholder names

---

## Output
- Hugo blog post: `content/posts/building-mcp-toolserver-claude.md`
- Suitable for copy-paste to LinkedIn Article with minor formatting adjustments
- Date: 2026-05-14
- Tags: ["ai", "mcp", "claude", "developer-tools", "tooling", "productivity"]
- Published (not draft)

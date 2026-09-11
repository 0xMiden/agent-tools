# Miden Agent Tools

Skills and commands for AI agents when working with the Miden ecosystem.

## Skills

Skills are applied automatically when the agent detects relevant tasks. Each skill is a `SKILL.md` file in a named directory under `skills/`.

### Rust SDK (Smart Contract Development)

- **rust-sdk-patterns** – Complete guide to `#[component]`, `#[note]`, `#[tx_script]` macros, storage patterns, native functions, asset handling, and cross-component calls
- **rust-sdk-testing-patterns** – MockChain testing workflow, account/note creation, storage verification, and multi-step test patterns
- **local-node-validation** – Validate contracts against a local Miden node after MockChain tests pass: node setup, Rust binary adaptation, state verification, and troubleshooting
- **miden-concepts** – Miden architecture from a developer perspective: actor model, accounts, notes, transactions, assets, privacy
- **rust-sdk-pitfalls** – Critical safety rules: felt arithmetic, comparison operators, stack limits, argument limits, storage naming, no-std
- **rust-sdk-source-guide** – Advanced development guide: AI practices (Plan Mode, verification-driven development, sub-agents, context engineering) and Miden source repository map for discovering patterns beyond basic skills

### React Frontend Development

- **react-sdk-patterns** – Complete `@miden-sdk/react` hook API reference: MidenProvider, query hooks, mutation hooks, transaction stages, signer integration, utilities
- **frontend-pitfalls** – Critical frontend pitfalls: client-readiness gating, multi-step WASM sequences and pointer lifetimes, COOP/COEP headers, BigInt boundaries, Bech32 network prefixes, IndexedDB state loss, the Web Worker shim, and structured error codes
- **vite-wasm-setup** – Vite + WASM configuration: required plugins, deployment headers (Nginx, Vercel, Cloudflare), TypeScript config, troubleshooting
- **frontend-source-guide** – Advanced frontend development guide: AI practices and miden-client source repository map for discovering patterns beyond basic skills
- **signer-integration** – Integrating external signers (Para, Turnkey, MidenFi wallet adapter) and building custom signers for Miden React frontends
- **testing-patterns** – Testing conventions: Vitest + testing-library setup, `@miden-sdk/react` module mocking, fixtures, TDD workflow for Miden React components

### Miden Assembly

- **masm-inline-comments** – Inline commenting conventions for .masm files (lowercase, avoid over-commenting)
- **masm-doc-comments** – Procedure documentation format (`#!` doc blocks with Inputs, Outputs, Where, Panics, Invocation)
- **masm-padding** – Stack padding conventions for `call` vs `exec` procedures
- **masm-formatting** – Orchestrator covering capitalization, `(N)` span notation, cross-repo doc-comment divergences, `Cycles:`, chained assertion style, and the `miden-format` formatter
- **masm-proc-type-signatures** – Type-signature conventions for `pub proc`: parameter and return types, semantic type aliases, struct/array/tuple types, and how a signature maps onto the operand stack

### Miden Client (Web SDK & Internals)

- **rust-client-patterns** – Rust conventions for the `miden-client` crate: error handling (`thiserror` + `ErrorHint`), `Store` trait (adding methods across `SqliteStore`/`WebStore` with cross-platform `async_trait`), `Client<AUTH>` generic pattern with the `Keystore` super-trait, `no_std` imports (`alloc::`/`core::`), `ClientBuilder` network constructors (`for_testnet()`, `for_devnet()`, `for_localhost()`), and section header formatting (`// ===` top-level, `// ---` subsections)
- **wasm-bridge** – Rust↔JS WASM boundary conventions for the `web-client` crate: `#[wasm_bindgen]` method exposure with `js_name`, newtype wrappers with `From` conversions, `js_error_with_context` error chaining with `ErrorHint`, promise handling (`await_js`/`await_ok`/`await_js_value`), data transfer objects with `getter_with_clone`, JS function imports, and the `MidenClient`/`WasmWebClient` (`WebClient`) two-layer JS API
- **idxdb-patterns** – IndexedDB/Dexie persistence conventions for the `idxdb-store` crate: Dexie transactions (`db.dexie.transaction("rw", tables, ...)`), schema interfaces (`IAccount`, `IAccountCode`), database registry (`getDatabase`/`openDatabase`), `logWebStoreError` error handling, forward-only state updates, and the TS→JS dual-commit build workflow
- **web-client-usage** – Developer-facing patterns for using the `@miden-sdk/miden-sdk` npm package: `MidenClient.create()` initialization, the resource-based API (`client.accounts`, `client.transactions`, `client.notes`, `client.pswap`, `client.tags`, `client.settings`, `client.compile`, `client.keystore`), sync ordering, type conversions (`AccountId.fromHex`, `BigInt` amounts, `NoteVisibility`), transaction flows (mint, send, consume, swap, custom contracts), private note transport, querying, import/export, and pitfall avoidance

## Commands

Custom slash commands for Claude Code (and other AI coding agents). These provide reusable, parameterized workflows that you invoke from the chat with `/<command-name>`.

### Available Commands

| Command | Purpose |
|---------|---------|
| [`/review-plan`](#review-plan) | Critical review of design documents and implementation plans |
| [`/review-security`](#review-security) | Security-focused code audit for web3/WASM/Rust/TS applications |
| [`/tdd-cycle`](#tdd-cycle) | Full test-driven development workflow with red-green-refactor discipline |
| [`/tech-debt`](#tech-debt) | Technical debt analysis with quantified impact and prioritized remediation |
| [`/deps-audit`](#deps-audit) | Dependency security scanning, license compliance, and update prioritization |
| [`/pr-enhance`](#pr-enhance) | Generate comprehensive PR descriptions with risk assessment and review checklists |
| [`/standup-notes`](#standup-notes) | Auto-generate daily standup notes from git activity and task trackers |
| [`/debug-trace`](#debug-trace) | Set up debugging environments, distributed tracing, and diagnostic tooling |

---

### review-plan

**Invoke:** `/review-plan <path-to-plan>`

**Example:**
```
/review-plan SimplifiedAPI.md
/review-plan docs/architecture-proposal.md
```

**What it does:** Performs a thorough critical review of a design document or implementation plan. The agent reads the specified file and evaluates it across six dimensions:

1. **Internal Consistency** — Checks that later sections don't contradict earlier ones, naming conventions are uniform throughout, and the summary table matches the detailed sections.
2. **Feasibility & Implementation** — Verifies that each proposed change can actually be implemented as described. For JS wrapper strategies, it checks whether Rust-side changes would really be needed. It flags proposals that depend on APIs that don't exist yet.
3. **API Design Quality** — Reviews parameter patterns for consistency (options objects vs positional args), evaluates whether defaults make sense, checks naming predictability, and identifies missing overloads or edge cases in type definitions.
4. **Completeness** — Looks for obvious missing APIs, gaps in type definitions, unaddressed error scenarios, and unspecified return types.
5. **Breaking Changes & Migration** — Identifies which changes are breaking vs additive and whether there's a clear migration path for existing users.
6. **Codebase Alignment** — Cross-references the plan against the actual source code to verify that "Current API" sections accurately reflect reality and flags anything outdated.

Each finding is tagged as `[ISSUE]`, `[SUGGESTION]`, `[QUESTION]`, or `[NITPICK]`. The review ends with a summary count and an overall readiness assessment.

**When to use it:** Before starting implementation of any design doc. Run it after writing or updating a plan to catch blind spots before you write code. Particularly valuable when the plan has been iterated on multiple times and may have accumulated internal inconsistencies.

---

### review-security

**Invoke:** `/review-security <path-to-code>`

**Example:**
```
/review-security crates/web-client/src/
/review-security crates/web-client/js/index.js
/review-security crates/idxdb-store/src/
```

**What it does:** Performs a security-focused audit tailored to the Miden stack (web3, WASM, TypeScript, Rust). The agent reads source files at the specified path and examines seven attack surfaces:

1. **Input Validation & Injection** — Checks whether user-supplied strings (hex IDs, bech32 addresses, amounts) are validated before reaching WASM/Rust. Looks for malformed input that could cause Rust panics propagating as unhandled JS exceptions, and numeric overflow risks in BigInt conversions.
2. **Key Material & Secrets** — Verifies that private keys are never logged, serialized to JSON, or exposed in error messages. Checks that seed material isn't stored in localStorage and that keystore callbacks can't leak secrets through stack traces.
3. **Transaction Safety** — Looks for parameter manipulation that could redirect funds, TOCTOU issues between building and submitting transactions, and precision loss through type coercion (string to number).
4. **WASM Boundary** — Examines JS-to-WASM interop for memory safety issues, JsValue conversion failures that could leave state inconsistent, and potential use-after-free when JS holds references to WASM objects.
5. **State & Storage** — Checks IndexedDB data integrity under concurrent tabs, race conditions in async operations that could cause double-spends, and whether store export/import could be used to replay old state.
6. **Network & RPC** — Evaluates whether RPC responses are validated before being trusted, whether a malicious endpoint could feed incorrect data, and whether TLS is enforced.
7. **Supply Chain & Dependencies** — Flags known vulnerable dependencies, checks WASM binary reproducibility, and reviews wasm-bindgen glue code.

Findings are graded by severity: `[CRITICAL]` (loss of funds / key compromise), `[HIGH]` (fix before production), `[MEDIUM]` (exploitable under specific conditions), `[LOW]` (defense-in-depth), or `[INFO]` (observation). Each finding includes the file and line number, a description, an attack scenario, and a recommended fix.

**When to use it:** Before merging any PR that touches authentication, key handling, transaction building, or WASM bindings. Also useful as a periodic audit of critical code paths.

---

### tdd-cycle

**Invoke:** `/tdd-cycle <feature-or-module-description>`

**Example:**
```
/tdd-cycle user authentication middleware
/tdd-cycle OutputNote.p2id() factory method
/tdd-cycle WebClient.create() options parsing
```

**What it does:** Executes a full Test-Driven Development workflow with strict red-green-refactor discipline across six phases:

1. **Test Specification & Design** — Analyzes requirements, defines acceptance criteria, identifies edge cases, and designs the test architecture (fixtures, mocks, test data strategy).
2. **RED Phase** — Writes failing unit tests covering happy paths, edge cases, and error scenarios. Critically, it verifies that all tests fail for the *right* reasons (missing implementation, not test errors). This is a hard gate — the workflow does not proceed until all tests fail appropriately.
3. **GREEN Phase** — Implements the minimum code needed to make tests pass. No extra features, no optimizations — just enough to go green. Another hard gate verifies all tests pass and coverage meets thresholds.
4. **REFACTOR Phase** — Improves code quality (SOLID principles, duplication removal, naming, performance) while keeping tests green. Also refactors the tests themselves for readability and maintainability.
5. **Integration & System Tests** — Follows the same red-green pattern for integration tests: write failing integration tests first, then implement the integration code to make them pass.
6. **Continuous Improvement** — Adds performance tests, additional edge cases, stress tests, and boundary tests. Ends with a final comprehensive code review.

**Configuration:** The command enforces minimum coverage thresholds (80% line, 75% branch, 100% critical path) and refactoring triggers (cyclomatic complexity > 10, method length > 20 lines, class length > 200 lines).

**Modes:**
- Default: full suite mode (write all tests, implement, refactor)
- Add `--incremental` to work one test at a time (write one failing test → make it pass → refactor → repeat)

**When to use it:** When implementing new features or modules where test quality matters. Especially valuable for core logic like transaction building, note creation, or store operations where bugs have high impact.

---

### tech-debt

**Invoke:** `/tech-debt <focus-area-or-requirements>`

**Example:**
```
/tech-debt crates/web-client - focus on API consistency and code duplication
/tech-debt full codebase scan, prioritize security-related debt
/tech-debt crates/rust-client/src/transaction/ - assess testing gaps
```

**What it does:** Performs a comprehensive technical debt analysis across five categories, then produces a prioritized remediation roadmap with ROI calculations:

1. **Debt Inventory** — Scans for code debt (duplication, high complexity, poor structure), architecture debt (missing abstractions, violated boundaries, monolithic components), testing debt (coverage gaps, flaky tests, missing integration tests), documentation debt (undocumented APIs, missing architecture diagrams), and infrastructure debt (manual deployment steps, missing monitoring).

2. **Impact Assessment** — Calculates the real cost of each debt item in developer hours and dollars. For example: "Duplicate validation logic in 5 files → 2 hours per bug fix × frequency = X hours/month." Includes risk stratification (critical/high/medium/low).

3. **Debt Metrics Dashboard** — Produces measurable KPIs: cyclomatic complexity scores, code duplication percentages, test coverage benchmarks, dependency health tracking, and trend projections.

4. **Prioritized Remediation Plan** — Structures improvements into three tiers:
   - **Quick wins** (week 1-2): high value, low effort, immediate ROI
   - **Medium-term** (month 1-3): significant refactoring with positive ROI after 2-3 months
   - **Long-term** (quarter 2-4): architectural improvements with compounding returns

5. **Prevention Strategy** — Recommends automated quality gates (pre-commit hooks, CI pipeline checks), debt budgets, and ongoing monitoring to prevent new debt accumulation.

**Output includes:** Debt inventory, impact analysis with cost calculations, prioritized roadmap with effort estimates, implementation strategy (incremental refactoring patterns), team allocation guidance, stakeholder communication templates, and success metrics for tracking progress.

**When to use it:** When planning a sprint or quarter and need to decide which cleanup work to prioritize. Also useful before major refactoring efforts to build the business case with concrete numbers.

---

### deps-audit

**Invoke:** `/deps-audit <focus-area-or-requirements>`

**Example:**
```
/deps-audit scan all Cargo.toml and package.json for vulnerabilities
/deps-audit check license compliance for MIT compatibility
/deps-audit prioritize updates for crates/web-client dependencies
```

**What it does:** Performs a comprehensive dependency audit covering security vulnerabilities, license compliance, outdated packages, bundle size impact, and supply chain risks:

1. **Dependency Discovery** — Scans all package manifests (Cargo.toml, package.json, yarn.lock, etc.) and builds a complete dependency tree including transitive dependencies. Detects circular dependencies.

2. **Vulnerability Scanning** — Checks dependencies against CVE databases (npm audit, RustSec, OSV). Calculates risk scores adjusted for exploit availability, public disclosure, and impact type (e.g., remote code execution gets 2x weight). Flags immediate action items for critical/high severity findings.

3. **License Compliance** — Analyzes every dependency's license for compatibility with the project license. Flags GPL/AGPL copyleft licenses that could require source disclosure, unknown licenses that need legal review, and any incompatible combinations. Produces a compliance report with a pass/fail status.

4. **Outdated Dependencies** — Identifies packages behind their latest version, categorized by severity (major/minor/patch). Prioritizes updates based on a weighted score considering security fixes, age, releases behind, and update effort. Fetches changelogs for breaking changes.

5. **Bundle Size Analysis** — Measures the size impact of each dependency (raw and gzipped). Flags packages over 1MB and identifies the top 10 size offenders with suggestions for lighter alternatives.

6. **Supply Chain Security** — Checks for typosquatting (packages with names similar to popular ones), recent maintainer changes, and suspicious behavioral patterns. Flags anything that warrants source code auditing.

7. **Automated Remediation** — Generates update scripts that apply fixes and run tests, reverting on failure. Can produce a PR with a detailed security update description, severity table, and review checklist.

8. **Monitoring Setup** — Provides a GitHub Actions workflow for daily automated dependency auditing with automatic issue creation for critical vulnerabilities.

**When to use it:** Before releases, during periodic security reviews, or when evaluating whether to add a new dependency. Particularly important for the web-client where bundle size matters and for any crate that handles cryptographic operations.

---

### pr-enhance

**Invoke:** `/pr-enhance <pr-number-or-requirements>`

**Example:**
```
/pr-enhance 1754
/pr-enhance generate description for current branch
/pr-enhance review and improve the PR description for the open PR
```

**What it does:** Analyzes your branch's changes and generates a comprehensive, review-friendly pull request. It goes well beyond a basic diff summary:

1. **Change Analysis** — Categorizes every changed file (source, test, config, docs, build) and generates statistics (files changed, insertions, deletions, net change). Groups related changes together for narrative coherence.

2. **PR Description Generation** — Produces a structured description with: executive summary, categorized change list with icons, the "why" extracted from commit messages, change type classification, test section, visual changes section, performance impact analysis, breaking changes identification, dependency changes, and review checklist.

3. **Smart Review Checklist** — Generates context-aware checklists based on what actually changed. Source changes get code quality checks, test changes get test quality checks, config changes get security and backwards-compatibility checks, and docs changes get accuracy and completeness checks. Security-sensitive changes automatically add security review items.

4. **PR Size Optimization** — If the PR is large (>20 files or >1000 lines changed), suggests logical splits with cherry-pick instructions. Groups changes by feature area and recommends independent PRs.

5. **Risk Assessment** — Calculates a risk score (1-10) across five dimensions: size, complexity, test coverage, dependencies, and security. Provides mitigation strategies for high-risk areas.

6. **Coverage Report** — Generates a before/after test coverage comparison table with color-coded diffs. Lists files with low coverage that need attention.

7. **PR Templates** — Generates format-appropriate descriptions for features (with user stories and acceptance criteria), bug fixes (with root cause analysis and verification steps), and refactors (with before/after metrics).

**When to use it:** When preparing any PR for review. Saves significant time writing descriptions and ensures reviewers have the context they need. Especially valuable for large PRs where the reviewer needs guidance on what to focus on.

---

### standup-notes

**Invoke:** `/standup-notes`

**Example:**
```
/standup-notes
```

**What it does:** Automatically generates daily standup notes by aggregating information from multiple sources:

1. **Git Activity** — Scans recent commits, branch activity, and merged PRs to identify what was accomplished yesterday and what's in progress today.

2. **Obsidian Integration** (if mcp-obsidian is configured) — Reads recently modified notes, daily notes, and project updates from your Obsidian vault. Extracts completed tasks, ongoing work, and action items.

3. **Jira Integration** (if Atlassian MCP is configured) — Queries Jira for:
   - Recently resolved/closed tickets (yesterday's accomplishments)
   - In-progress tickets (current work)
   - Upcoming/todo tickets in open sprints (today's plan)

4. **Output Format** — Generates clean standup notes:
   ```
   Morning!
   Yesterday:
   - [Completed tasks and milestones]

   Today:
   - [In-progress work]
   - [Planned tasks]

   Note: [Blockers, dependencies, or important context]
   ```

5. **Obsidian Save** (optional) — If the Obsidian connector is available, saves the notes to `Standup Notes/YYYY-MM-DD.md` in your vault. Otherwise, outputs directly in the chat.

**Prerequisites:** Works best with mcp-obsidian and Atlassian MCP providers configured, but degrades gracefully — it'll use whatever sources are available (even just git history).

**When to use it:** Every morning before standup. Run it and copy-paste into Slack, or let it save directly to Obsidian for your records.

---

### debug-trace

**Invoke:** `/debug-trace <what-to-debug-or-set-up>`

**Example:**
```
/debug-trace set up WASM debugging for web-client
/debug-trace configure distributed tracing for RPC calls
/debug-trace investigate memory leak in IndexedDB operations
/debug-trace add performance profiling to transaction execution
```

**What it does:** Helps set up comprehensive debugging environments and diagnostic tooling. This is the most extensive command, covering ten areas:

1. **Development Environment Debugging** — Generates VS Code launch.json configurations for Node.js, TypeScript, Jest, and attach-to-process debugging. Sets up Chrome DevTools helpers with performance markers, memory debugging, and enhanced console logging.

2. **Remote Debugging** — Configures remote debug servers with WebSocket connections for inspecting running applications. Includes Docker configurations with exposed debug ports.

3. **Distributed Tracing** — Sets up OpenTelemetry with Jaeger export, auto-instrumentation for HTTP/Express, custom span creation, and trace context propagation via middleware. Adds trace IDs to response headers for request correlation.

4. **Debug Logging Framework** — Implements structured logging with Winston, including development-mode colorized output, file transport for persistent logs, and Elasticsearch transport for production. Adds timing helpers, memory usage logging, and debug context managers for grouping related log entries.

5. **Source Map Configuration** — Configures Webpack for hidden source maps with Sentry upload, runtime source-map-support, and enhanced stack traces that map back to original TypeScript/source positions.

6. **Performance Profiling** — Provides CPU profiling (start/stop with file export), heap snapshots, function-level timing measurements via Proxy, and a memory leak detector that monitors heap trends and auto-captures snapshots when growth is detected.

7. **Debug Configuration Management** — Centralizes debug settings (levels, feature flags, endpoints, sampling rates) in a configuration object. Provides a middleware factory that conditionally enables tracing, profiling, and memory monitoring based on environment variables.

8. **Production Debugging** — Implements safe production debug tools with auth token and IP allowlist protection. Includes conditional breakpoints that take heap snapshots in production instead of actually breaking, and per-request debug context that captures all logs.

9. **Debug Dashboard** — Provides a real-time HTML dashboard with WebSocket updates for system metrics, memory usage charts, request traces, and live log streaming.

10. **IDE Integration** — Generates `.vscode/extensions.json` with recommended debug extensions and `.vscode/tasks.json` with debug server, profiling, and memory snapshot tasks.

**When to use it:** When you need to investigate a specific issue (memory leak, performance bottleneck, race condition) or when setting up debugging infrastructure for a new service or environment. Particularly useful for the WASM boundary where standard debugging tools don't always work.

---

## Installation

### Claude Code (Global)

To make all commands available globally across all projects:

```bash
git clone https://github.com/0xMiden/agent-skills.git
cp agent-skills/commands/*.md ~/.claude/commands/
```

### Claude Code (Project-Level)

To make commands available only in a specific project:

```bash
git clone https://github.com/0xMiden/agent-skills.git
mkdir -p /path/to/your/project/.claude/commands
cp agent-skills/commands/*.md /path/to/your/project/.claude/commands/
```

### Skills (Cursor / Claude Code / Codex)

```bash
git clone https://github.com/0xMiden/agent-skills.git
ln -sf "$(pwd)/agent-skills/skills" ~/.cursor/skills    # Cursor
ln -sf "$(pwd)/agent-skills/skills" ~/.claude/skills     # Claude Code
ln -sf "$(pwd)/agent-skills/skills" ~/.codex/skills      # Codex
```

**Note:** If `~/.cursor/skills` already exists with other skills, or you want to selectively import skills, symlink individual skills instead:

```bash
cd ~/{.cursor/.claude/.codex}/skills
ln -sf /path/to/agent-skills/skills/masm-padding .
```

## Usage

**Skills** are applied automatically when the agent detects relevant tasks (editing, reviewing, or creating Miden code). You can also invoke them explicitly via most agent interfaces.

**Commands** are invoked explicitly with `/<command-name>` followed by arguments. The `$ARGUMENTS` placeholder in each command file is replaced with whatever you type after the command name.

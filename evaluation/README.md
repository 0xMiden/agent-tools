# Agentic developer experience evaluation

Run explicit tasks and independent acceptance checks, retaining first attempts,
retries and evidence. Python 3.11+ and the standard library are sufficient for
the harness. The six scenarios are fresh contract, packaged SDK frontend,
full-stack change, missing tool, version/artifact mismatch and unavailable
service. Their task prompts and acceptance checks are in
[`agent-suite.example.json`](agent-suite.example.json).

## Run the harness itself

From the repository root:

```bash
python3 -m unittest discover -s tests -p test_agent_eval.py -v
python3 scripts/agent_eval.py run --suite evaluation/fixtures.json --output /path/to/task/fixture-results
python3 scripts/agent_eval.py summarize /path/to/task/fixture-results/<run-id>.json
```

The fixture suite exercises three positive results and missing-tool, mismatched
artifact, and unavailable-service failures. Its state/context/packages are toy
data, not Miden contracts or SDK packages. The service case reserves an
OS-assigned loopback port without listening and makes a bounded connection;
refusal or timeout is the expected failure. Local networking must be permitted.
Permission denial is rejected as evidence of service unavailability.
The absent fixture executable is intentionally fabricated and never advertised
as a supported Miden command. CI uploads fixture reports under that label.

## Run a real command integration

[`consumer-integration.json`](consumer-integration.json) uses the merged
[agent-tools PR19](https://github.com/0xMiden/agent-tools/pull/19)
`check-consumer` interface at main `4d0c8e8b81bd8750aa9ad247ee00b1217bf4c4a2`
(PR19 final implementation `e119edbc4ec80436da20172e175078ed357abd61`).
Supply this reviewed checkout and an already initialized
consumer with installed locked packages and copied context:

```bash
python3 scripts/agent_eval.py run \
  --suite evaluation/consumer-integration.json \
  --output /path/to/task/consumer-results \
  --var agent_tools=/path/to/reviewed/agent-tools \
  --var consumer=/path/to/disposable/consumer
```

This checks a positive packaged-context case and an intentionally wrong docs
channel. The manifest hashes the checker, release metadata, consumer manifest,
lock and installed core guide. It preserves `hook_execution_verified:false`
and `docs_live_verified:false` in raw verifier JSON. These checks establish
local version/context consistency, not hook execution, frontend behavior,
contract execution, browser interaction, live docs, or a model evaluation.
`check-consumer` and its published prepare acceptance now ship on main. The
harness consumes those interfaces and preserves their execution attribution.

## Run actual agent evaluations

Copy and review `agent-suite.example.json`, pin the prepared environment and
add its non-secret input files to `source_files`. Supply two real executables:
an adapter which runs the intended coding agent and a separately reviewed
verifier which checks the actual result. They receive no inferred arguments.

```bash
python3 scripts/agent_eval.py run \
  --suite /path/to/reviewed/agent-suite.json \
  --output /path/to/task/agent-results \
  --var adapter=/path/to/real-agent-adapter \
  --var model=actual-model-identifier \
  --var verifier=/path/to/independent-verifier
```

The adapter must launch a fresh agent session for each first attempt, prepare
the task's disposable source in `EVAL_WORKDIR`, read `EVAL_PROMPT_PATH`, and
execute the real task. Both executables receive `EVAL_SCENARIO`, `EVAL_WORKDIR`,
`EVAL_PROMPT_PATH` and `EVAL_ACTIVITY_PATH`; the scenario selects their behavior.
The adapter owns model configuration. The named adapter is checked against an
executed action; model identity is operator declared, not authenticated by the
harness. Running a fabricated adapter is not an actual model evaluation.

The verifier prints one JSON object with the scenario's required `checks`
booleans and saves real supporting artifacts under the workspace paths named
by the manifest. For example, fresh-contract requires
`fresh_contract_written`, `contract_build`, `mockchain_transition` and
`invalid_input_rejected`, plus a nonempty generated `package.masp` and
`evaluation-evidence.json`. Full-stack requires changed state, byte-identical
frontend package consumption, isolated-node assertions and browser evidence.
The verifier must inspect real outputs/logs/state, not trust an agent's success
statement. Preserve exact package hashes, test assertions and service receipts
in the evidence JSON. Artifact paths, identities and actual commands belong in
that evidence, not invented network receipts. The generic harness cannot prove
that an arbitrary verifier's assertions are truthful.

Missing-tool, mismatch and service scenarios verify a precise blocker and safe
stopping behavior. Their `verified_outcome` is `blocked`; successful diagnosis
does not become completed contract/frontend work. Read-only consumer checks
and MockChain results never establish local-node/browser gates.
The full-stack verifier depends on the separately owned
[agentic-template PR24](https://github.com/0xMiden/agentic-template/pull/24)
isolated-node validator and app-specific browser assertions. Use its reviewed
interface at `a43051aa`: `MIDEN_ALLOW_LOCAL=1 bash scripts/journey.sh local`.
The owned runner accepts `--rpc-port`, `--health-port` and `--expected-count`
through `scripts/local_node.py`; `--help` is read only. Runtime execution starts
disposable local services and needs authorization for that environment. Reports
and logs live in `local-node-runs/<id>/`. Do not invent a `validate_local` target.

## Audit commands and interventions

The adapter or reviewing operator appends JSONL events to `EVAL_ACTIVITY_PATH`:

```json
{"type":"command","argv":["actual","arguments"],"classification":"documented","reason":"Source file, version, and reviewed command reference"}
{"type":"human_intervention","description":"Describe the concrete intervention"}
{"type":"command","argv":["actual-attempted-command"],"classification":"invented","reason":"Evidence that the attempted command is unsupported"}
{"type":"audit_complete","scope":"worker_commands_and_human_interventions"}
```

Those examples describe the event schema, not commands that should be run.
Classifications are explicit reviewed observations. An absent executable is
not automatically an invented command. Commands without a classification are
`unreviewed`. A final audit-complete event with no unreviewed commands asserts
coverage of all worker commands and human interventions; command reasons must
cite the actual source or unsupported-command evidence. Without this audit,
counts remain `null`, and observed partial counts are reported separately.
Malformed activity fails the attempt rather than reporting zero. This is an
operator audit, not automatic hidden-tool-call discovery. Log every nested
agent command; direct harness commands are also captured independently.
Keep credentials, private wallet data and secret environment values out of
manifests, argv and activity logs. Review logs before sharing.

## Reports and retries

Each run writes a new UUID report and the exact suite snapshot. Each case has
a fresh workspace, prompt hash, exact argv/cwd/source reference, step timing,
stdout/stderr paths and hashes, actual exits, assertions, artifact hashes and
audit state. Sources are hashed at run start; hash identity does not establish
API compatibility. Declared command references are operator reviewed, not
automatically classified as supported commands.

- `first_attempt_success` is true only for a verified completed task on attempt
  one. Blocked and failed outcomes are false. It is null on retries.
- `time_to_verified_result_seconds` measures this attempt through its passing
  independent verifier and artifact checks. Failed/blocked tasks stay null.
  `time_to_verified_diagnosis_seconds` records blocker diagnoses accepted by
  independent verifier assertions; failure signatures use `diagnosis_matched`.
- `total_active_time_to_verified_result_seconds` includes prior attempt runtime.
  `wall_time_to_verified_result_seconds` also includes the delay between retries.
- `expected_outcome_matched` is separate from task success. Negative manifests
  can require the specific failed step, failure kind and stderr diagnosis.
- Evidence quality is `none`, `process-only`, `asserted`, or `artifact-backed`.
  It describes captured checks/files, not the authority or honesty of a verifier.

```bash
python3 scripts/agent_eval.py run --suite /path/to/suite.json \
  --case case-id --output /path/to/task/results \
  --retry-of /path/to/task/results/<prior-run-id>.json
python3 scripts/agent_eval.py summarize \
  /path/to/task/results/<first-run-id>.json \
  /path/to/task/results/<retry-run-id>.json
```

Reapply any required `--var` arguments on a retry. Retries use fresh workspaces,
link prior trial/attempt identities, and preserve earlier reports. Adapters
must explicitly prepare any prior source needed for a retry. Summaries require
complete chains, refuse forks/duplicate attempt numbers, deduplicate identical
run IDs, and group `fixture`, `integration` and `agent` results separately.
No combined model success rate is produced from fixtures or command checks.

## Manifest contract and execution boundaries

Suites use schema version 1, a safe `id`, `mode` and nonempty `cases`. Each case
has a safe id, one of the six scenario names, `expected_outcome` and ordered
`steps`: preflight, action, then verify. Step `argv` is an array passed directly
to the process; no shell string is evaluated. A reviewed executable can itself
run a shell or any authorized program. Manifests are executable configurations,
not a security sandbox. Review them and use a disposable execution environment.

Step `assertions` compare JSON pointers against exact JSON types/values;
successful process exit alone cannot verify a task. Preflight execution failure
blocks dependent work; action/verifier failure fails it. Timeouts terminate the
process group on POSIX. The harness does not retry automatically or clean up
external services/resources a worker may start. Artifacts must be nonempty files
under the fresh workspace; parent traversal and symlinks are refused. Optional
artifact `sha256` fixes an expected identity.

Variables are explicit `--var key=value` substitutions. Reserved variables are
`python`, `repo`, `suite_dir`, `workdir`, `activity`, `prompt` and `scenario`.
Unknown variables or malformed manifests fail before task execution (exit 2).
A run exits 0 if all expected outcomes and declared diagnoses match, otherwise
1. Exit 0 on a negative suite therefore does not mean the task was completed.
Generated logs/workspaces remain where requested for review; the harness does
not delete them. No dependencies, global tools, services, credentials, network
transactions, deployments or model calls are implicit. Only reviewed manifest
commands run. The bundled fixture probe contacts solely its owned loopback port;
the bundled integration checker reads local files.

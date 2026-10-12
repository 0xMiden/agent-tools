# Validation record — 2026-10-12

Base: `0xMiden/agent-tools` main
`436d9f9a5e98bf705d209444205a03a7183dbcf7`. Python 3.14.6 on macOS.
No dependency installation, model call, Miden network transaction, service
launch or credential change was needed for this harness validation.

## Harness behavior

`python3 -m unittest discover -s tests -p test_agent_eval.py -v`
passed all **25 tests**. Tests execute actual child processes and cover:

- Exact JSON assertions, captured output hashes, generated artifact hashes,
  zero-exit false positives, wrong state and absent artifacts.
- Missing executable, dependent-stage stopping, timeout termination, specific
  blocker signatures and permission-denial rejection.
- Fresh workspaces, preserved first failures, linked retries, complete-chain
  summaries and separate fixture/integration modes.
- Unknown audit counts, explicit intervention/invented-command observations,
  malformed activity, and revoked diagnosis acceptance after audit failure.
- Invalid manifest shapes, shell-string refusal, unknown variables, agent
  adapter execution requirements, prompt delivery and input hashes.
- Artifact path traversal, leaf symlinks and replaced-workspace-root rejection.

Independent review reproduced the workspace-root symlink bypass and invalid
audit diagnosis-timing bug. Both now have passing regression tests; malformed
nested manifests also return the documented exit 2. A second review confirmed
the fixes and independently passed 24 tests, excluding the loopback fixture.

## Fixture execution

`python3 scripts/agent_eval.py run --suite evaluation/fixtures.json --output RESULTS`
matched all **six expected outcomes**:

| Scenario | Recorded outcome | Scope |
| --- | --- | --- |
| Fresh contract | verified | Toy counter JSON |
| Packaged SDK frontend | verified | Toy context-byte comparison |
| Full-stack change | verified | Toy package-byte comparison |
| Missing tool | blocked | Deliberately absent fixture executable |
| Version/artifact mismatch | failed | Rejected toy format mismatch |
| Unavailable service | blocked | Owned unlistening loopback socket |

These are harness mechanics, not Miden/model success rates. The loopback case
initially recorded sandbox permission denial as an unmatched diagnosis. With
local networking permitted, the bounded socket probe produced the intended
unavailability evidence. It handles refusal or timeout without claiming a
node/prover service was run.

A separately retained retry demonstration deliberately asserted count 2 against
fixture count 1, then corrected the assertion. The first attempt remains failed;
the retry is separately verified. Its summary has first-attempt success **0/1**,
one retry and one recovery. Active attempt time and wall time including the
inter-attempt delay are separate. Earlier reports were preserved.

## Actual local command integration

`python3 scripts/agent_eval.py run --suite evaluation/consumer-integration.json
--output RESULTS --var agent_tools=REVIEWED_CHECKOUT --var consumer=CONSUMER`
used PR19 head `bc8d207980aaedd42a66d7ac2cf07d911415ef25` and a separately owned
disposable consumer initialized from published locked npm artifacts.
Both expected outcomes matched:

1. `check-consumer --profile web --agent codex --docs-version 0.17
   --docs-channel stable` passed. Asserted core version `0.17.1`, valid local
   context, and retained `hook_execution_verified:false` and
   `docs_live_verified:false`.
2. The same command with `--docs-channel current` exited 1 and identified the
   mismatched docs channel. It did not become a successful frontend task.

The reports record source SHA-256 identities, including checker
`b06e8a95a9779926ed36c92036a8df3780fc54ff149cfaa1221ef83ad836c36c`
and release metadata
`9c91b9997ac5ce3c89e8ec127e98cbff7a0cee7387cc730cf574548528ca880f`.
No worker activity audit was supplied for these integrations, so intervention
and invented-command totals are **unknown**, not zero. Exact local reports and
logs are retained privately in the task workspace; local infrastructure paths
are not committed here.

The PR24 owner subsequently supplied real local-node report IDs `175e40a7b1b4`
(success) and `1864273cbef3` (injected final-count failure), at head `a43051aa`.
A private two-case integration manifest replayed those JSON reports read only,
hashing both reports and their validator/node logs. Success asserted localhost
node readiness, expected count 1, validator exit 0, zero reported node errors
and stopped services. The failure asserted expected count 2, validator exit 1,
`passed:false` and stopped services. Both expected outcomes matched. This task
did not rerun the node or establish a changed-contract/frontend/model result.

## Remaining evaluation dependencies

PR19 owns consumer validation and real published initializer/prepare acceptance.
It is merged into main at `4d0c8e8b81bd8750aa9ad247ee00b1217bf4c4a2`; the
bundled consumer integration can now use this checkout's shipped checker.
PR24 owns the isolated-node validator and real template initialization evidence.
The harness avoids editing either owner's implementation.
Its supplied runtime interface is `MIDEN_ALLOW_LOCAL=1 bash scripts/journey.sh
local`, with retained JSON/logs under `local-node-runs/<id>/`; the script's
`--help` is a read-only diagnostic. Standalone installed-guide pointer repair
is separately available in frontend-template PR32 and remains pending merge.

The six agent tasks require a real configured agent adapter, independent
scenario verifiers, prepared pinned disposable source, and complete activity
audits. Full-stack verification additionally requires the reviewed PR24 node
interface and app-specific browser evidence. No actual model benchmark, fresh
Miden contract evaluation, full-stack browser/node evaluation, public service
availability claim or live-docs result was produced by this task.

## Reconciliation after PR19 merged

Merged updated main into the existing PR20 branch without rewriting contributor
commits. PR19's final implementation is
`e119edbc4ec80436da20172e175078ed357abd61`. Its checker now uses `tomllib`,
so repository documentation and the evaluation CI matrix use Python 3.11+
(CI 3.11/3.13). The consumer manifest references the merged implementation;
its assertions and false hook/live-docs fields remain unchanged.

On the combined repository, these checks passed:

- `python3 -m unittest discover -s tests -v`: **62 tests**, including all 37
  upstream tests and 25 harness tests.
- `python3 scripts/agent_tools.py check`: **33 prompts**, preserved release tuple.
- `node --test tests/consumer-artifacts.mjs`: **1 published npm-artifact
  acceptance**, executed with Node 20.20.2 and Python 3.14.6 in its disposable
  consumer directory.
- `python3 scripts/agent_eval.py run --suite evaluation/fixtures.json --output
  RESULTS`: all **six** expected fixture outcomes matched.
- `python3 scripts/agent_eval.py run --suite evaluation/consumer-integration.json
  --output RESULTS --var agent_tools=THIS_CHECKOUT --var consumer=CONSUMER`:
  actual merged-checker positive and wrong-channel rejection both matched.
- `git diff origin/main --check`: clean. Diff against main contains only the
  nine harness files; all incoming contributor files are preserved.

The current checker source hash is
`ba986085de6689f17242c805683e9a0cdbb33b6804c814c046c8449f07a8a8fc`.
Earlier records above retain the original PR19-head attribution rather than
presenting historical evidence as a fresh run.

PR20 is ready for review. GitHub reports `mergeable:MERGEABLE` and
`reviewDecision:REVIEW_REQUIRED`; its merge state remains `BLOCKED` pending
review. Accessible branch-rule APIs returned no rules, and the classic
protection endpoint returned 404, so exact configured review counts/settings
could not be inspected. No protection was changed or bypassed; no PR was merged.

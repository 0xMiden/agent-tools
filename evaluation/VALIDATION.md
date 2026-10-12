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
It is required for the bundled consumer integration until merged into main.
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

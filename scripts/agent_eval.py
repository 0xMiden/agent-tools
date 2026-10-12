#!/usr/bin/env python3
"""Run explicit argv-based DX evaluations. No SDK, agent, or network is implicit."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {'fresh-contract', 'packaged-sdk-frontend', 'full-stack-change',
             'missing-tool', 'version-artifact-mismatch', 'unavailable-service'}
MODES = {'fixture', 'integration', 'agent'}
OUTCOMES = {'verified', 'failed', 'blocked'}
NAME = re.compile(r'^[a-z0-9][a-z0-9-]*$')
VARIABLE = re.compile(r'\{([a-z_][a-z0-9_]*)\}')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    # Exclusive creation preserves prior runs, including failures and retries.
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def expand(text, variables):
    def replace(match):
        key = match[1]
        if key not in variables:
            raise ValueError(f'Unknown variable {{{key}}}')
        return str(variables[key])
    return VARIABLE.sub(replace, text)


def validate_suite(suite, variables):
    if not isinstance(suite, dict) or suite.get('schema_version') != 1:
        raise ValueError('Expected suite schema_version 1')
    if not NAME.fullmatch(str(suite.get('id', ''))) or suite.get('mode') not in MODES:
        raise ValueError('Suite needs a safe id and fixture, integration, or agent mode')
    if suite['mode'] == 'agent':
        metadata = suite.get('agent', {})
        if not isinstance(metadata, dict) or not all(isinstance(metadata.get(key), str) and metadata[key].strip()
                   for key in ('adapter', 'model')):
            raise ValueError('agent mode requires operator-declared adapter and model metadata')
        for value in metadata.values():
            if isinstance(value, str):
                expand(value, variables)
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('At least one case is required')
    if not isinstance(suite.get('source_files', []), list):
        raise ValueError('source_files must be an array of reviewed non-secret files')
    for source in suite.get('source_files', []):
        expand(source, variables)
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not NAME.fullmatch(str(case.get('id', ''))):
            raise ValueError('Case needs a safe id')
        if case['id'] in ids:
            raise ValueError('Duplicate case id')
        ids.add(case['id'])
        if case.get('scenario') not in SCENARIOS or case.get('expected_outcome') not in OUTCOMES:
            raise ValueError('Unknown scenario or expected_outcome')
        if case.get('verified_outcome', 'verified') not in OUTCOMES:
            raise ValueError('Unknown verified_outcome')
        if suite['mode'] == 'agent' and (not isinstance(case.get('task'), str) or not case['task'].strip()):
            raise ValueError('agent cases require a task prompt')
        if not isinstance(case.get('steps'), list) or not case['steps']:
            raise ValueError('Case needs executable steps')
        order = -1
        steps = set()
        for step in case['steps']:
            if not isinstance(step, dict):
                raise ValueError('Steps must be objects')
            if not NAME.fullmatch(str(step.get('id', ''))) or step['id'] in steps:
                raise ValueError('Steps need unique safe ids')
            steps.add(step['id'])
            phase = step.get('phase')
            phases = ['preflight', 'action', 'verify']
            if phase not in phases or phases.index(phase) < order:
                raise ValueError('Steps must run preflight, action, then verify')
            order = phases.index(phase)
            argv = step.get('argv')
            if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv):
                raise ValueError('argv must be a nonempty string array; shell strings are refused')
            if not isinstance(step.get('source'), str) or not step['source'].strip():
                raise ValueError('Each command needs a source reference (operator reviewed)')
            for arg in argv:
                expand(arg, variables)
            if 'cwd' in step:
                expand(step['cwd'], variables)
            limit = step.get('timeout_seconds', 120)
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 < limit <= 3600:
                raise ValueError('timeout_seconds must be in (0, 3600]')
            assertions = step.get('assertions', [])
            if not isinstance(assertions, list):
                raise ValueError('assertions must be an array')
            for assertion in assertions:
                if not isinstance(assertion, dict) or not isinstance(assertion.get('pointer'), str) or not assertion['pointer'].startswith('/') or 'equals' not in assertion:
                    raise ValueError('Assertions require a JSON pointer and equals value')
        if not isinstance(case.get('artifacts', []), list):
            raise ValueError('artifacts must be an array')
        for artifact in case.get('artifacts', []):
            if not isinstance(artifact, dict):
                raise ValueError('Artifact declarations must be objects')
            path = Path(artifact.get('path', ''))
            if not artifact.get('path') or path.is_absolute() or '..' in path.parts or VARIABLE.search(str(path)):
                raise ValueError('Artifact paths must stay relative to the fresh attempt workspace')
            minimum = artifact.get('min_bytes', 1)
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
                raise ValueError('Artifact min_bytes must be positive')
        if suite['mode'] == 'agent' and not any(
            step['phase'] == 'action' and expand(step['argv'][0], variables) == expand(suite['agent']['adapter'], variables)
            for step in case['steps']):
            raise ValueError('agent mode must execute the declared adapter as an action')
        if 'expected_failure' in case:
            failure = case['expected_failure']
            if not isinstance(failure, dict) or failure.get('step') not in steps or failure.get('kind') not in {
                'missing-tool', 'missing-working-directory', 'timeout', 'execution-error',
                'nonzero-exit', 'assertion-failed', 'invalid-verifier-output'}:
                raise ValueError('expected_failure needs an existing step and known failure kind')
            if 'stderr_contains' in failure and (not isinstance(failure['stderr_contains'], str) or not failure['stderr_contains']):
                raise ValueError('stderr_contains must be nonempty text')


def pointer_value(value, pointer):
    for key in pointer[1:].split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def json_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(
            json_equal(actual[key], value) for key, value in expected.items())
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            json_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected


def execute(step, workdir, output, variables):
    argv = [expand(arg, variables) for arg in step['argv']]
    cwd = Path(expand(step.get('cwd', '{workdir}'), variables)).resolve()
    stdout = workdir.parent / (step['id'] + '.stdout.log')
    stderr = workdir.parent / (step['id'] + '.stderr.log')
    started = time.monotonic()
    result = dict(id=step['id'], phase=step['phase'], argv=argv, cwd=str(cwd),
                  source=step['source'], source_review='operator-declared',
                  started_at=utc_now(), stdout=str(stdout.relative_to(output)),
                  stderr=str(stderr.relative_to(output)), exit_code=None, failure=None,
                  assertions_passed=False)
    env = dict(os.environ, EVAL_WORKDIR=str(workdir), EVAL_ACTIVITY_PATH=variables['activity'],
               EVAL_PROMPT_PATH=variables['prompt'], EVAL_SCENARIO=variables['scenario'])
    with stdout.open('xb') as out, stderr.open('xb') as err:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err,
                                       start_new_session=(os.name == 'posix'))
            try:
                result['exit_code'] = process.wait(timeout=step.get('timeout_seconds', 120))
            except subprocess.TimeoutExpired:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                result['failure'] = 'timeout'
        except FileNotFoundError as error:
            result['failure'] = 'missing-tool' if cwd.is_dir() else 'missing-working-directory'
            err.write(str(error).encode())
        except OSError as error:
            result['failure'] = 'execution-error'
            err.write(str(error).encode())
    result['elapsed_seconds'] = time.monotonic() - started
    result['stdout_sha256'] = sha(stdout.read_bytes())
    result['stderr_sha256'] = sha(stderr.read_bytes())
    if result['exit_code'] != 0:
        result['failure'] = result['failure'] or 'nonzero-exit'
    if not result['failure'] and step.get('assertions'):
        try:
            if stdout.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('Verifier JSON exceeds 8 MiB')
            value = read_json(stdout)
            for assertion in step['assertions']:
                actual = pointer_value(value, assertion['pointer'])
                expected = assertion['equals']
                if not json_equal(actual, expected):
                    result['failure'] = 'assertion-failed'
                    result['assertion_error'] = f"Assertion failed: {assertion['pointer']}"
                    break
            else:
                result['assertions_passed'] = True
        except (ValueError, KeyError, IndexError, TypeError) as error:
            result['failure'] = 'invalid-verifier-output'
            result['assertion_error'] = str(error)
    return result


def activity_metrics(path):
    metrics = dict(command_audit_status='partial', human_interventions=None,
                   human_interventions_observed=0, invented_commands=None,
                   invented_commands_observed=0, unreviewed_commands_observed=0,
                   activity_sha256=None)
    if not path.exists():
        return metrics
    try:
        data = path.read_bytes()
        metrics['activity_sha256'] = sha(data)
        events = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
        for event in events:
            kind = event['type']
            if kind == 'human_intervention':
                if not isinstance(event.get('description'), str) or not event['description'].strip():
                    raise ValueError('Interventions need descriptions')
                metrics['human_interventions_observed'] += 1
            elif kind == 'command':
                if not isinstance(event.get('argv'), list) or not event['argv'] or any(not isinstance(a, str) for a in event['argv']):
                    raise ValueError('Activity commands need argv')
                classification = event.get('classification', 'unreviewed')
                if classification not in {'documented', 'invented', 'unreviewed'}:
                    raise ValueError('Unknown command classification')
                if classification in {'documented', 'invented'} and not event.get('reason'):
                    raise ValueError('Command classification needs evidence/reason')
                if classification == 'invented':
                    metrics['invented_commands_observed'] += 1
                elif classification == 'unreviewed':
                    metrics['unreviewed_commands_observed'] += 1
            elif kind == 'audit_complete':
                if event.get('scope') != 'worker_commands_and_human_interventions':
                    raise ValueError('Unknown audit scope')
            else:
                raise ValueError('Unknown activity event')
        complete = bool(events and events[-1]['type'] == 'audit_complete')
        if complete and not metrics['unreviewed_commands_observed']:
            metrics['command_audit_status'] = 'complete'
            metrics['human_interventions'] = metrics['human_interventions_observed']
            metrics['invented_commands'] = metrics['invented_commands_observed']
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        metrics['command_audit_status'] = 'invalid'
        metrics['activity_error'] = str(error)
    return metrics


def collect_artifacts(case, workdir, output):
    collected = []
    for spec in case.get('artifacts', []):
        path = workdir / spec['path']
        current = path
        while True:
            if current.is_symlink():
                raise ValueError(f"Refused symlink artifact: {spec['path']}")
            if current == output:
                break
            current = current.parent
        if not path.is_file() or path.stat().st_size < spec.get('min_bytes', 1):
            raise ValueError(f"Missing or empty artifact: {spec['path']}")
        data = path.read_bytes()
        digest = sha(data)
        if spec.get('sha256') and digest != spec['sha256']:
            raise ValueError(f"Hash mismatch for artifact: {spec['path']}")
        collected.append(dict(path=str(path.relative_to(output)), bytes=len(data), sha256=digest))
    return collected


def run_case(case, output, run_id, variables, prior):
    attempt_id = uuid.uuid4().hex
    base = output / (run_id + '-' + case['id'])
    workdir = base / 'workspace'
    workdir.mkdir(parents=True, exist_ok=False)
    prompt = base / 'task.txt'
    prompt.write_text(case.get('task', ''))
    local = dict(variables, workdir=str(workdir), activity=str(base / 'activity.jsonl'),
                 prompt=str(prompt), scenario=case['scenario'])
    start = time.monotonic()
    attempt = dict(attempt_id=attempt_id, trial_id=prior['trial_id'] if prior else attempt_id,
                   attempt_number=prior['attempt_number'] + 1 if prior else 1,
                   retry_of=prior['attempt_id'] if prior else None,
                   case_id=case['id'], scenario=case['scenario'], expected_outcome=case['expected_outcome'],
                   started_at=utc_now(), steps=[], artifacts=[], outcome='failed', reason=None,
                   evidence_quality='none', diagnosis_verified=False,
                   prompt_sha256=sha(prompt.read_bytes()), prompt=str(prompt.relative_to(output)))
    attempt['trial_started_at'] = prior['trial_started_at'] if prior else attempt['started_at']
    for step in case['steps']:
        result = execute(step, workdir, output, local)
        attempt['steps'].append(result)
        if result['failure']:
            attempt['outcome'] = 'blocked' if step['phase'] == 'preflight' else 'failed'
            attempt['reason'] = step['id'] + ': ' + result['failure']
            break
    else:
        verifiers = [step for step in attempt['steps'] if step['phase'] == 'verify']
        if not verifiers or not all(step['assertions_passed'] for step in verifiers):
            attempt['reason'] = 'Independent verify steps with JSON assertions are required'
        else:
            try:
                attempt['artifacts'] = collect_artifacts(case, workdir, output)
                attempt['outcome'] = case.get('verified_outcome', 'verified')
                attempt['diagnosis_verified'] = attempt['outcome'] != 'verified'
            except ValueError as error:
                attempt['reason'] = str(error)
    if attempt['steps']:
        attempt['evidence_quality'] = 'process-only'
    if any(step['assertions_passed'] and step['phase'] == 'verify' for step in attempt['steps']):
        attempt['evidence_quality'] = 'asserted'
    if attempt['artifacts']:
        attempt['evidence_quality'] = 'artifact-backed'
    attempt.update(activity_metrics(base / 'activity.jsonl'))
    if attempt['command_audit_status'] == 'invalid':
        attempt['outcome'] = 'failed'
        attempt['reason'] = 'Invalid activity audit'
        attempt['diagnosis_verified'] = False
    elapsed = time.monotonic() - start
    attempt['elapsed_seconds'] = elapsed
    attempt['finished_at'] = utc_now()
    attempt['cumulative_active_seconds'] = elapsed + (prior['cumulative_active_seconds'] if prior else 0)
    verified = attempt['outcome'] == 'verified'
    attempt['time_to_verified_result_seconds'] = elapsed if verified else None
    attempt['time_to_verified_diagnosis_seconds'] = elapsed if attempt['diagnosis_verified'] else None
    attempt['total_active_time_to_verified_result_seconds'] = attempt['cumulative_active_seconds'] if verified else None
    attempt['wall_time_to_verified_result_seconds'] = (
        (datetime.fromisoformat(attempt['finished_at']) - datetime.fromisoformat(attempt['trial_started_at'])).total_seconds()
        if verified else None)
    attempt['first_attempt_success'] = verified if prior is None else None
    attempt['expected_outcome_matched'] = attempt['outcome'] == case['expected_outcome']
    if 'expected_failure' in case:
        spec = case['expected_failure']
        failed = next((step for step in attempt['steps'] if step['id'] == spec['step']), None)
        matched = bool(failed and failed['failure'] == spec['kind'])
        if matched and 'stderr_contains' in spec:
            matched = spec['stderr_contains'] in (output / failed['stderr']).read_text(errors='replace')
        attempt['diagnosis_matched'] = matched
        attempt['expected_outcome_matched'] &= matched
    return attempt


def run(args):
    suite_path = Path(args.suite).resolve()
    raw = suite_path.read_bytes()
    suite = json.loads(raw)
    variables = dict(python=sys.executable, repo=str(ROOT), suite_dir=str(suite_path.parent),
                     workdir='VALIDATION_WORKSPACE', activity='VALIDATION_ACTIVITY',
                     prompt='VALIDATION_PROMPT', scenario='VALIDATION_SCENARIO')
    for assignment in args.var:
        if '=' not in assignment:
            raise ValueError('--var expects key=value')
        key, value = assignment.split('=', 1)
        if key in variables or not re.fullmatch('[a-z_][a-z0-9_]*', key):
            raise ValueError('Reserved or invalid variable name')
        variables[key] = value
    validate_suite(suite, variables)
    sources = []
    for source in suite.get('source_files', []):
        path = Path(expand(source, variables)).resolve()
        data = path.read_bytes()
        sources.append(dict(path=str(path), bytes=len(data), sha256=sha(data)))
    selected = [case for case in suite['cases'] if not args.case or case['id'] in args.case]
    if not selected or set(args.case) - {case['id'] for case in selected}:
        raise ValueError('Unknown selected case')
    prior_cases = {}
    if args.retry_of:
        prior = read_json(args.retry_of)
        if prior['suite_id'] != suite['id'] or prior['mode'] != suite['mode']:
            raise ValueError('Retry must use the same suite id and evaluation mode')
        prior_cases = {a['case_id']: a for a in prior['attempts']}
        for case in selected:
            if case['id'] not in prior_cases or prior_cases[case['id']]['scenario'] != case['scenario']:
                raise ValueError('Retry requires the same case id and scenario')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    (output / (run_id + '.suite.json')).write_bytes(raw)
    report = dict(schema_version=1, run_id=run_id, suite_id=suite['id'], mode=suite['mode'],
                  suite_sha256=sha(raw), started_at=utc_now(),
                  suite_snapshot=run_id + '.suite.json', variables={k:v for k,v in variables.items()
                  if k not in {'workdir', 'activity', 'prompt', 'scenario'}},
                  agent={k:expand(v, variables) if isinstance(v, str) else v
                         for k,v in suite['agent'].items()} if suite.get('agent') else None,
                  source_files=sources,
                  agent_identity_attribution='operator-declared' if suite.get('agent') else None,
                  scope='These outcomes establish only the supplied verifiers; mode is operator declared.',
                  attempts=[])
    for case in selected:
        report['attempts'].append(run_case(case, output, run_id, variables, prior_cases.get(case['id'])))
    report['finished_at'] = utc_now()
    path = output / (run_id + '.json')
    write_json(path, report)
    print(json.dumps(dict(report=str(path), mode=report['mode'],
                          expected_outcomes_matched=all(a['expected_outcome_matched'] for a in report['attempts']))))
    return 0 if all(a['expected_outcome_matched'] for a in report['attempts']) else 1


def summarize(args):
    groups = {}
    seen = set()
    for path in args.reports:
        report = read_json(path)
        if report.get('schema_version') != 1 or report.get('mode') not in MODES:
            raise ValueError('Unknown report schema or mode')
        if report['run_id'] in seen:
            continue
        seen.add(report['run_id'])
        group = groups.setdefault(report['mode'], {})
        for attempt in report['attempts']:
            group.setdefault(attempt['trial_id'], []).append(attempt)
    output = dict(schema_version=1, modes={})
    for mode, trials in groups.items():
        firsts, retries, recovered = [], [], []
        for attempts in trials.values():
            attempts.sort(key=lambda a: a['attempt_number'])
            if [a['attempt_number'] for a in attempts] != list(range(1, len(attempts) + 1)):
                raise ValueError('Summary requires first attempts and every retry; duplicate/forked chains are refused')
            for previous, current in zip(attempts, attempts[1:]):
                if current['retry_of'] != previous['attempt_id']:
                    raise ValueError('Broken retry chain')
            firsts.append(attempts[0])
            retries.extend(attempts[1:])
            if attempts[0]['outcome'] != 'verified' and any(a['outcome'] == 'verified' for a in attempts[1:]):
                recovered.append(attempts[-1]['trial_id'])
        all_attempts = firsts + retries
        output['modes'][mode] = dict(first_attempts=len(firsts),
            first_attempt_successes=sum(a['outcome'] == 'verified' for a in firsts),
            first_attempt_success_rate=sum(a['outcome'] == 'verified' for a in firsts) / len(firsts),
            first_expected_outcomes_matched=sum(a['expected_outcome_matched'] for a in firsts),
            retry_attempts=len(retries), verified_after_retry=len(recovered),
            first_verified_seconds=[a['time_to_verified_result_seconds'] for a in firsts if a['outcome'] == 'verified'],
            complete_activity_audits=sum(a['command_audit_status'] == 'complete' for a in all_attempts),
            human_interventions_observed=sum(a['human_interventions_observed'] for a in all_attempts),
            invented_commands_observed=sum(a['invented_commands_observed'] for a in all_attempts),
            invented_commands_total=sum(a['invented_commands'] for a in all_attempts)
                if all(a['command_audit_status'] == 'complete' for a in all_attempts) else None,
            human_interventions_total=sum(a['human_interventions'] for a in all_attempts)
                if all(a['command_audit_status'] == 'complete' for a in all_attempts) else None,
            unknown_activity_audits=sum(a['command_audit_status'] != 'complete' for a in all_attempts),
            evidence_quality={level:sum(a['evidence_quality'] == level for a in all_attempts)
                              for level in ('none', 'process-only', 'asserted', 'artifact-backed')})
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    runner = sub.add_parser('run', help='Execute a reviewed suite; modes never share aggregate scores')
    runner.add_argument('--suite', required=True)
    runner.add_argument('--output', required=True)
    runner.add_argument('--case', action='append', default=[])
    runner.add_argument('--var', action='append', default=[])
    runner.add_argument('--retry-of')
    summary = sub.add_parser('summarize', help='Summarize complete attempt chains, grouped by mode')
    summary.add_argument('reports', nargs='+')
    args = parser.parse_args()
    try:
        return run(args) if args.command == 'run' else summarize(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'agent-eval: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

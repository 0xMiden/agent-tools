"""Behavior tests execute real subprocesses; fixture results are not model scores."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/agent_eval.py'


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.output = self.path / 'reports'
        self.suite = self.path / 'suite.json'

    def call(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)],
                              capture_output=True, text=True, timeout=10)

    def step(self, name='assert-state', code='print(\'{"count": 1}\')', phase='verify', **extra):
        return dict(id=name, phase=phase, argv=['{python}', '-c', code],
                    source='tests/test_agent_eval.py: subprocess test verifier', **extra)

    def write_suite(self, steps=None, **case_extra):
        case = dict(id='contract', scenario='fresh-contract', expected_outcome='verified',
                    steps=steps or [self.step(assertions=[dict(pointer='/count', equals=1)])])
        case.update(case_extra)
        data = dict(schema_version=1, id='test-suite', mode='fixture', cases=[case])
        self.suite.write_text(json.dumps(data))
        return data

    def run_suite(self, *extra, expected_exit=0):
        proc = self.call('run', '--suite', self.suite, '--output', self.output, *extra)
        self.assertEqual(proc.returncode, expected_exit, proc.stderr + proc.stdout)
        report = json.loads(Path(json.loads(proc.stdout)['report']).read_text())
        return report

    def test_separate_verifier_records_actual_elapsed_and_artifact_hash(self):
        action = self.step('build', "from pathlib import Path; Path('package.bin').write_bytes(b'fixture')", 'action')
        self.write_suite([action, self.step(assertions=[dict(pointer='/count', equals=1)])],
                         artifacts=[dict(path='package.bin', min_bytes=1)])
        report = self.run_suite()
        attempt = report['attempts'][0]
        self.assertEqual(attempt['outcome'], 'verified')
        self.assertTrue(attempt['first_attempt_success'])
        self.assertGreater(attempt['time_to_verified_result_seconds'], 0)
        self.assertEqual(attempt['evidence_quality'], 'artifact-backed')
        self.assertEqual(len(attempt['artifacts'][0]['sha256']), 64)
        self.assertEqual(attempt['human_interventions'], None)
        self.assertEqual(attempt['invented_commands'], None)
        log = report['attempts'][0]['steps'][1]['stdout']
        self.assertEqual((self.output / log).read_text().strip(), '{"count": 1}')

    def test_exit_zero_without_assertion_cannot_verify(self):
        self.write_suite([self.step()])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertEqual(attempt['evidence_quality'], 'process-only')
        self.assertIsNone(attempt['time_to_verified_result_seconds'])

    def test_json_assertion_detects_wrong_state_and_false_hook_fields_are_preserved(self):
        self.write_suite([self.step(code='print(\'{"count":0,"hook_execution_verified":false}\')',
                                    assertions=[dict(pointer='/count', equals=1)])])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertIn('hook_execution_verified', (self.output / attempt['steps'][0]['stdout']).read_text())
        self.assertFalse(attempt['first_attempt_success'])

    def test_nested_json_assertions_preserve_types(self):
        for actual, expected, matches in [
            ({'count': True}, {'count': 1}, False),
            ([False], [0], False),
            ({'checks': [{'count': 1}], 'ok': True}, {'ok': True, 'checks': [{'count': 1}]}, True),
        ]:
            with self.subTest(actual=actual, expected=expected):
                code = 'print(' + repr(json.dumps({'value': actual})) + ')'
                self.write_suite([self.step(code=code, assertions=[dict(pointer='/value', equals=expected)])])
                attempt = self.run_suite(expected_exit=0 if matches else 1)['attempts'][0]
                self.assertEqual(attempt['outcome'], 'verified' if matches else 'failed')

    def test_invalid_verifier_output_does_not_match_expected_assertion_failure(self):
        for output in ['not JSON', '{"unrelated": false}']:
            with self.subTest(output=output):
                self.write_suite([self.step(code='print(' + repr(output) + ')',
                                            assertions=[dict(pointer='/version_equal', equals=True)])],
                                 expected_outcome='failed',
                                 expected_failure=dict(step='assert-state', kind='assertion-failed'))
                attempt = self.run_suite(expected_exit=1)['attempts'][0]
                self.assertFalse(attempt['expected_outcome_matched'])
                self.assertEqual(attempt['steps'][0]['failure'], 'invalid-verifier-output')

    def test_missing_executable_is_blocked_and_not_invented(self):
        step = self.step(phase='preflight')
        step['argv'] = ['agent-eval-intentionally-absent-executable']
        self.write_suite([step], expected_outcome='blocked')
        attempt = self.run_suite()['attempts'][0]
        self.assertEqual(attempt['outcome'], 'blocked')
        self.assertTrue(attempt['expected_outcome_matched'])
        self.assertFalse(attempt['first_attempt_success'])
        self.assertEqual(attempt['steps'][0]['failure'], 'missing-tool')
        self.assertEqual(attempt['invented_commands_observed'], 0)

    def test_action_failure_skips_verifier(self):
        self.write_suite([self.step('change', 'import sys; sys.exit(7)', 'action'),
                          self.step(assertions=[dict(pointer='/count', equals=1)])])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(len(attempt['steps']), 1)
        self.assertEqual(attempt['steps'][0]['exit_code'], 7)

    def test_wrong_blocker_does_not_match_expected_diagnosis(self):
        self.write_suite([self.step('probe', "import sys; print('unrelated error', file=sys.stderr); sys.exit(1)", 'preflight')],
                         expected_outcome='blocked',
                         expected_failure=dict(step='probe', kind='nonzero-exit', stderr_contains='service-unavailable:'))
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'blocked')
        self.assertFalse(attempt['expected_outcome_matched'])

    def test_verified_quality_requires_every_verifier_not_a_partial_success(self):
        self.write_suite([self.step('first', assertions=[dict(pointer='/count', equals=1)]),
                          self.step('second', code='print("not JSON")', assertions=[dict(pointer='/count', equals=1)])])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertIsNone(attempt['time_to_verified_result_seconds'])

    def test_timeout_terminates_child_and_records_failure(self):
        self.write_suite([self.step(code='import time; time.sleep(10)', timeout_seconds=0.05,
                                    assertions=[dict(pointer='/count', equals=1)])])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['steps'][0]['failure'], 'timeout')

    def test_missing_artifact_fails_even_when_verifier_passes(self):
        self.write_suite(artifacts=[dict(path='not-generated.masp', min_bytes=1)])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertIn('artifact', attempt['reason'])

    def test_retry_keeps_first_failure_and_summary_does_not_inflate_rate(self):
        self.write_suite([self.step(assertions=[dict(pointer='/count', equals=2)])])
        first = self.run_suite(expected_exit=1)
        first_path = self.output / (first['run_id'] + '.json')
        original = first_path.read_bytes()
        self.write_suite()
        retry = self.run_suite('--retry-of', first_path)
        self.assertEqual(first_path.read_bytes(), original)
        second = retry['attempts'][0]
        self.assertEqual(second['attempt_number'], 2)
        self.assertIsNone(second['first_attempt_success'])
        self.assertEqual(second['trial_id'], first['attempts'][0]['trial_id'])
        self.assertIsNotNone(second['time_to_verified_result_seconds'])
        self.assertGreater(second['total_active_time_to_verified_result_seconds'], second['elapsed_seconds'])
        summary = self.call('summarize', first_path, self.output / (retry['run_id'] + '.json'))
        self.assertEqual(summary.returncode, 0, summary.stderr)
        group = json.loads(summary.stdout)['modes']['fixture']
        self.assertEqual(group['first_attempt_success_rate'], 0)
        self.assertEqual(group['retry_attempts'], 1)
        self.assertEqual(group['verified_after_retry'], 1)
        missing = self.call('summarize', self.output / (retry['run_id'] + '.json'))
        self.assertEqual(missing.returncode, 2)

    def test_retry_cannot_change_evaluation_mode(self):
        self.write_suite()
        first = self.run_suite()
        data = json.loads(self.suite.read_text())
        data['mode'] = 'integration'
        self.suite.write_text(json.dumps(data))
        proc = self.call('run', '--suite', self.suite, '--output', self.output,
                         '--retry-of', self.output / (first['run_id'] + '.json'))
        self.assertEqual(proc.returncode, 2)
        self.assertIn('mode', proc.stderr)

    def test_complete_activity_audit_counts_interventions_and_invented_commands(self):
        events = [{'type':'human_intervention', 'description':'Fixture operator fixes prerequisite'},
                  {'type':'command', 'argv':['fictional-fixture-command'], 'classification':'invented',
                   'reason':'Deliberately fabricated in test activity'},
                  {'type':'audit_complete', 'scope':'worker_commands_and_human_interventions'}]
        code = "import os; from pathlib import Path; Path(os.environ['EVAL_ACTIVITY_PATH']).write_text(" + repr(''.join(json.dumps(e) + '\n' for e in events)) + ')'
        self.write_suite([self.step('agent', code, 'action'),
                          self.step(assertions=[dict(pointer='/count', equals=1)])])
        attempt = self.run_suite()['attempts'][0]
        self.assertEqual(attempt['human_interventions'], 1)
        self.assertEqual(attempt['invented_commands'], 1)
        self.assertEqual(attempt['command_audit_status'], 'complete')

    def test_invalid_activity_retains_failed_attempt_and_completed_cases(self):
        for operation in ["write_text('not json')", 'mkdir()']:
            with self.subTest(operation=operation):
                completed = self.write_suite()['cases'][0]
                completed['id'] = 'completed'
                code = "import os; from pathlib import Path; Path(os.environ['EVAL_ACTIVITY_PATH'])." + operation
                data = self.write_suite([self.step('agent', code, 'action'),
                                         self.step(assertions=[dict(pointer='/count', equals=1)])])
                data['cases'].insert(0, completed)
                self.suite.write_text(json.dumps(data))
                first, attempt = self.run_suite(expected_exit=1)['attempts']
                self.assertEqual(first['outcome'], 'verified')
                self.assertEqual(attempt['outcome'], 'failed')
                self.assertEqual(attempt['command_audit_status'], 'invalid')
                self.assertIsNone(attempt['invented_commands'])

    def test_manifest_rejects_shell_strings_and_unknown_variables(self):
        data = self.write_suite()
        data['cases'][0]['steps'][0]['argv'] = 'echo invented-shell-command'
        self.suite.write_text(json.dumps(data))
        self.assertEqual(self.call('run', '--suite', self.suite, '--output', self.output).returncode, 2)
        data = self.write_suite()
        data['cases'][0]['steps'][0]['argv'][0] = '{unknown}'
        self.suite.write_text(json.dumps(data))
        self.assertEqual(self.call('run', '--suite', self.suite, '--output', self.output).returncode, 2)
        self.assertFalse(self.output.exists())

    def test_malformed_nested_manifest_shapes_exit_two_without_traceback(self):
        for field, value in [('steps', ['bad']), ('artifacts', [None]), ('artifacts', {}),
                             ('expected_failure', []), ('steps', [dict(id='verify', phase='verify',
                              argv=['{python}'], source='test', assertions=['bad'])])]:
            with self.subTest(field=field, value=value):
                data = self.write_suite()
                data['cases'][0][field] = value
                self.suite.write_text(json.dumps(data))
                proc = self.call('run', '--suite', self.suite, '--output', self.output)
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn('Traceback', proc.stderr)

    def test_agent_mode_requires_named_adapter_and_model(self):
        data = self.write_suite()
        data['mode'] = 'agent'
        self.suite.write_text(json.dumps(data))
        proc = self.call('run', '--suite', self.suite, '--output', self.output)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('agent', proc.stderr)

    def test_worker_receives_task_prompt_and_baseline_is_hashed(self):
        source = self.path / 'baseline.json'
        source.write_text('{"version":"0.17"}')
        code = "import os; from pathlib import Path; assert Path(os.environ['EVAL_PROMPT_PATH']).read_text() == 'Write a fresh contract'; print('{\"count\":1}')"
        data = self.write_suite([self.step(code=code, assertions=[dict(pointer='/count', equals=1)])], task='Write a fresh contract')
        data['source_files'] = [str(source)]
        self.suite.write_text(json.dumps(data))
        report = self.run_suite()
        self.assertEqual(len(report['source_files'][0]['sha256']), 64)
        self.assertEqual(report['source_files'][0]['bytes'], source.stat().st_size)

    def test_verified_blocker_diagnosis_does_not_count_as_task_success(self):
        self.write_suite([self.step(code='print(\'{"missing_tool_named":true}\')',
                                    assertions=[dict(pointer='/missing_tool_named', equals=True)])],
                         expected_outcome='blocked', verified_outcome='blocked')
        attempt = self.run_suite()['attempts'][0]
        self.assertTrue(attempt['diagnosis_verified'])
        self.assertFalse(attempt['first_attempt_success'])
        self.assertIsNone(attempt['time_to_verified_result_seconds'])
        self.assertGreater(attempt['time_to_verified_diagnosis_seconds'], 0)

    def test_agent_label_requires_execution_of_declared_adapter(self):
        data = self.write_suite(task='A real agent task')
        data.update(mode='agent', agent=dict(adapter=sys.executable, model='operator-declared-test-model'))
        self.suite.write_text(json.dumps(data))
        proc = self.call('run', '--suite', self.suite, '--output', self.output)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('adapter', proc.stderr)

    def test_summary_separates_fixture_and_integration_counts(self):
        data = self.write_suite()
        fixture = self.run_suite()
        data['mode'] = 'integration'
        self.suite.write_text(json.dumps(data))
        integration = self.run_suite()
        proc = self.call('summarize', self.output / (fixture['run_id'] + '.json'),
                         self.output / (integration['run_id'] + '.json'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        modes = json.loads(proc.stdout)['modes']
        self.assertEqual(set(modes), {'fixture', 'integration'})
        self.assertEqual(modes['fixture']['first_attempts'], 1)
        self.assertEqual(modes['integration']['first_attempts'], 1)
        self.assertIsNone(modes['integration']['invented_commands_total'])

    def test_artifact_cannot_escape_workspace_or_follow_symlinks(self):
        self.write_suite(artifacts=[dict(path='../outside', min_bytes=1)])
        self.assertEqual(self.call('run', '--suite', self.suite, '--output', self.output).returncode, 2)
        outside = self.path / 'outside'
        outside.write_text('valuable pre-existing output')
        code = f"from pathlib import Path; Path('stale').symlink_to({str(outside)!r})"
        self.write_suite([self.step('link', code, 'action'), self.step(assertions=[dict(pointer='/count', equals=1)])],
                         artifacts=[dict(path='stale', min_bytes=1)])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')

    def test_replaced_workspace_root_cannot_supply_external_artifact(self):
        external = self.path / 'external'
        external.mkdir()
        (external / 'package.masp').write_text('pre-existing artifact')
        code = ("import os; from pathlib import Path; p=Path(os.environ['EVAL_WORKDIR']); "
                f"p.rename(p.with_name('preserved-workspace')); p.symlink_to({str(external)!r}, target_is_directory=True)")
        self.write_suite([self.step('replace-root', code, 'action'),
                          self.step(assertions=[dict(pointer='/count', equals=1)])],
                         artifacts=[dict(path='package.masp')])
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertIn('symlink', attempt['reason'])

    def test_invalid_audit_revokes_previously_verified_diagnosis(self):
        code = "import os; from pathlib import Path; Path(os.environ['EVAL_ACTIVITY_PATH']).write_text('malformed'); print('{\"missing_tool_named\":true}')"
        self.write_suite([self.step(code=code, assertions=[dict(pointer='/missing_tool_named', equals=True)])],
                         expected_outcome='blocked', verified_outcome='blocked')
        attempt = self.run_suite(expected_exit=1)['attempts'][0]
        self.assertEqual(attempt['outcome'], 'failed')
        self.assertFalse(attempt['diagnosis_verified'])
        self.assertIsNone(attempt['time_to_verified_diagnosis_seconds'])

    def test_cannot_reorder_action_after_verifier(self):
        self.write_suite([self.step(assertions=[dict(pointer='/count', equals=1)]),
                          self.step('modify-after-check', 'print("oops")', 'action')])
        self.assertEqual(self.call('run', '--suite', self.suite, '--output', self.output).returncode, 2)

    def test_fixtures_cover_all_six_scenarios_with_expected_positive_and_failure_cases(self):
        proc = self.call('run', '--suite', ROOT / 'evaluation/fixtures.json', '--output', self.output)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        report = json.loads(Path(json.loads(proc.stdout)['report']).read_text())
        self.assertEqual(report['mode'], 'fixture')
        self.assertEqual(len({a['scenario'] for a in report['attempts']}), 6)
        self.assertEqual([a['outcome'] for a in report['attempts']],
                         ['verified', 'verified', 'verified', 'blocked', 'failed', 'blocked'])
        self.assertTrue(all(a['expected_outcome_matched'] for a in report['attempts']))


if __name__ == '__main__':
    unittest.main()

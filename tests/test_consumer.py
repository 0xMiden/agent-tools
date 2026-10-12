import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('agent_tools', ROOT / 'scripts/agent_tools.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

class ConsumerAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.data = cli.catalog()
        guide = b'Published guide for test fixture\n'
        skill = b'---\nname: web-client-usage\ndescription: Fixture\n---\nTest guidance.\n'
        hashed = lambda b: hashlib.sha256(b).hexdigest()
        self.data['release']['web_packages'] = {'@miden-sdk/miden-sdk': {'version': '0.17.1', 'context': {'AGENTS.md': hashed(guide), 'skills/web-client-usage/SKILL.md': hashed(skill)}}}
        self.data['release']['docs'] = {'version': '0.17', 'channel': 'stable', 'source': 'https://github.com/0xMiden/docs/pull/378'}
        pkg = self.project / 'node_modules/@miden-sdk/miden-sdk'
        (pkg / 'skills/web-client-usage').mkdir(parents=True)
        (pkg / 'package.json').write_text(json.dumps({'name': '@miden-sdk/miden-sdk', 'version': '0.17.1'}))
        (pkg / 'AGENTS.md').write_bytes(guide)
        (pkg / 'skills/web-client-usage/SKILL.md').write_bytes(skill)
        copied = self.project / '.claude/skills/web-client-usage/SKILL.md'
        copied.parent.mkdir(parents=True)
        copied.write_bytes(skill)
        (self.project / 'package.json').write_text(json.dumps({'dependencies': {'@miden-sdk/miden-sdk': '0.17.1'}, 'scripts': {'prepare': 'miden-skills sync || true'}}))
        (self.project / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {'node_modules/@miden-sdk/miden-sdk': {'version': '0.17.1'}}}))
        (self.project / 'AGENTS.md').write_text('node_modules/@miden-sdk/miden-sdk/AGENTS.md\n')
        (self.project / 'CLAUDE.md').write_text('@AGENTS.md\n')

    def check(self, profile='web', version='0.17', channel='stable', agent='claude'):
        return cli.check_consumer(self.project, self.data, profile, version, channel, agent)

    def test_installed_context_success_reports_artifact_hashes_and_limits(self):
        result = self.check()
        self.assertTrue(result['valid'])
        self.assertEqual(result['packages']['@miden-sdk/miden-sdk']['version'], '0.17.1')
        self.assertFalse(result['hook_execution_verified'])

    def test_wrong_docs_channel_is_not_accepted_as_release_context(self):
        with self.assertRaisesRegex(ValueError, 'docs channel'):
            self.check(channel='current')

    def test_wrong_docs_version_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'docs version'):
            self.check(version='0.16')

    def test_installed_package_version_mismatch_is_actionable(self):
        path = self.project / 'node_modules/@miden-sdk/miden-sdk/package.json'
        path.write_text(json.dumps({'name': '@miden-sdk/miden-sdk', 'version': '0.16.4'}))
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            self.check()

    def test_installed_guide_must_match_published_artifact_not_just_exist(self):
        (self.project / 'node_modules/@miden-sdk/miden-sdk/AGENTS.md').write_text('stale guide')
        with self.assertRaisesRegex(ValueError, 'context mismatch'):
            self.check()

    def test_missing_published_context_fails(self):
        (self.project / 'node_modules/@miden-sdk/miden-sdk/skills/web-client-usage/SKILL.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing context'):
            self.check()

    def test_missing_copied_context_fails_even_with_prepare_declared(self):
        (self.project / '.claude/skills/web-client-usage/SKILL.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing synced context'):
            self.check()

    def test_modified_copied_context_fails(self):
        (self.project / '.claude/skills/web-client-usage/SKILL.md').write_text('stale copy')
        with self.assertRaisesRegex(ValueError, 'Synced context mismatch'):
            self.check()

    def test_missing_agent_pointer_is_actionable(self):
        (self.project / 'AGENTS.md').write_text('unrelated instructions')
        with self.assertRaisesRegex(ValueError, 'AGENTS.md pointer'):
            self.check()

    def test_missing_claude_import_is_actionable(self):
        (self.project / 'CLAUDE.md').write_text('unrelated instructions')
        with self.assertRaisesRegex(ValueError, 'CLAUDE.md'):
            self.check()

    def test_missing_prepare_is_actionable(self):
        (self.project / 'package.json').write_text(json.dumps({'dependencies': {'@miden-sdk/miden-sdk': '0.17.1'}}))
        with self.assertRaisesRegex(ValueError, 'prepare'):
            self.check()

    def test_lock_mismatch_is_not_hidden_by_installed_package(self):
        (self.project / 'package-lock.json').write_text(json.dumps({'lockfileVersion': 3, 'packages': {'node_modules/@miden-sdk/miden-sdk': {'version': '0.16.4'}}}))
        with self.assertRaisesRegex(ValueError, 'Lock version mismatch'):
            self.check()

    def test_npm_shrinkwrap_takes_precedence(self):
        lock = self.project / 'package-lock.json'
        shrinkwrap = self.project / 'npm-shrinkwrap.json'
        current = json.loads(lock.read_text())
        stale = json.loads(lock.read_text())
        stale['packages']['node_modules/@miden-sdk/miden-sdk']['version'] = '0.16.4'
        shrinkwrap.write_text(json.dumps(stale))
        with self.assertRaisesRegex(ValueError, 'Lock version mismatch'):
            self.check()
        shrinkwrap.write_text(json.dumps(current))
        lock.write_text(json.dumps(stale))
        self.assertTrue(self.check()['valid'])
        lock.unlink()
        self.assertTrue(self.check()['valid'])

    def test_rust_tuple_from_actual_locked_packages(self):
        (self.project / 'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "miden-client"\nversion = "0.17.2"\n\n[[package]]\nname = "miden-protocol"\nversion = "0.17.1"\n\n[[package]]\nname = "miden-core"\nversion = "0.35.0"\n')
        for toolchain, valid in [
            ('[toolchain]\nchannel = "0.17.0"\n', True),
            ("[toolchain]\n  channel = '0.17.0' # release pin\n", True),
            ('[metadata]\nchannel = "0.16.0"\n[toolchain]\nchannel = "0.17.0"\n', True),
            ('[metadata]\nchannel = "0.17.0"\n[toolchain]\nchannel = "0.16.0"\n', False),
            ('channel = "0.17.0"\n', False),
        ]:
            with self.subTest(toolchain=toolchain):
                (self.project / 'miden-toolchain.toml').write_text(toolchain)
                if valid:
                    result = self.check(profile='rust')
                    self.assertTrue(result['valid'])
                    self.assertEqual(result['toolchain'], '0.17.0')
                    self.assertFalse(result['compiler_execution_verified'])
                else:
                    with self.assertRaisesRegex(ValueError, 'toolchain channel mismatch'):
                        self.check(profile='rust')

    def test_rust_tuple_mismatch_fails(self):
        (self.project / 'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "miden-client"\nversion = "0.16.4"\n')
        (self.project / 'miden-toolchain.toml').write_text('[toolchain]\nchannel = "0.17.0"\n')
        with self.assertRaisesRegex(ValueError, 'Cargo version mismatch'):
            self.check(profile='rust')

    def test_missing_cargo_lock_is_actionable(self):
        with self.assertRaisesRegex(ValueError, 'Cargo.lock'):
            self.check(profile='rust')

    def test_yarn_v1_actual_resolved_version_is_supported(self):
        (self.project / 'package-lock.json').unlink()
        for selector in ['"@miden-sdk/miden-sdk@0.17.1"',
                         '"@miden-sdk/miden-sdk@^0.17.0", "@miden-sdk/miden-sdk@0.17.1"']:
            with self.subTest(selector=selector):
                (self.project / 'yarn.lock').write_text(
                    f'# yarn lockfile v1\n\n{selector}:\n  version "0.17.1"\n'
                    '\n"@miden-sdk/miden-sdk@^0.16.0":\n  version "0.16.4"\n')
                self.assertTrue(self.check()['valid'])

    def test_yarn_v1_mismatch_fails(self):
        (self.project / 'package-lock.json').unlink()
        for selector, version in [('0.17.1', '0.16.4'), ('^0.17.1', '0.17.1')]:
            with self.subTest(selector=selector, version=version):
                (self.project / 'yarn.lock').write_text(
                    f'# yarn lockfile v1\n\n"@miden-sdk/miden-sdk@{selector}":\n  version "{version}"\n')
                with self.assertRaisesRegex(ValueError, 'Lock version mismatch'):
                    self.check()

    def test_codex_consumer_does_not_require_claude_import(self):
        (self.project / 'CLAUDE.md').unlink()
        self.assertTrue(self.check(agent='codex')['valid'])

    def test_bundle_rejects_missing_docs_context(self):
        from unittest.mock import patch
        release = json.loads((ROOT / 'release.json').read_text())
        del release['docs']
        fixture = self.project / 'broken-bundle'
        fixture.mkdir()
        (fixture / 'release.json').write_text(json.dumps(release))
        (fixture / 'skills').mkdir()
        with patch.object(cli, 'ROOT', fixture):
            with self.assertRaisesRegex(ValueError, 'release.json.*docs'):
                cli.catalog()

if __name__ == '__main__':
    unittest.main()

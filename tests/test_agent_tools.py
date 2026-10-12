import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'agent_tools.py'

class JourneyFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / 'project'
        self.project.mkdir()
        self.addCleanup(self.temp.cleanup)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)

    def install(self, *args):
        return self.run_cli('install', '--project', str(self.project), '--agent', 'codex', '--skill', 'miden-concepts', *args)

class InstallerJourney(JourneyFixture, unittest.TestCase):
    def test_discovery_reports_prompts_and_release(self):
        result = self.run_cli('list')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['release']['protocol'], '0.17.1')
        self.assertTrue(any(x['name'] == 'miden-concepts' and x['kind'] == 'skill' for x in data['entries']))
        self.assertTrue(all(x['effect'] == 'prompt' for x in data['entries']))

    def test_preview_does_not_write(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertFalse(json.loads(result.stdout)['applied'])

    def test_apply_preserves_context_and_is_repeatable(self):
        agents = self.project / 'AGENTS.md'
        agents.write_text('Project rules: keep this.\n')
        first = self.install('--apply')
        self.assertEqual(first.returncode, 0, first.stderr)
        skill = self.project / '.agents/skills/miden-concepts/SKILL.md'
        self.assertEqual(skill.read_bytes(), (ROOT / 'skills/miden-concepts/SKILL.md').read_bytes())
        self.assertTrue(agents.read_text().startswith('Project rules: keep this.\n'))
        before = agents.read_bytes()
        second = self.install('--apply')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(before, agents.read_bytes())
        self.assertIn('unchanged', second.stdout)

    def test_collision_prevents_all_writes(self):
        target = self.project / '.agents/skills/miden-concepts'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('user content')
        result = self.install('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertIn('collision', result.stderr)
        self.assertEqual((target / 'SKILL.md').read_text(), 'user content')
        self.assertFalse((self.project / 'AGENTS.md').exists())

    def test_symlink_destination_is_refused(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.project / '.agents').symlink_to(outside, target_is_directory=True)
        result = self.install('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertIn('symlink', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_unknown_skill_does_not_write(self):
        result = self.run_cli('install', '--project', str(self.project), '--agent', 'codex', '--skill', '../bad', '--apply')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Unknown skill', result.stderr)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_malformed_context_is_not_replaced(self):
        agents = self.project / 'AGENTS.md'
        agents.write_text('rules\n<!-- miden-agent-tools:start -->\nbroken')
        result = self.install('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertIn('marker', result.stderr)
        self.assertEqual(list(self.project.iterdir()), [agents])

    def test_check_reports_missing_and_modified_install(self):
        missing = self.run_cli('check', '--project', str(self.project), '--agent', 'codex', '--skill', 'miden-concepts')
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(self.install('--apply').returncode, 0)
        good = self.run_cli('check', '--project', str(self.project), '--agent', 'codex', '--skill', 'miden-concepts')
        self.assertEqual(good.returncode, 0, good.stderr)
        (self.project / '.agents/skills/miden-concepts/SKILL.md').write_text('modified')
        bad = self.run_cli('check', '--project', str(self.project), '--agent', 'codex', '--skill', 'miden-concepts')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('collision', bad.stderr)

class InstallerBoundaries(JourneyFixture, unittest.TestCase):
    def test_unrelated_skills_and_web_sdk_context_survive(self):
        skill = self.project / '.agents/skills/custom/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('custom skill')
        web = '<!-- miden-web-sdk:start -->\nRead node_modules/@miden-sdk/react/skills\n<!-- miden-web-sdk:end -->\n'
        (self.project / 'AGENTS.md').write_text(web)
        self.assertEqual(self.install('--apply').returncode, 0)
        self.assertEqual(skill.read_text(), 'custom skill')
        self.assertTrue((self.project / 'AGENTS.md').read_text().startswith(web))

    def test_command_install_is_claude_only(self):
        denied = self.install('--commands', '--apply')
        self.assertEqual(denied.returncode, 1)
        self.assertEqual(list(self.project.iterdir()), [])
        result = self.run_cli('install', '--project', str(self.project), '--agent', 'claude', '--skill', 'miden-concepts', '--commands', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / '.claude/commands/review-plan.md').read_bytes(), (ROOT / 'commands/review-plan.md').read_bytes())

    def test_cursor_install_uses_project_skills(self):
        result = self.run_cli('install', '--project', str(self.project), '--agent', 'cursor', '--skill', 'miden-concepts', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.project / '.cursor/skills/miden-concepts/SKILL.md').is_file())

    def test_unknown_extra_file_in_selected_skill_is_preserved(self):
        self.assertEqual(self.install('--apply').returncode, 0)
        extra = self.project / '.agents/skills/miden-concepts/notes.txt'
        extra.write_text('personal notes')
        before = (self.project / 'AGENTS.md').read_bytes()
        result = self.install('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(extra.read_text(), 'personal notes')
        self.assertEqual((self.project / 'AGENTS.md').read_bytes(), before)

    def test_failed_context_write_rolls_back_only_own_new_files(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('agent_tools', CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        unrelated = self.project / 'keep.txt'
        unrelated.write_text('keep')
        args = type('Args', (), dict(project=str(self.project), agent='codex', skill=['miden-concepts'], commands=False))()
        plan = module.plan_install(args, module.catalog())
        with patch.object(module.os, 'replace', side_effect=OSError('simulated disk error')):
            with self.assertRaisesRegex(OSError, 'simulated disk error'):
                module.apply_plan(*plan)
        self.assertEqual(list(self.project.iterdir()), [unrelated])
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_catalog_rejects_skill_directory_without_manifest(self):
        import importlib.util
        from unittest.mock import patch
        import shutil
        spec = importlib.util.spec_from_file_location('agent_tools', CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = Path(self.temp.name) / 'fixture'
        fixture.mkdir()
        shutil.copy(ROOT / 'release.json', fixture / 'release.json')
        (fixture / 'skills/broken').mkdir(parents=True)
        with patch.object(module, 'ROOT', fixture):
            with self.assertRaisesRegex(ValueError, 'SKILL.md'):
                module.catalog()

    def test_default_install_and_check_cover_every_skill(self):
        args = ('--project', str(self.project), '--agent', 'codex')
        result = self.run_cli('install', *args, '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = list((self.project / '.agents/skills').glob('*/SKILL.md'))
        self.assertEqual(len(installed), len(list((ROOT / 'skills').glob('*/SKILL.md'))))
        self.assertEqual(self.run_cli('check', *args).returncode, 0)

    def test_context_suffix_survives_selection_change(self):
        self.assertEqual(self.install('--apply').returncode, 0)
        agents = self.project / 'AGENTS.md'
        agents.write_text(agents.read_text() + '\nProject suffix: keep this.\n')
        result = self.run_cli('install', '--project', str(self.project), '--skill', 'rust-sdk-pitfalls', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(agents.read_text().endswith('Project suffix: keep this.\n'))
        self.assertTrue((self.project / '.agents/skills/miden-concepts/SKILL.md').exists())
        self.assertEqual(agents.read_text().count('<!-- miden-agent-tools:start -->'), 1)

    def test_missing_release_metadata_is_actionable(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('agent_tools', CLI)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = Path(self.temp.name) / 'fixture'
        fixture.mkdir()
        (fixture / 'release.json').write_text('{}')
        (fixture / 'skills').mkdir()
        with patch.object(module, 'ROOT', fixture):
            with self.assertRaisesRegex(ValueError, 'release.json'):
                module.catalog()


if __name__ == '__main__':
    unittest.main()

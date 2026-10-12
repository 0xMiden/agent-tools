// Explicit acceptance test: downloads locked artifacts, then runs only the inspected
// published initializer and the prepare hook in a disposable consumer directory.
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, writeFileSync, copyFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {test} from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.PYTHON || 'python3';

function run(command, args, cwd) {
  const result = spawnSync(command, args, {cwd, encoding: 'utf8', timeout: 120000});
  assert.ifError(result.error);
  return result;
}
function succeed(result) {
  assert.equal(result.status, 0, result.stdout + result.stderr);
  return result.stdout;
}

test('published v17 initializer and consumer prepare regenerate exact context', () => {
  const project = mkdtempSync(join(tmpdir(), 'agent-tools-artifacts-'));
  // Retain the exact fixture path on failure for diagnosis; CI runner handles its teardown.
  console.log(`consumer fixture: ${project}`);
  for (const file of ['package.json', 'package-lock.json']) {
    copyFileSync(join(root, 'tests/fixtures/web-consumer', file), join(project, file));
  }
  succeed(run('npm', ['ci', '--ignore-scripts', '--no-audit', '--no-fund'], project));
  const check = (channel = 'stable') => run(python, [join(root, 'scripts/agent_tools.py'),
    'check-consumer', '--project', project, '--profile', 'web',
    '--docs-version', '0.17', '--docs-channel', channel], project);
  const beforeInit = check();
  assert.equal(beforeInit.status, 1);
  assert.match(beforeInit.stderr, /Missing AGENTS.md/);
  const manifestPath = join(project, 'package.json');
  const manifest = JSON.parse(readFileSync(manifestPath));
  manifest.scripts = {prepare: `node -e "require('fs').appendFileSync('.prepare-executions', 'ran\\n')"`};
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  writeFileSync(join(project, 'AGENTS.md'), 'Existing consumer rules.\n');
  succeed(run('node', ['node_modules/@miden-sdk/create/dist/cli.js'], project));
  assert.match(readFileSync(join(project, 'AGENTS.md'), 'utf8'), /^Existing consumer rules\./);
  assert.match(readFileSync(join(project, 'CLAUDE.md'), 'utf8'), /@AGENTS.md/);
  const initialized = JSON.parse(succeed(check()));
  assert.equal(initialized.hook_execution_verified, false);
  assert.equal(initialized.packages['@miden-sdk/miden-sdk'].version, '0.17.1');
  // Coexist with the agent-tools Claude installation, then execute the consumer hook.
  succeed(run(python, [join(root, 'scripts/agent_tools.py'), 'install', '--project', project,
    '--agent', 'claude', '--skill', 'miden-concepts', '--apply'], project));
  const owned = join(project, '.claude/skills/miden-concepts/SKILL.md');
  const ownBytes = readFileSync(owned);
  const synced = join(project, '.claude/skills/web-client-usage/SKILL.md');
  writeFileSync(synced, 'stale copied context');
  assert.equal(check().status, 1);
  succeed(run('npm', ['run', 'prepare'], project));
  assert.equal(readFileSync(join(project, '.prepare-executions'), 'utf8'), 'ran\n');
  assert.deepEqual(readFileSync(owned), ownBytes);
  const repaired = JSON.parse(succeed(check()));
  const copiedSkills = Object.values(repaired.packages).reduce((count, pkg) =>
    count + Object.keys(pkg.context_hashes).filter(path => path.startsWith('skills/')).length, 0);
  assert.equal(copiedSkills, 9);
  // The hook may report success when context is absent: acceptance checks the outcome.
  const installedGuide = join(project, 'node_modules/@miden-sdk/miden-sdk/AGENTS.md');
  const guideBytes = readFileSync(installedGuide);
  writeFileSync(installedGuide, 'wrong release guide');
  assert.match(check().stderr, /context mismatch/);
  writeFileSync(installedGuide, guideBytes);
  const wrongChannel = check('current');
  assert.equal(wrongChannel.status, 1);
  assert.match(wrongChannel.stderr, /docs channel/);
  assert.ok(existsSync(join(project, 'node_modules/.bin/miden-skills')));
  succeed(check());
});

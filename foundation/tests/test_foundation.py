import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('foundation', SOURCE / 'foundation.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        import shutil
        shutil.copytree(SOURCE / 'template', self.source / 'template')
        (self.source / 'template/playbooks/obsolete.md').write_text('# Retired optional procedure\n')
        shutil.copy(SOURCE / 'foundation.py', self.source / 'foundation.py')
        shutil.copy(SOURCE / 'source-exclusions.json', self.source / 'source-exclusions.json')
        shutil.copytree(SOURCE / 'backend', self.source / 'backend', ignore=shutil.ignore_patterns('__pycache__'))
        self.config = self.base / 'config.json'
        self.config.write_text(json.dumps({'company_id': 'fixture', 'company_name': 'Fixture Company', 'owner_name': 'Fixture Owner', 'timezone': 'UTC', 'names': {}, 'models': {}}))
        self.bundle = self.build('1.0.0')
        self.root = self.base / 'installed'
        f.initialize(types.SimpleNamespace(root=self.root, config=self.config, bundle=self.bundle))
    def tearDown(self):
        self.temp.cleanup()
    def build(self, version):
        bundle = self.base / (version + '.zip')
        with contextlib.redirect_stdout(io.StringIO()):
            f.build_release(self.source, bundle, version)
        return bundle
    def args(self, command, **kw):
        return types.SimpleNamespace(root=self.root, command=command, apply=False, backup=None, **kw)
    def new_bundle(self):
        role = self.source / 'template/roles/cos.md'
        role.write_text(role.read_text() + '\nNew reusable role improvement.\n')
        return self.build('1.1.0')
    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def test_init_uses_final_paths_and_blank_company_context(self):
        config = f.read_json(self.root / 'generated/openclaw.fragment.json')
        self.assertEqual(config['agents']['entries']['cos']['workspace'], str(self.root / 'workspaces/cos'))
        self.assertEqual(len(config['agents']['entries']), 18)
        self.assertEqual(f.read_json(self.root / 'company/context/facts.json'), {'facts': []})
        self.assertFalse((self.root / '.openclaw').exists())
        self.assertIn('Fixture Company', (self.root / 'workspaces/cos/AGENTS.md').read_text())
    def test_update_preview_is_read_only_then_preserves_company_and_memory(self):
        company = self.root / 'company/context/facts.json'
        company.write_text('{"facts": [{"id":"company.fixture","value":7}]}\n')
        memory = self.root / 'workspaces/cos/MEMORY.md'
        memory.write_text('Installation memory\n')
        before = self.snapshot()
        bundle = self.new_bundle()
        preview = f.update(self.args('update', bundle=bundle))
        self.assertGreater(len(preview['changes']), 0)
        self.assertEqual(before, self.snapshot())
        args = self.args('update', bundle=bundle); args.apply = True
        result = f.update(args)
        self.assertEqual(result['version'], '1.1.0')
        self.assertIn('"value":7', company.read_text())
        self.assertEqual(memory.read_text(), 'Installation memory\n')
        self.assertIn('New reusable', (self.root / 'workspaces/cos/AGENTS.md').read_text())
        self.assertEqual(f.update(args)['result'], 'already current')
    def test_conflict_blocks_whole_update_and_restores_nothing_unrelated(self):
        managed = self.root / 'workspaces/cos/AGENTS.md'
        managed.write_text('Local edit\n')
        old = f.read_json(self.root / f.STATE)
        args = self.args('update', bundle=self.new_bundle()); args.apply = True
        with self.assertRaises(f.Error): f.update(args)
        self.assertEqual(old, f.read_json(self.root / f.STATE))
        self.assertEqual(managed.read_text(), 'Local edit\n')
    def test_custom_roles_and_agents_survive(self):
        custom = self.root / 'custom/roles/cos.md'
        custom.parent.mkdir(parents=True)
        custom.write_text('# Custom coordinator\nKeep this local role.\n')
        seatdir = self.root / 'custom/agents/fixture-worker'
        seatdir.mkdir(parents=True)
        (seatdir / 'seat.json').write_text(json.dumps({'id': 'fixture-worker', 'title': 'Fixture Worker', 'type': 'control', 'reports_to': 'cos', 'spawn': []}))
        (seatdir / 'role.md').write_text('# Local worker\nOne bounded task.\n')
        args = self.args('render'); args.apply = True
        f.update(args)
        args = self.args('update', bundle=self.new_bundle()); args.apply = True
        f.update(args)
        self.assertIn('Keep this local role', (self.root / 'workspaces/cos/AGENTS.md').read_text())
        self.assertEqual(custom.read_text(), '# Custom coordinator\nKeep this local role.\n')
        self.assertTrue((self.root / 'workspaces/fixture-worker/AGENTS.md').exists())
    def test_rollback_exactly_restores_managed_bytes(self):
        old = f.read_json(self.root / f.STATE)
        original = {k: (self.root / k).read_bytes() for k in old['files']}
        args = self.args('update', bundle=self.new_bundle()); args.apply = True
        f.update(args)
        before_preview = self.snapshot()
        preview = f.rollback(self.args('rollback'))
        self.assertEqual(preview['to'], '1.0.0')
        self.assertEqual(before_preview, self.snapshot())
        args = self.args('rollback'); args.apply = True
        f.rollback(args)
        for name, data in original.items(): self.assertEqual((self.root / name).read_bytes(), data)
    def test_rollback_refuses_post_update_drift(self):
        args = self.args('update', bundle=self.new_bundle()); args.apply = True
        f.update(args)
        (self.root / 'workspaces/cos/AGENTS.md').write_text('Changed after update')
        args = self.args('rollback'); args.apply = True
        with self.assertRaises(f.Error): f.rollback(args)
    def test_safe_paths_and_symlinks(self):
        for name in ('../bad', '/bad', 'a/../b', 'a\\b', 'a//b'):
            with self.assertRaises(f.Error): f.safe_name(name)
        outside = self.base / 'outside'; outside.write_text('untouched')
        managed = self.root / 'workspaces/cos/AGENTS.md'; managed.unlink(); managed.symlink_to(outside)
        with self.assertRaises(f.Error): f.update(self.args('update', bundle=self.new_bundle()))
        self.assertEqual(outside.read_text(), 'untouched')
    def test_malicious_or_corrupt_bundle_rejected_before_writes(self):
        bundle = self.base / 'malicious.zip'
        with zipfile.ZipFile(bundle, 'w') as z: z.writestr('../escape', 'bad')
        before = self.snapshot()
        with self.assertRaises(f.Error): f.update(self.args('update', bundle=bundle))
        self.assertEqual(before, self.snapshot())
        with zipfile.ZipFile(self.bundle) as z: entries = {n: z.read(n) for n in z.namelist()}
        entries['template/roles/cos.md'] = b'corrupted'
        bad = self.base / 'corrupt.zip'
        with zipfile.ZipFile(bad, 'w') as z:
            for n, v in entries.items(): z.writestr(n, v)
        with self.assertRaises(f.Error): f.bundle_read(bad)
    def test_company_leak_in_template_rejected(self):
        (self.source / 'template/roles/cos.md').write_text('source-private-marker private company fact')
        with self.assertRaises(f.Error): self.build('9.0.0')
    def test_source_identifiers_and_exclusions_are_not_distributed(self):
        meta, payload = f.bundle_read(self.bundle)
        pattern = __import__('re').compile(f.read_json(SOURCE / 'source-exclusions.json')['pattern'])
        self.assertFalse(any(pattern.search(data.decode()) for data in payload.values()))
        self.assertFalse(any('source-exclusions' in name for name in payload))
    def test_duplicate_agent_rejected(self):
        p = self.source / 'template/manifest.json'; m = f.read_json(p)
        m['agents'].append(m['agents'][0]); p.write_text(json.dumps(m))
        with self.assertRaises(f.Error): self.build('9.0.0')
    def test_failure_during_apply_restores_prior_bytes_and_state(self):
        from unittest.mock import patch
        before = f.read_json(self.root / f.STATE)
        original = {k: (self.root / k).read_bytes() for k in before['files']}
        bundle = self.new_bundle()
        real = f.atomic
        calls = [0]
        def fail_once(path, data):
            if str(path).endswith('workspaces/cos/AGENTS.md') and calls[0] == 0:
                calls[0] += 1
                raise OSError('simulated disk failure')
            return real(path, data)
        args = self.args('update', bundle=bundle); args.apply = True
        with patch.object(f, 'atomic', side_effect=fail_once):
            with self.assertRaises(OSError): f.update(args)
        self.assertEqual(before, f.read_json(self.root / f.STATE))
        for name,data in original.items(): self.assertEqual((self.root / name).read_bytes(),data)
    def test_existing_root_is_never_overwritten(self):
        with self.assertRaises(f.Error): f.initialize(types.SimpleNamespace(root=self.root, config=self.config, bundle=self.bundle))
    def test_render_updates_company_snapshot_without_replacing_history(self):
        (self.root / 'bible/SNAPSHOT.md').write_text('# Updated local facts\n')
        history = self.root / 'bible/history.md'; history.write_text('Company history\n')
        args = self.args('render'); args.apply = True
        f.update(args)
        self.assertIn('Updated local facts', (self.root / 'workspaces/cos/AGENTS.md').read_text())
        self.assertEqual(history.read_text(), 'Company history\n')
    def test_doctor_does_not_claim_unverified_readiness(self):
        result = f.doctor(self.args('doctor'))
        self.assertFalse(result['ready_for_autonomy'])
        self.assertEqual(result['managed_drift'], [])
        self.assertTrue(all(s['live_health'] == 'not checked' for s in result['services'].values()))
    def test_no_shell_or_public_tools_and_bounded_spawn(self):
        fragment = f.read_json(self.root / 'generated/openclaw.fragment.json')
        entries = fragment['agents']['entries']
        for entry in entries.values():
            self.assertEqual(entry['heartbeat']['every'], '0m')
            self.assertIn('exec', entry['tools']['deny'])
        self.assertEqual(entries['librarian']['subagents']['allowAgents'], ['context-numbers', 'context-watcher', 'daily-company-recorder'])
        self.assertEqual(entries['context-numbers']['subagents']['allowAgents'], [])
    def test_archive_is_a_standalone_installer_and_installed_launcher_works(self):
        import subprocess, sys
        root = self.base / 'from-archive'
        result = subprocess.run([sys.executable, str(self.bundle), 'init', '--config', str(self.config), '--root', str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(root / 'foundation'), 'doctor'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['ready_for_autonomy'])
    def test_state_cannot_mark_company_records_as_managed(self):
        state = f.read_json(self.root / f.STATE)
        company = self.root / 'config/company.json'
        state['files']['config/company.json'] = f.digest(company.read_bytes())
        (self.root / f.STATE).write_bytes(f.encoded(state))
        with self.assertRaises(f.Error): f.update(self.args('update', bundle=self.new_bundle()))
        self.assertTrue(company.exists())
    def test_same_version_republish_is_refused(self):
        (self.source / 'template/roles/cos.md').write_text('# Changed role\n')
        another = self.base / 'republished.zip'
        with contextlib.redirect_stdout(io.StringIO()): f.build_release(self.source, another, '1.0.0')
        with self.assertRaises(f.Error): f.update(self.args('update', bundle=another))
    def test_removed_managed_playbook_is_reversible(self):
        removed = 'template/playbooks/obsolete.md'
        (self.source / removed).unlink()
        bundle = self.build('1.1.0')
        args = self.args('update', bundle=bundle); args.apply = True
        f.update(args)
        self.assertFalse((self.root / 'workspaces/cos/work/playbooks/obsolete.md').exists())
        args = self.args('rollback'); args.apply = True
        f.rollback(args)
        self.assertTrue((self.root / 'workspaces/cos/work/playbooks/obsolete.md').exists())

if __name__ == '__main__': unittest.main()

#!/usr/bin/env python3
"""Portable foundation release, installation, preview, update and rollback. Python 3.9+, stdlib only."""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import zipfile

VERSION = '2.1.0-rc.1'
# runpy launchers and ZIP execution both need sibling backend imports.
sys.path.insert(0, str(Path(__file__).parent))
MAX_FILE = 2 * 1024 * 1024
MAX_BUNDLE = 16 * 1024 * 1024
STATE = '.foundation/state.json'
MANAGED = '.foundation/managed/'
# Company records, credentials and custom agents are never part of a managed release.
ALLOWED = ('template/', 'runtime/')
BOOT = b"from runtime.foundation import main\nraise SystemExit(main())\n"
FORBIDDEN = re.compile(r'(?i)(BEGIN .*PRIVATE KEY|(?:sk|ghp|github_pat)-[A-Za-z0-9_]{16,})')

class Error(Exception):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest()

def encoded(obj):
    return (json.dumps(obj, indent=2, sort_keys=True) + '\n').encode()

def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Error('Cannot read JSON: %s (%s)' % (path, e))

def safe_name(name):
    p = PurePosixPath(name)
    if not name or '\\' in name or p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        raise Error('Unsafe release path: %s' % name)
    return name

def target(root, name):
    safe_name(name)
    root = Path(root).absolute()
    p = root
    if root.is_symlink():
        raise Error('Installation root is a symbolic link')
    for part in PurePosixPath(name).parts:
        p = p / part
        if p.is_symlink():
            raise Error('Symbolic links are not managed: %s' % p)
    try:
        p.resolve().relative_to(root.resolve())
    except ValueError:
        raise Error('Path leaves installation root')
    return p

def managed_name(name):
    safe_name(name)
    if name.startswith(MANAGED):
        return
    if name in ('generated/openclaw.fragment.json', 'generated/roster.json'):
        return
    if re.fullmatch(r'workspaces/[a-z][a-z0-9-]{0,62}/(?:AGENTS|IDENTITY|USER|SOUL)\.md', name):
        return
    if re.fullmatch(r'workspaces/[a-z][a-z0-9-]{0,62}/work/(?:playbooks/[a-zA-Z0-9-]+\.md|context/company-(?:snapshot|rules)\.md)', name):
        return
    raise Error('Not a template-owned path: ' + name)

def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.foundation-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def source_payload(source):
    source = Path(source)
    payload = {'runtime/foundation.py': (source / 'foundation.py').read_bytes(),
               'runtime/__init__.py': b'', '__main__.py': BOOT}
    for p in sorted((source / 'template').rglob('*')):
        if p.is_symlink():
            raise Error('Release sources cannot be symlinks')
        if p.is_file():
            payload[p.relative_to(source).as_posix()] = p.read_bytes()
    for p in sorted((source / 'backend').rglob('*')):
        if p.is_symlink(): raise Error('Release sources cannot be symlinks')
        if p.is_file() and (p.suffix in ('.py', '.json')) and '__pycache__' not in p.parts:
            payload['runtime/backend/' + p.relative_to(source / 'backend').as_posix()] = p.read_bytes()
    return payload

def validate_payload(payload):
    if not payload or sum(len(v) for v in payload.values()) > MAX_BUNDLE:
        raise Error('Empty or oversized release')
    for name, data in payload.items():
        safe_name(name)
        if (not name.startswith(ALLOWED) and name != '__main__.py') or len(data) > MAX_FILE:
            raise Error('Unapproved or oversized file: ' + name)
        try:
            text = data.decode('utf-8')
        except UnicodeError:
            raise Error('Release files must be UTF-8 text: ' + name)
        # The runtime contains this scanner; scan template content rather than its pattern literals.
        if name != 'runtime/foundation.py' and FORBIDDEN.search(text):
            raise Error('Company data or credential-shaped text found in ' + name)
    required_files = ['runtime/foundation.py', 'runtime/__init__.py', '__main__.py',
                      'template/manifest.json', 'template/rules/core.md', 'template/soul.md',
                      'template/setup.md', 'template/updates.md', 'template/company.example.json',
                      'template/blueprints/portfolio-cos.md']
    required_files += ['template/playbooks/%s.md' % name for name in
                      ('INDEX', 'company-context', 'hiring', 'delegation', 'research', 'reviews', 'approvals', 'proactive', 'service-wiring')]
    for required in required_files:
        if required not in payload:
            raise Error('Missing release file: ' + required)
    manifest = json.loads(payload['template/manifest.json'])
    ids = [a['id'] for a in manifest['agents']]
    if len(set(ids)) != len(ids):
        raise Error('Duplicate agent ids')
    for a in manifest['agents']:
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', a['id']):
            raise Error('Invalid agent id')
        if 'template/roles/%s.md' % a['id'] not in payload:
            raise Error('Missing role for ' + a['id'])
        if a.get('reports_to') not in ids + ['owner', 'portfolio-cos']:
            raise Error('Unknown reporting parent for ' + a['id'])
        if any(x not in ids for x in a.get('spawn', [])):
            raise Error('Unknown child agent for ' + a['id'])
    return manifest

def bundle_read(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 300 or sum(i.file_size for i in infos) > MAX_BUNDLE + MAX_FILE:
            raise Error('Oversized archive')
        if len({i.filename for i in infos}) != len(infos):
            raise Error('Duplicate archive entry')
        for i in infos:
            safe_name(i.filename)
            if i.is_dir() or i.file_size > MAX_FILE or (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise Error('Invalid archive entry')
        meta = json.loads(z.read('release.json'))
        if meta.get('schema') != 1 or set(meta['files']) != {i.filename for i in infos} - {'release.json'}:
            raise Error('Release manifest does not match archive')
        payload = {name: z.read(name) for name in meta['files']}
        if any(digest(data) != meta['files'][name] for name, data in payload.items()):
            raise Error('Release checksum mismatch')
    validate_payload(payload)
    return meta, payload

def build_release(source, output, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?', version):
        raise Error('Use a semantic release version')
    from backend.updates import semver
    semver(version)
    payload = source_payload(source)
    validate_payload(payload)
    # Maintainer-only source exclusions are never distributed with the generic runtime.
    exclusions = Path(source) / 'source-exclusions.json'
    if exclusions.exists():
        pattern = re.compile(read_json(exclusions)['pattern'])
        for name, data in payload.items():
            if pattern.search(data.decode()): raise Error('Source-specific information found in ' + name)
    meta = {'schema': 1, 'version': version, 'files': {k: digest(v) for k, v in sorted(payload.items())}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise Error('Release output already exists; use a new file')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(dict(payload, **{'release.json': encoded(meta)}).items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            z.writestr(info, data)
    print(json.dumps({'release': str(output.absolute()), 'version': version, 'sha256': digest(output.read_bytes()), 'files': len(payload)}, indent=2))

def local_config(root):
    cfg = read_json(target(root, 'config/company.json'))
    for key in ('company_id', 'company_name', 'owner_name', 'timezone'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip() or '\n' in cfg[key]:
            raise Error('Set ' + key + ' in config/company.json')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', cfg['company_id']):
        raise Error('company_id must be a lowercase slug')
    return cfg

def compile_files(root, payload, cfg):
    manifest = validate_payload(payload)
    agents = list(manifest['agents'])
    custom = target(root, 'custom/agents')
    if custom.exists():
        for p in sorted(custom.glob('*/seat.json')):
            seat = read_json(target(root, p.relative_to(root).as_posix()))
            if seat['id'] in {a['id'] for a in agents} or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', seat['id']):
                raise Error('Custom agent has a duplicate or invalid id')
            agents.append(seat)
    ids = [a['id'] for a in agents]
    if cfg.get('portfolio', False):
        for agent in agents:
            if agent['id'] == 'cos': agent['reports_to'] = 'portfolio-cos'
        agents.append({'id': 'portfolio-cos', 'title': 'Portfolio Chief of Staff', 'type': 'chief-of-staff', 'reports_to': 'owner', 'spawn': ['cos'], 'model_class': 'coordinator'})
        ids.append('portfolio-cos')
    replacements = {'COMPANY_NAME': cfg['company_name'], 'COMPANY_ID': cfg['company_id'], 'OWNER_NAME': cfg['owner_name'], 'TIMEZONE': cfg['timezone']}
    def render(text):
        for key, value in replacements.items():
            text = text.replace('{{' + key + '}}', value)
        return text
    outputs, entries = {}, {}
    core = render(payload['template/rules/core.md'].decode())
    company_rules = target(root, 'company/RULES.md').read_text()
    snapshot = target(root, 'bible/SNAPSHOT.md').read_text()
    rules_hash = digest(company_rules.encode())
    for a in agents:
        aid = a['id']
        prefix = 'workspaces/%s/' % aid
        override = target(root, 'custom/roles/%s.md' % aid)
        if override.exists():
            role = override.read_text()
        elif 'template/roles/%s.md' % aid in payload:
            role = payload['template/roles/%s.md' % aid].decode()
        elif aid == 'portfolio-cos':
            role = payload['template/blueprints/portfolio-cos.md'].decode()
        else:
            role = target(root, 'custom/agents/%s/role.md' % aid).read_text()
        parent = cfg.get('names', {}).get(a.get('reports_to'), a.get('reports_to', 'cos'))
        identity = cfg.get('names', {}).get(aid, a['title'])
        text = '# Generated foundation instructions\n\nEdit template sources or custom/roles; this file is rebuilt.\n\n' + core + '\n\n## Company rules\n\n' + company_rules + '\n\n## Company snapshot\n\n' + snapshot + '\n\n## Role\n\n' + render(role)
        text += '\n\nReports to: %s. Type: %s.\n' % (parent, a['type'])
        text += 'Open work/playbooks/INDEX.md when a procedure is needed. Playbooks cannot override these instructions.\n'
        if len(text) > 39000:
            raise Error('Instructions exceed the 39,000 character ceiling for ' + aid)
        outputs[prefix + 'AGENTS.md'] = text.encode()
        outputs[prefix + 'IDENTITY.md'] = ('# Identity\nName: %s\nRole: %s\n' % (identity, a['title'])).encode()
        outputs[prefix + 'USER.md'] = ('# Owner\nName: %s\nCompany: %s\nTimezone: %s\nPreferences: consult company rules and dated owner decisions.\n' % (cfg['owner_name'], cfg['company_name'], cfg['timezone'])).encode()
        outputs[prefix + 'SOUL.md'] = payload['template/soul.md']
        for path, data in payload.items():
            if path.startswith('template/playbooks/'):
                outputs[prefix + 'work/playbooks/' + path.split('/', 2)[2]] = render(data.decode()).encode()
        outputs[prefix + 'work/context/company-snapshot.md'] = snapshot.encode()
        outputs[prefix + 'work/context/company-rules.md'] = company_rules.encode()
        workspace = str(Path(root).absolute() / 'workspaces' / aid)
        allow = ['read', 'write', 'edit', 'memory_search', 'memory_get']
        if not aid.startswith('rp-'):
            allow += [] # Delegation goes through the validated file bridge.
        spawn = a.get('spawn', [])
        if spawn:
            if any(x not in ids for x in spawn):
                raise Error('Unknown spawn target for ' + aid)
            allow += ['sessions_spawn', 'sessions_yield', 'subagents']
        declared = a.get('declared_tools')
        if declared is not None:
            allowed_declared = {'read','write','edit','memory_search','memory_get'}
            if not set(declared).issubset(allowed_declared): raise Error('Unknown declared native tool: ' + aid)
            allow = sorted(set(declared))
        model_class = a.get('model_class', 'worker')
        model = cfg.get('models', {}).get(model_class)
        entry = {'name': identity, 'workspace': workspace, 'cwd': workspace + '/work',
                 'heartbeat': {'every': '0m'},
                 'tools': {'profile': 'coding', 'allow': allow,
                           'deny': ['exec', 'process', 'browser', 'cron', 'gateway', 'group:web'] + (sorted({'read','write','edit','memory_search','memory_get'} - set(declared)) if declared is not None else []),
                           'fs': {'workspaceOnly': True}, 'elevated': {'enabled': False}},
                 'subagents': {'allowAgents': spawn}}
        if model:
            entry['model'] = {'primary': model}
        entries[aid] = entry
    fragment = {'agents': {'ownership': 'explicit', 'entries': entries,
                 'defaults': {'systemAgent': {'agentId': 'cos'}, 'bootstrapMaxChars': 40000,
                 'bootstrapTotalMaxChars': 100000, 'subagents': {'maxSpawnDepth': 1, 'maxConcurrent': 4, 'maxChildrenPerAgent': 4}}},
                'tools': {'agentToAgent': {'enabled': True, 'allow': [i for i in ids if not i.startswith('rp-')]}}}
    outputs['generated/openclaw.fragment.json'] = encoded(fragment)
    outputs['generated/roster.json'] = encoded({'agents': agents, 'company_rules_sha256': rules_hash})
    return outputs

def desired_files(root, payload, cfg):
    return dict({MANAGED + k: v for k, v in payload.items()}, **compile_files(root, payload, cfg))

def file_hash(root, name):
    path = target(root, name)
    if path.exists() and not path.is_file():
        raise Error('Managed path is not a regular file: ' + name)
    return digest(path.read_bytes()) if path.exists() else None

def plan(root, desired, old):
    actions, conflicts = [], []
    for name in sorted(set(desired) | set(old)):
        managed_name(name)
        current = file_hash(root, name)
        before = old.get(name)
        after = digest(desired[name]) if name in desired else None
        if current == after:
            continue
        if current != before:
            conflicts.append(name)
        else:
            actions.append({'path': name, 'action': 'remove' if after is None else 'add' if before is None else 'update', 'before': current, 'after': after})
    return {'changes': actions, 'conflicts': conflicts}

@contextlib.contextmanager
def locked(root):
    import fcntl
    root = Path(root)
    lockpath = target(root, '.foundation/lock')
    lockpath.parent.mkdir(parents=True, exist_ok=True)
    with lockpath.open('a') as f, contextlib.ExitStack() as stack:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another foundation operation is running')
        try:
            # A persistent worker must be stopped before changing the code it is using.
            servicepath = target(root, 'state/service.lock')
            servicepath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            service = stack.enter_context(servicepath.open('a'))
            try: fcntl.flock(service, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise Error('Stop the foundation service before updating or rendering')
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def commit(root, desired, version, old_state, operation):
    with locked(root):
        statepath = target(root, STATE)
        if read_json(statepath) != old_state:
            raise Error('Installation changed after preview; run again')
        change = plan(root, desired, old_state['files'])
        if change['conflicts']:
            raise Error('Edited managed files: ' + ', '.join(change['conflicts']) + '. Move intentional role changes into custom/roles; no files were overwritten.')
        if not change['changes'] and old_state['version'] == version:
            return {'result': 'already current', 'version': version}
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = target(root, '.foundation/backups/' + stamp)
        backup.mkdir(parents=True)
        history = {'operation': operation, 'old_state': old_state, 'changes': change['changes'], 'version': version}
        atomic(backup / 'transaction.json', encoded(history))
        # Save every old byte before the first write. No company or credential records enter this backup.
        for action in change['changes']:
            path = target(root, action['path'])
            if path.exists():
                atomic(backup / 'files' / action['path'], path.read_bytes())
        applied = []
        try:
            for action in change['changes']:
                path = target(root, action['path'])
                if file_hash(root, action['path']) != action['before']:
                    raise Error('File changed while applying: ' + action['path'])
                applied.append(action)
                if action['path'] in desired:
                    atomic(path, desired[action['path']])
                elif path.exists():
                    path.unlink()
            state = {'schema': 1, 'version': version, 'files': {k: digest(v) for k, v in desired.items()}, 'last_backup': stamp}
            atomic(statepath, encoded(state))
        except BaseException:
            for action in reversed(applied):
                path = target(root, action['path'])
                original = backup / 'files' / action['path']
                if original.exists():
                    atomic(path, original.read_bytes())
                elif path.exists():
                    path.unlink()
            atomic(statepath, encoded(old_state))
            raise
        return {'result': 'applied', 'version': version, 'files_changed': len(change['changes']), 'rollback': stamp}

def seeds(cfg):
    from backend.core import DEFAULT
    return {'config/backend.json': encoded(DEFAULT), 'config/company.json': encoded(cfg), 'company/RULES.md': b'# Company rules\n\nRecord approved company-specific rules here, with sources and dates.\n',
            'bible/SNAPSHOT.md': ('# Company snapshot\n\nCompany: %s\nOwner: %s\n\nGoals, customers, operations and current targets: not configured. Ask the keeper for a context packet; missing facts are gaps.\n' % (cfg['company_name'], cfg['owner_name'])).encode(),
            'bible/decisions.md': b'# Owner decisions\n\nNo decisions recorded.\n', 'bible/history.md': b'# History\n\nNo historical facts recorded.\n',
            'bible/CONFLICTS.md': b'# Conflicts\n\nNo conflicts recorded.\n', 'bible/inbox/README.md': b'# Bible inbox\n\nOne dated, cited note per file. The keeper verifies and files it; unresolved contradictions remain explicit.\n',
            'company/context/facts.json': b'{"facts": []}\n', 'company/context/sources.json': b'{"sources": []}\n',
            'config/services.json': b'{"services": {}}\n', 'config/automations.json': b'{"enabled": false, "jobs": []}\n',
            'custom/README.md': b'# Local customizations\n\nCore role overrides: roles/<agent-id>.md. New agents: agents/<id>/seat.json and role.md. Updates never edit this directory.\n',
            '.gitignore': b'.foundation/backups/\n.foundation/lock\nworkspaces/*/work/\nworkspaces/*/memory/\nworkspaces/*/MEMORY.md\nsecrets/\n'}

LAUNCHER = b'''#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys
root = Path(__file__).resolve().parent
if '--root' not in sys.argv and len(sys.argv) > 1:
    sys.argv.extend(['--root', str(root)])
runpy.run_path(str(root / '.foundation/managed/runtime/foundation.py'), run_name='__main__')
'''

def initialize(args):
    root = Path(args.root).absolute()
    if root.exists():
        raise Error('Destination already exists; init requires a fresh directory')
    cfg = read_json(args.config)
    meta, payload = bundle_read(args.bundle)
    # Stage the whole fresh installation beside the destination; publish it with one rename.
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.foundation-init-', dir=root.parent) as temp:
        stage = Path(temp) / 'installation'
        stage.mkdir(mode=0o700)
        for name, data in seeds(cfg).items():
            atomic(target(stage, name), data)
        local_config(stage)
        desired = desired_files(stage, payload, cfg)
        # Render final absolute workspace paths, not staging paths.
        for name in ('generated/openclaw.fragment.json',):
            desired[name] = desired[name].replace(str(stage).encode(), str(root).encode())
        for name, data in desired.items():
            atomic(target(stage, name), data)
        for a in validate_payload(payload)['agents']:
            atomic(target(stage, 'workspaces/%s/work/notes/OPEN.md' % a['id']), b'# Open items\n\nNo open work.\n')
        atomic(stage / 'foundation', LAUNCHER)
        os.chmod(stage / 'foundation', 0o700)
        atomic(stage / STATE, encoded({'schema': 1, 'version': meta['version'], 'files': {k: digest(v) for k, v in desired.items()}, 'last_backup': None}))
        os.rename(stage, root)
    return {'result': 'created', 'root': str(root), 'version': meta['version'], 'agents': len(validate_payload(payload)['agents']), 'gateway_modified': False}

def update(args):
    root = Path(args.root).absolute()
    old = read_json(target(root, STATE))
    cfg = local_config(root)
    if args.command == 'render':
        payload = {name[len(MANAGED):]: target(root, name).read_bytes() for name in old['files'] if name.startswith(MANAGED)}
        meta = {'version': old['version']}
    else:
        meta, payload = bundle_read(args.bundle)
        from backend.updates import semver
        if semver(meta['version']) < semver(old['version']):
            raise Error('Use rollback for a downgrade')
        installed_release = {name[len(MANAGED):]: expected for name, expected in old['files'].items() if name.startswith(MANAGED)}
        if meta['version'] == old['version'] and installed_release != meta['files']:
            raise Error('A release version is immutable; publish changed sources under a new version')
    desired = desired_files(root, payload, cfg)
    from backend.common import Store
    runtime_state = Store(root).snapshot()
    if any(j.get('lease') for j in runtime_state['jobs'].values()): raise Error('Stop workers before updating template code')
    preview = plan(root, desired, old['files'])
    preview.update({'from': old['version'], 'to': meta['version'], 'applied': False})
    if not args.apply:
        return preview
    result = commit(root, desired, meta['version'], old, args.command)
    from backend.common import Store, event
    with Store(root).transaction() as runtime_state: event(runtime_state, 'template-updated', version=meta['version'])
    result['runtime_schema'] = runtime_state['schema']
    result['gateway_modified'] = False
    result['next'] = 'Preview provision to update registered seats; restart gateway before fresh-session verification.'
    return result

def rollback(args):
    root = Path(args.root).absolute()
    from backend.common import Store
    if any(j.get('lease') for j in Store(root).snapshot()['jobs'].values()): raise Error('Stop workers before rollback')
    current = read_json(target(root, STATE))
    stamp = args.backup or current.get('last_backup')
    if not stamp or not re.fullmatch(r'\d{8}T\d{12}Z', stamp):
        raise Error('No valid rollback backup')
    history = read_json(target(root, '.foundation/backups/%s/transaction.json' % stamp))
    old = history['old_state']
    desired = {}
    for name in old['files']:
        backup = target(root, '.foundation/backups/%s/files/%s' % (stamp, name))
        if backup.exists():
            data = backup.read_bytes()
        else:
            data = target(root, name).read_bytes()
        if digest(data) != old['files'][name]:
            raise Error('Rollback input changed or missing: ' + name)
        desired[name] = data
    preview = plan(root, desired, current['files'])
    preview.update({'from': current['version'], 'to': old['version'], 'applied': False})
    if not args.apply:
        return preview
    return commit(root, desired, old['version'], current, 'rollback')

def doctor(args):
    root = Path(args.root).absolute()
    state = read_json(target(root, STATE))
    drift = [name for name, expected in state['files'].items() if file_hash(root, name) != expected]
    from backend.common import Store, read, fingerprint
    from backend.core import config, iso_seconds
    import time
    runtime = Store(root).snapshot(); cfg = config(root)
    provision = read(target(root, 'state/provision.json'), {'entries': {}})
    entries = read_json(target(root, 'generated/openclaw.fragment.json'))['agents']['entries']
    proofs = read(target(root, 'state/proofs.json'), {'proofs': {}})['proofs']
    native_proofs = {v['seat'] for v in proofs.values() if v.get('passed') and v.get('native') and time.time()-iso_seconds(v['at'])<7*86400}
    health = read(target(root, 'state/service-health.json'), {'ok': False})
    collector = read(target(root, 'company/context/current.json'), {'facts': {}, 'sources': {}, 'gaps': [], 'conflicts': []})
    statuses = {name: {'configured': True, 'proof_recorded': False, 'live_health': 'not checked'} for name in
                ('builder', 'research', 'judge', 'release-gate', 'merge-gate', 'context-collector', 'ops-monitor', 'wake-scheduler', 'budget-guard')}
    all_registered = all(provision['entries'].get(k) == fingerprint(v) for k,v in entries.items())
    if cfg['native'].get('config_path'):
        try:
            actual_native = read_json(Path(cfg['native']['config_path']).expanduser()).get('agents',{}).get('entries',{})
            all_registered = all_registered and all(fingerprint(actual_native.get(k)) == fingerprint(v) for k,v in entries.items())
        except (Error, OSError, ValueError): all_registered = False
    paid = cfg['paid_calls']
    budget_ready = not cfg['native'].get('paid',True) or (paid['enabled'] and paid['daily_usd'] > 0 and paid['max_usd_per_turn'] > 0)
    stale = [key for key,fact in collector['facts'].items() if fact.get('status')!='current']
    recent = bool(health.get('at')) and time.time()-iso_seconds(health['at'])<180
    open_incidents = [i for i,v in runtime['incidents'].items() if v['status']=='open']
    ready = not open_incidents and not drift and not stale and budget_ready and cfg['native']['enabled'] and all_registered and set(entries).issubset(native_proofs) and health['ok'] and recent and bool(collector['facts']) and not collector.get('gaps') and not collector.get('conflicts')
    return {'version': state['version'], 'runtime_schema': runtime['schema'], 'managed_drift': drift,
            'services': statuses, 'openclaw_on_path': bool(shutil.which(cfg['native']['binary'])),
            'native_enabled': cfg['native']['enabled'], 'all_seats_registered': all_registered,
            'fresh_native_proof_seats': sorted(native_proofs), 'service_health': health,
            'open_incidents': open_incidents, 'budget_ready': bool(budget_ready), 'stale_facts': stale, 'context_gaps': collector.get('gaps', []), 'context_conflicts': collector.get('conflicts', []),
            'gateway_modified': False, 'ready_for_autonomy': bool(ready),
            'note': 'Built-in engines are installed. Readiness needs current seat readback proofs, a recent service cycle, current sources and provider budgets; external adapters require their own proofs.'}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    release = sub.add_parser('release', help='build a clean, checksummed release archive')
    release.add_argument('--source', default=str(Path(__file__).parent))
    release.add_argument('--output', required=True)
    release.add_argument('--version', default=VERSION)
    init = sub.add_parser('init', help='create a fresh company scaffold; does not change OpenClaw')
    archive = Path(__file__).parents[1]
    default_bundle = str(archive) if archive.is_file() and zipfile.is_zipfile(archive) else None
    init.add_argument('--bundle', default=default_bundle, required=default_bundle is None)
    init.add_argument('--config', required=True)
    init.add_argument('--root', required=True)
    for command in ('update', 'render', 'rollback', 'doctor'):
        p = sub.add_parser(command)
        p.add_argument('--root', required=True)
        if command == 'update':
            p.add_argument('--bundle', required=True)
        if command in ('update', 'render', 'rollback'):
            p.add_argument('--apply', action='store_true', help='apply after the conflict check; default is preview')
        if command == 'rollback':
            p.add_argument('--backup')
    from backend.cli import parsers, COMMANDS, dispatch
    from backend.common import ServiceError
    parsers(sub)
    args = ap.parse_args()
    try:
        if args.command == 'release':
            build_release(args.source, args.output, args.version)
            return 0
        result = dispatch(args) if args.command in COMMANDS else initialize(args) if args.command == 'init' else rollback(args) if args.command == 'rollback' else doctor(args) if args.command == 'doctor' else update(args)
        print(json.dumps(result, indent=2))
        return 1 if result.get('conflicts') or result.get('managed_drift') else 0
    except (Error, ServiceError, OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        print('foundation: ' + str(e), file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())

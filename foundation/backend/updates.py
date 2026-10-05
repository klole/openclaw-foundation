"""GitHub release checks and verified downloads; never applies or restarts anything."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import ServiceError, atomic, inbox, json_bytes, now, read, safe

DEFAULT = {'enabled': True, 'repository': 'klole/openclaw-foundation',
           'channel': 'stable', 'interval_seconds': 86400, 'token_env': ''}
MAX_DOWNLOAD = 18 * 1024 * 1024
HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
         'objects.githubusercontent.com'}

def semver(value):
    match = re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?', value)
    if not match: raise ServiceError('Invalid release version')
    pre = match[4]
    parts = []
    if pre:
        for part in pre.split('.'):
            if not part or (part.isdigit() and len(part) > 1 and part[0] == '0'):
                raise ServiceError('Invalid prerelease version')
            parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(int(match[i]) for i in (1, 2, 3)) + (pre is None, tuple(parts))

def settings(cfg):
    out = dict(DEFAULT, **cfg.get('updates', {}))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', out['repository']):
        raise ServiceError('Use a GitHub owner/repository update source')
    if out['channel'] not in ('stable', 'preview'): raise ServiceError('Use stable or preview updates')
    if type(out['interval_seconds']) is not int or out['interval_seconds'] < 86400:
        raise ServiceError('Automatic update checks must be at least a day apart')
    if out['token_env'] and not re.fullmatch(r'[A-Z][A-Z0-9_]*', out['token_env']):
        raise ServiceError('Use an environment variable name for private repository access')
    return out

def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ServiceError('Update downloads must stay on approved GitHub HTTPS hosts')

class GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        validate_url(url)
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if redirected is not None and urllib.parse.urlsplit(request.full_url).hostname != urllib.parse.urlsplit(url).hostname:
            redirected.remove_header('Authorization')
        return redirected

def request(url, maximum, token='', binary=False):
    validate_url(url)
    headers = {'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json',
               'User-Agent': 'openclaw-foundation-updater', 'X-GitHub-Api-Version': '2026-03-10'}
    if token and urllib.parse.urlsplit(url).hostname == 'api.github.com':
        headers['Authorization'] = 'Bearer ' + token
    try:
        opener = urllib.request.build_opener(GitHubRedirect())
        with opener.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
            validate_url(response.geturl())
            data = response.read(maximum + 1)
    except urllib.error.HTTPError as exc:
        raise ServiceError('GitHub update request failed (HTTP %s)' % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ServiceError('GitHub update request unavailable; retry later') from None
    if len(data) > maximum: raise ServiceError('Update response exceeds size limit')
    return data

def token_for(cfg):
    return os.environ.get(cfg['token_env'], '') if cfg['token_env'] else ''

def releases(cfg):
    data = json.loads(request('https://api.github.com/repos/' + cfg['repository'] + '/releases?per_page=100', 2*1024*1024, token_for(cfg)))
    if not isinstance(data, list): raise ServiceError('Malformed GitHub release listing')
    return data

def candidate(item, cfg):
    if item.get('draft') or (item.get('prerelease') and cfg['channel'] != 'preview'): return None
    version = item.get('tag_name', '').removeprefix('v')
    try: semver(version)
    except (ServiceError, TypeError): return None
    if '-' in version and cfg['channel'] != 'preview': return None
    name = 'openclaw-foundation-' + version + '.zip'
    assets = {a.get('name'): a for a in item.get('assets', [])}
    if name not in assets or 'SHA256SUMS' not in assets: return None
    for filename in (name, 'SHA256SUMS'):
        asset = assets[filename]
        expected = 'https://github.com/' + cfg['repository'] + '/releases/download/' + item['tag_name'] + '/' + filename
        if asset.get('browser_download_url') != expected or type(asset.get('id')) is not int:
            raise ServiceError('Release asset URL does not match the configured repository')
        if type(asset.get('size')) is not int or not 0 < asset['size'] <= (MAX_DOWNLOAD if filename == name else 65536):
            raise ServiceError('Invalid release asset size')
    return {'version': version, 'tag': item['tag_name'], 'name': name,
            'url': 'https://github.com/' + cfg['repository'] + '/releases/tag/' + item['tag_name'],
            'notes': str(item.get('body') or '')[:12000], 'assets': assets,
            'repository': cfg['repository'], 'channel': cfg['channel']}

@contextlib.contextmanager
def locked(root):
    path = safe(root, 'state/updates.lock'); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield

def check(root, cfg, force=False):
    cfg = settings(cfg)
    if not cfg['enabled']: return {'enabled': False, 'checked': False}
    with locked(root):
        path = safe(root, 'state/updates.json'); state = read(path, {})
        installed = read(safe(root, '.foundation/state.json'))['version']
        if not force and state.get('repository') == cfg['repository'] and state.get('channel') == cfg['channel'] and time.time() - state.get('attempted_at', 0) < cfg['interval_seconds']:
            # A local update/rollback can change availability without another GitHub request.
            pending = state.get('release')
            state['installed'] = installed
            state['available'] = bool(pending and semver(pending['version']) > semver(installed))
            atomic(path, json_bytes(state))
            return dict(state, checked=False)
        state.update({'repository': cfg['repository'], 'channel': cfg['channel'], 'installed': installed,
                      'attempted_at': time.time(), 'checked_at': now()})
        try:
            choices = [c for c in (candidate(r, cfg) for r in releases(cfg)) if c]
            latest = max(choices, key=lambda c: semver(c['version'])) if choices else None
            state.update({'release': latest, 'available': bool(latest and semver(latest['version']) > semver(installed)), 'error': None})
            identity = cfg['repository'] + ':' + latest['version'] if latest else None
            if state['available'] and state.get('notified') != identity:
                inbox(root, 'cos', {'event': 'foundation-update-available', 'version': latest['version'],
                      'installed': installed, 'release_url': latest['url'],
                      'action': 'Tell the owner a foundation update is available. Review release notes; operator fetches, previews and approves installation. Do not install it yourself.'})
                state['notified'] = identity
        except (ServiceError, ValueError, TypeError, KeyError):
            # Preserve the last known notice and do not stop company jobs for a network failure.
            state['error'] = 'Update check failed; last known notice retained. Retry check-updates --force.'
            if (state.get('release') or {}).get('repository') != cfg['repository'] or (state.get('release') or {}).get('channel') != cfg['channel']:
                state.update({'release': None, 'available': False})
        atomic(path, json_bytes(state))
        return dict(state, checked=True)

def asset_bytes(asset, cfg, maximum):
    if cfg['token_env']:
        url = 'https://api.github.com/repos/' + cfg['repository'] + '/releases/assets/' + str(asset['id'])
    else: url = asset['browser_download_url']
    return request(url, maximum, token_for(cfg), binary=True)

def fetch(root, cfg, version=None):
    cfg = settings(cfg)
    if not cfg['enabled']: raise ServiceError('Updates are disabled in config/backend.json')
    if version: semver(version)
    choices = [c for c in (candidate(r, cfg) for r in releases(cfg)) if c and (not version or c['version'] == version)]
    if not choices: raise ServiceError('No packaged release is available on this update channel')
    release = max(choices, key=lambda c: semver(c['version']))
    installed = read(safe(root, '.foundation/state.json'))['version']
    if semver(release['version']) <= semver(installed): raise ServiceError('Use rollback for a downgrade; this release is not newer')
    checksums = asset_bytes(release['assets']['SHA256SUMS'], cfg, 65536).decode('utf-8')
    matching = [line.split() for line in checksums.splitlines() if len(line.split()) == 2 and line.split()[1].lstrip('*') == release['name']]
    if len(matching) != 1 or not re.fullmatch(r'[a-f0-9]{64}', matching[0][0]): raise ServiceError('Missing or ambiguous archive checksum')
    expected = matching[0][0]
    data = asset_bytes(release['assets'][release['name']], cfg, MAX_DOWNLOAD)
    if hashlib.sha256(data).hexdigest() != expected: raise ServiceError('Downloaded archive checksum mismatch')
    digest = release['assets'][release['name']].get('digest')
    if digest and digest != 'sha256:' + expected: raise ServiceError('GitHub asset digest mismatch')
    with locked(root):
        dest = safe(root, 'state/updates/downloads/' + release['name'])
        if dest.exists() and dest.read_bytes() != data: raise ServiceError('Cached release changed; versions are immutable')
        # Validate the manifest and all packaged files before exposing the cache to an operator.
        import foundation
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            candidate_path = Path(temp) / 'release.zip'; candidate_path.write_bytes(data)
            meta, payload = foundation.bundle_read(candidate_path)
            if meta['version'] != release['version']: raise ServiceError('Archive version does not match the release tag')
        atomic(dest, data)
        atomic(safe(root, 'state/updates/downloads/' + release['version'] + '.json'), json_bytes({'version': release['version'], 'sha256': expected, 'repository': cfg['repository'], 'release_url': release['url'], 'at': now()}))
    command = shlex.join([sys.executable, str(Path(root).absolute() / 'foundation'), 'update', '--bundle', str(dest)])
    return {'downloaded': str(dest), 'version': release['version'], 'sha256': expected,
            'release_url': release['url'], 'preview_command': command, 'apply_command': command + ' --apply',
            'next': 'Review release notes, stop the foundation worker, save a private backup, preview, then approve apply. Native provisioning/restart is separate.'}

def service_files(root, python):
    import plistlib
    root = Path(root).absolute(); python = str(Path(python).absolute())
    if any('\n' in s or '\r' in s or '%' in s for s in (str(root), python)): raise ServiceError('Unsupported service path')
    args = [python, str(root / 'foundation'), 'check-updates']
    label = 'org.openclaw.foundation-updates.' + read(safe(root, 'config/company.json'))['company_id']
    paths = []
    # Standalone daily checker works even when the model worker is stopped.
    launch = {'Label': label, 'ProgramArguments': args, 'StartInterval': 86400, 'RunAtLoad': True,
              'StandardOutPath': str(root / 'state/update-check.log'), 'StandardErrorPath': str(root / 'state/update-check-error.log')}
    files = {'generated/' + label + '.plist': plistlib.dumps(launch),
             'generated/foundation-update-check.service': ('[Unit]\nDescription=OpenClaw foundation release check\n[Service]\nType=oneshot\nExecStart=' + ' '.join('"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$') + '"' for s in args) + '\n').encode(),
             'generated/foundation-update-check.timer': b'[Unit]\nDescription=Daily OpenClaw foundation update check\n[Timer]\nOnBootSec=5m\nOnUnitActiveSec=1d\nPersistent=true\n[Install]\nWantedBy=timers.target\n'}
    for name, data in files.items(): atomic(safe(root, name), data); paths.append(str(root / name))
    return {'files': paths, 'activated': False, 'note': 'Install the launchd job or systemd user timer as described in updates.md. Checks are also built into serve. Private repository tokens need the supervisor environment.'}

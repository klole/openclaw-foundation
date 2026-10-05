"""Build the executable release plus checksum and release notes; no installed company files."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('foundation',ROOT/'foundation/foundation.py')
foundation=importlib.util.module_from_spec(spec); spec.loader.exec_module(foundation)

def build(output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    version=foundation.VERSION
    path=output/('openclaw-foundation-'+version+'.zip')
    foundation.build_release(ROOT/'foundation',path,version)
    (output/'SHA256SUMS').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n')
    (output/'VERSION').write_text(version+'\n')
    changelog=(ROOT/'foundation/CHANGELOG.md').read_text()
    match=re.search(r'^## '+re.escape(version)+r'[^\n]*\n(.*?)(?=^## |\Z)',changelog,re.M|re.S)
    if not match: raise SystemExit('Add the exact release version to CHANGELOG before publishing')
    notes='OpenClaw Foundation '+version+'\n\n'+match[1].strip()+'\n\n'
    if '-' in version: notes+='Preview candidate: use only with the preview channel; independent review is pending.\n\n'
    notes+='Daily discovery checks run automatically. Installation requires owner approval. Stop the worker, save a private backup, preview and apply; provision/restart the native gateway separately. Company data and custom agents remain local. See foundation/template/updates.md for installation and rollback.\n'
    (output/'RELEASE-NOTES.md').write_text(notes)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    build(parser.parse_args().output)

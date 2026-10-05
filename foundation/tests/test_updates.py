"""Release discovery/download checks use deterministic GitHub fixtures, never network."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
import foundation as f
from backend import maintenance, updates
from backend.common import ServiceError, atomic, json_bytes, read
from backend.core import config
from backend.cli import cycle

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name); self.root=self.base/'company'
        cfg=self.base/'config.json'; cfg.write_text(json.dumps({'company_id':'fixture','company_name':'Fixture','owner_name':'Owner','timezone':'UTC'}))
        bundle=self.build('2.1.0'); f.initialize(SimpleNamespace(root=self.root,config=cfg,bundle=bundle))
        self.cfg=config(self.root)
        self.new=self.build('2.2.0'); self.data=self.new.read_bytes(); self.sha=hashlib.sha256(self.data).hexdigest()
    def tearDown(self): self.temp.cleanup()
    def build(self,version):
        bundle=self.base/('build-'+version+'.zip')
        with contextlib.redirect_stdout(io.StringIO()): f.build_release(SOURCE,bundle,version)
        return bundle
    def release(self,version='2.2.0',prerelease=False,**kwargs):
        item={'tag_name':'v'+version,'body':'A new tested release','draft':False,'prerelease':prerelease,'assets':[]}
        for i,name in enumerate(['openclaw-foundation-'+version+'.zip','SHA256SUMS']):
            item['assets'].append({'id':i+1,'name':name,'size':len(self.data) if i==0 else 100,'browser_download_url':'https://github.com/klole/openclaw-foundation/releases/download/v'+version+'/'+name})
        item.update(kwargs); return item
    def request(self,url,maximum,token='',binary=False):
        if 'releases?' in url: return json.dumps([self.release()]).encode()
        if url.endswith('SHA256SUMS'): return (self.sha+'  openclaw-foundation-2.2.0.zip\n').encode()
        if url.endswith('.zip'): return self.data
        raise AssertionError(url)
    def test_semver_and_prerelease_order(self):
        versions=['2.1.0-alpha.2','2.1.0-alpha.10','2.1.0-beta','2.1.0-rc.1','2.1.0','2.1.1','2.10.0']
        self.assertEqual(sorted(reversed(versions),key=updates.semver),versions)
        for bad in ['02.1.0','2.1','2.1.0-rc.01','2.1.0-rc..1','2.1.0/../../file']:
            with self.assertRaises(ServiceError): updates.semver(bad)
    def test_daily_check_deduplicates_and_sends_no_company_data(self):
        with patch.object(updates,'request',side_effect=self.request) as net:
            result=updates.check(self.root,self.cfg); self.assertTrue(result['available'])
            self.assertFalse(updates.check(self.root,self.cfg)['checked']); self.assertEqual(net.call_count,1)
            updates.check(self.root,self.cfg,True)
        notices=list((self.root/'workspaces/cos/work/inbox').glob('*.json'))
        self.assertEqual(len(notices),1)
        self.assertNotIn('Fixture',net.call_args.args[0])
    def test_failed_check_is_daily_and_preserves_last_notice(self):
        with patch.object(updates,'request',side_effect=self.request): updates.check(self.root,self.cfg)
        with patch.object(updates,'request',side_effect=ServiceError('offline')) as net:
            result=updates.check(self.root,self.cfg,True); self.assertTrue(result['available']); self.assertTrue(result['error'])
            updates.check(self.root,self.cfg); self.assertEqual(net.call_count,1)
    def test_first_failure_does_not_raise_or_expose_secrets(self):
        with patch.object(updates,'request',side_effect=ServiceError('private transport details')):
            result=updates.check(self.root,self.cfg)
        self.assertFalse(result['available']); self.assertNotIn('private transport',result['error'])
    def test_disable_means_no_network(self):
        self.cfg['updates']['enabled']=False
        with patch.object(updates,'request') as net:
            self.assertFalse(updates.check(self.root,self.cfg)['enabled'])
            with self.assertRaises(ServiceError): updates.fetch(self.root,self.cfg)
            net.assert_not_called()
    def test_stable_excludes_draft_and_preview_and_unpackaged(self):
        items=[self.release('3.0.0-rc.1',True),self.release('4.0.0',draft=True),self.release('2.2.0'),self.release('5.0.0',assets=[])]
        with patch.object(updates,'releases',return_value=items):
            self.assertEqual(updates.check(self.root,self.cfg)['release']['version'],'2.2.0')
            self.cfg['updates']['channel']='preview'
            self.assertEqual(updates.check(self.root,self.cfg)['release']['version'],'3.0.0-rc.1')
    def test_source_change_clears_previous_notice_on_failure(self):
        with patch.object(updates,'request',side_effect=self.request): updates.check(self.root,self.cfg)
        self.cfg['updates']['repository']='another/foundation'
        with patch.object(updates,'request',side_effect=ServiceError('offline')):
            result=updates.check(self.root,self.cfg)
        self.assertIsNone(result['release']); self.assertFalse(result['available'])
    def test_applied_update_clears_availability_without_network(self):
        with patch.object(updates,'request',side_effect=self.request): updates.check(self.root,self.cfg)
        f.update(SimpleNamespace(root=self.root,command='update',apply=True,bundle=self.new))
        with patch.object(updates,'request') as net:
            self.assertFalse(updates.check(self.root,self.cfg)['available']); net.assert_not_called()
        maintenance.hq(self.root); self.assertNotIn('Update available:',(self.root/'generated/hq.html').read_text())
    def test_download_verifies_all_files_and_only_caches(self):
        before=read(self.root/f.STATE)
        with patch.object(updates,'request',side_effect=self.request): result=updates.fetch(self.root,self.cfg)
        self.assertEqual(Path(result['downloaded']).read_bytes(),self.data)
        self.assertEqual(read(self.root/f.STATE),before)
        self.assertTrue(result['apply_command'].endswith('--apply'))
        self.assertEqual(Path(result['downloaded']).stat().st_mode & 0o777,0o600)
    def test_bad_checksum_and_missing_checksum_fail_before_cache(self):
        for body in [b'bad',b'0'*64+b'  openclaw-foundation-2.2.0.zip\n', (self.sha+'  openclaw-foundation-2.2.0.zip\n') .encode()*2]:
            def fake(url,maximum,token='',binary=False):
                return body if url.endswith('SHA256SUMS') else self.request(url,maximum,token,binary)
            with patch.object(updates,'request',side_effect=fake):
                with self.assertRaises(ServiceError): updates.fetch(self.root,self.cfg)
        self.assertFalse((self.root/'state/updates/downloads').exists())
    def test_digest_and_version_mismatch_fail(self):
        item=self.release(); item['assets'][0]['digest']='sha256:'+'0'*64
        with patch.object(updates,'releases',return_value=[item]),patch.object(updates,'request',side_effect=self.request):
            with self.assertRaises(ServiceError): updates.fetch(self.root,self.cfg)
        self.data=self.build('2.3.0').read_bytes(); self.sha=hashlib.sha256(self.data).hexdigest()
        with patch.object(updates,'request',side_effect=self.request):
            with self.assertRaises(ServiceError): updates.fetch(self.root,self.cfg)
    def test_downgrade_and_same_version_refused(self):
        for version in ['2.0.0','2.1.0']:
            with patch.object(updates,'releases',return_value=[self.release(version)]):
                with self.assertRaises(ServiceError): updates.fetch(self.root,self.cfg,version)
    def test_external_urls_and_invalid_sources_refused(self):
        item=self.release(); item['assets'][0]['browser_download_url']='https://example.com/payload.zip'
        with self.assertRaises(ServiceError): updates.candidate(item,updates.settings(self.cfg))
        for url in ['http://github.com/payload','https://github.com.evil.test/payload','https://user:pass@github.com/payload','https://github.com:444/payload','https://127.0.0.1/payload']:
            with self.assertRaises(ServiceError): updates.validate_url(url)
        for repo in ['../private','https://github.com/a/b','a/b?x=y']:
            with self.assertRaises(ServiceError): updates.settings({'updates':{'repository':repo}})
    def test_redirect_drops_auth_and_blocks_external_hosts(self):
        req=urllib.request.Request('https://api.github.com/repos/a/b/releases/assets/1',headers={'Authorization':'Bearer fixture-token'})
        red=updates.GitHubRedirect().redirect_request(req,None,302,'moved',{},'https://release-assets.githubusercontent.com/payload')
        self.assertIsNone(red.get_header('Authorization'))
        with self.assertRaises(ServiceError): updates.GitHubRedirect().redirect_request(req,None,302,'moved',{},'https://attacker.example/payload')
    def test_hq_escapes_release_notes_and_schedulers_are_not_activated(self):
        item=self.release(body='<script>alert(1)</script>')
        with patch.object(updates,'releases',return_value=[item]): updates.check(self.root,self.cfg)
        maintenance.hq(self.root); body=(self.root/'generated/hq.html').read_text()
        self.assertIn('Update available:',body); self.assertNotIn('<script>',body)
        result=updates.service_files(self.root,sys.executable); self.assertFalse(result['activated'])
        plist=plistlib.loads(Path(result['files'][0]).read_bytes()); self.assertEqual(plist['StartInterval'],86400)
        self.assertEqual(plist['ProgramArguments'][-1],'check-updates')
        self.assertIn('OnUnitActiveSec=1d',Path(result['files'][2]).read_text())
    def test_service_cycle_checks_releases_without_model_turns(self):
        from backend.core import Runtime
        with patch.object(updates,'request',side_effect=self.request): result=cycle(Runtime(self.root))
        self.assertTrue(result['updates']['available']); self.assertFalse(result['tick']['ran'])
    def test_existing_config_receives_defaults_without_overwrite(self):
        path=self.root/'config/backend.json'; cfg=read(path); cfg.pop('updates'); atomic(path,json_bytes(cfg))
        self.assertEqual(config(self.root)['updates'],updates.DEFAULT)
        self.assertNotIn('updates',read(path))

if __name__=='__main__': unittest.main()

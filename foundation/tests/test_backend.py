"""Clean-install integration checks with no network, model spend or live gateway writes."""
import contextlib
import datetime as dt
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
import foundation as f
from backend import bridge, context, deploy, maintenance, research
from backend.cli import activate
from backend.common import ServiceError, Store, atomic, fingerprint, initial, json_bytes, now, read, safe
from backend.core import Runtime, DEFAULT

class Scripted:
    def __init__(self,fix=False,fail_stage=None): self.calls=[]; self.fix=fix; self.fail_stage=fail_stage
    def turn(self,seat,stage,request):
        self.calls.append((seat,stage,request))
        if stage==self.fail_stage: raise ServiceError('Deliberate transport outage')
        schema=request.get('schema',{})
        if stage.startswith('break-'): response={'verdict':'STANDS','reasons':[]}
        elif 'verdict' in schema:
            verdict='PASS'
            if stage=='verify' and self.fix: verdict='FIX'; self.fix=False
            response={'verdict':verdict,'confidence':.95,'reasons':['Fixture evidence checked']}
            if stage=='challenge': response['held_out_cases']=[{'input':'Summarize an unseen fixture with a missing fact','expected':'A cited summary that flags the missing fact'}]
        elif stage=='intake': response={'accepted':True,'brief':request['goal'],'done_when':'checked result'}
        elif stage=='execute': response={'artifact':'Fixture deliverable v'+str(len(self.calls)),'done':True,'evidence':['local receipt']}
        elif stage=='close': response={'summary':'Independent checker confirmed the deliverable'}
        elif stage=='size': response={'tier':'medium','reason':'A bounded role'}
        elif stage=='draft': response={'role':'# Fixture specialist\nComplete the exact bounded request and report evidence.','requirements':request['brief'].get('requirements',[]),'tests':[{'input':'Summarize the fixture','expected':'A cited summary'}],'tools':['read','write'],'helpers':[],'helpers_reason':'Reuse the independent reviewer; no additional helper needed for this bounded fixture','budget_proposal':{'monthly_usd':0,'reason':'Scripted fixture only; no provider calls or paid tool dependencies'}}
        elif stage.startswith('held-out-'): response={'artifact':'A cited summary','evidence':['fixture']}
        elif stage.startswith('scout-'):
            response={'findings':[{'finding':'The measured run produced 12 outcomes from 100 exposures.','quotes':['The measured run produced 12 outcomes from 100 exposures.'],'source':'fixture-measurement','numbers':['12','100'],'arithmetic':[],'conditions':{}}],'gaps':[]}
        elif stage.startswith('break-'): response={'verdict':'STANDS','reasons':[]}
        elif stage.startswith('director-'): response={'questions':[],'readiness_proposal':True}
        elif stage.startswith('challenger-'): response={'blocking':False,'questions':[],'reasons':[]}
        elif stage=='plan':
            due=(dt.date.today()+dt.timedelta(days=7)).isoformat()
            response={'plan':'''Goal: Increase verified outcomes
Setup: Confirm the baseline with CLM-0001
Trial TRIAL-0001: Measure a bounded change
Claims: CLM-0001
Because: CLM-0001 establishes a measured baseline
Expected change: An observable difference
Leading metric: engagement
Goal metric: outcomes
Expected lag: 7 days
Compare on: '''+due+'''
Keep if: outcomes exceed the measured baseline
Kill if: outcomes stay below the baseline
Constraint spend: 0
'''}
        elif stage=='tool-proof': response={'passed':True,'evidence':'read receipt','observed':'fixture readback\n'}
        else: raise AssertionError('Unknown fixture stage '+stage)
        return response,{'tokens':100,'transport':'scripted'}

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name); self.root=self.base/'company'
        cfg=self.base/'company.json'; cfg.write_text(json.dumps({'company_id':'fixture','company_name':'Fixture <Company>','owner_name':'Fixture Owner','timezone':'UTC','models':{}}))
        self.bundle=self.base/'2.0.0.zip'
        with contextlib.redirect_stdout(io.StringIO()): f.build_release(SOURCE,self.bundle,'2.0.0')
        f.initialize(SimpleNamespace(root=self.root,config=cfg,bundle=self.bundle))
        cfg=read(self.root/'config/backend.json'); cfg['native']['paid']=False; atomic(self.root/'config/backend.json',json_bytes(cfg))
        self.provider=Scripted(); self.runtime=Runtime(self.root,self.provider)
    def tearDown(self): self.temp.cleanup()
    def finish(self,jid,limit=50):
        for step in range(limit):
            result=self.runtime.tick(jid)
            if not result['ran']: break
            job=self.runtime.store.snapshot()['jobs'][jid]
            if job['status'] not in ('queued','retry'): return job
            if job['status']=='retry': return job
        return self.runtime.store.snapshot()['jobs'][jid]
    def cfg(self,**updates):
        cfg=read(self.root/'config/backend.json')
        for key,value in updates.items(): cfg[key].update(value)
        atomic(self.root/'config/backend.json',json_bytes(cfg)); self.runtime=Runtime(self.root,self.provider)
    def work(self,**updates):
        p={'goal':'Create a checked deliverable','maker':'plumber','checker':'push-queue'}; p.update(updates)
        return self.runtime.submit('work',p)
    def research_payload(self):
        return {'goal':'Increase verified outcomes','mode':'plan','card':{'goal_exact':'Increase verified outcomes','unit':'outcomes','baseline':12,'constraints':[{'label':'spend','max':0}]},'sources':[{'id':'fixture-measurement','class':'internal_measurement','text':'The measured run produced 12 outcomes from 100 exposures.','as_of':now()}]}
    def fact(self,value=12,date=None): return {'id':'numbers.outcomes','area':'numbers','label':'Verified outcomes','value':value,'as_of':date or now(),'source':'Fixture measurement','fresh_hours':24}
    def test_work_revisions_and_independent_fresh_check(self):
        self.provider.fix=True; job=self.work(); done=self.finish(job['id'])
        self.assertEqual(done['status'],'done'); self.assertEqual(done['results']['review']['verdict'],'PASS')
        self.assertEqual(sum(stage=='execute' for seat,stage,req in self.provider.calls),2)
        self.assertTrue(all(seat=='push-queue' for seat,stage,req in self.provider.calls if stage=='verify'))
        self.assertGreater(len(self.runtime.store.snapshot()['receipts']),4)
    def test_approval_before_calls_and_expiry(self):
        job=self.work(public=True)
        self.assertFalse(self.runtime.tick(job['id'])['ran']); self.assertFalse(self.provider.calls)
        self.runtime.approve(job['id'],'approve',expires='2000-01-01T00:00:00Z')
        self.assertFalse(self.runtime.tick(job['id'])['ran']); self.assertFalse(self.provider.calls)
        self.runtime.approve(job['id'],'approve'); self.assertEqual(self.finish(job['id'])['status'],'done')
        with self.assertRaises(ServiceError): self.runtime.approve(job['id'],'approve',actor='cos')
    def test_idempotent_submission_and_input_binding(self):
        p={'goal':'One exact task'}; a=self.runtime.submit('work',p,key='one'); b=self.runtime.submit('work',p,key='one')
        self.assertEqual(a['id'],b['id'])
        with self.assertRaises(ServiceError): self.runtime.submit('work',{'goal':'Different task'},key='one')
    def test_budget_and_paid_brake_block_before_transport(self):
        self.cfg(limits={'daily_turns':1},native={'paid':True})
        job=self.work(); self.runtime.tick(job['id']); self.assertFalse(self.provider.calls)
        self.assertIn('Paid-call brake',self.runtime.store.snapshot()['jobs'][job['id']]['error'])
        self.cfg(paid_calls={'enabled':True,'daily_usd':1,'max_usd_per_turn':.5})
        self.runtime.retry(job['id']); self.runtime.tick(job['id']); self.assertEqual(len(self.provider.calls),1)
        self.runtime.tick(job['id']); self.assertEqual(len(self.provider.calls),1) # daily cap blocks before second call
        self.cfg(limits={'daily_turns':2}); self.runtime.retry(job['id']); self.runtime.tick(job['id'])
        self.assertEqual(len(self.provider.calls),2)
    def test_failure_incident_retry_and_verified_recovery(self):
        self.provider.fail_stage='execute'; job=self.work(); self.runtime.tick(job['id']); failed=self.runtime.tick(job['id'])
        self.assertEqual(failed['status'],'retry'); self.assertEqual(self.runtime.store.snapshot()['incidents']['job-'+job['id']]['status'],'open')
        self.provider.fail_stage=None; self.runtime.retry(job['id']); done=self.finish(job['id'])
        self.assertEqual(done['status'],'done'); self.assertEqual(self.runtime.store.snapshot()['incidents']['job-'+job['id']]['status'],'verified')
    def test_lost_lease_does_not_duplicate_turn(self):
        job=self.work()
        with self.runtime.store.transaction() as state: state['jobs'][job['id']]['lease']={'token':'lost','until':'2000-01-01T00:00:00Z'}
        self.assertFalse(self.runtime.tick(job['id'])['ran']); self.assertFalse(self.provider.calls)
        self.assertEqual(self.runtime.store.snapshot()['jobs'][job['id']]['status'],'needs-attention')
    def test_context_changes_history_conflicts_staleness_and_frozen_packet(self):
        atomic(self.root/'company/context/facts.json',json_bytes({'facts':[self.fact()]})); context.collect(self.root)
        job=self.work(); frozen=job['context']['sha256']
        atomic(self.root/'company/context/import.json',json_bytes({'facts':[self.fact(20)]}))
        atomic(self.root/'company/context/sources.json',json_bytes({'sources':[{'id':'measurements','type':'json-file','path':'company/context/import.json'}]}))
        current=context.collect(self.root)
        self.assertEqual(current['facts']['numbers.outcomes']['value'],20); self.assertEqual(len(current['conflicts']),1)
        self.assertIn('12 → 20',(self.root/'bible/history.md').read_text())
        self.assertEqual(self.runtime.store.snapshot()['jobs'][job['id']]['context']['sha256'],frozen)
        atomic(self.root/'company/context/facts.json',json_bytes({'facts':[]})); (self.root/'company/context/import.json').unlink()
        current=context.collect(self.root); self.assertEqual(current['facts']['numbers.outcomes']['status'],'stale'); self.assertTrue(current['gaps'])
        self.assertEqual(self.runtime.monitor()['new_incidents'],1); self.assertEqual(self.runtime.monitor()['new_incidents'],0)
        atomic(self.root/'company/context/import.json',json_bytes({'facts':[self.fact(20)]})); context.collect(self.root); self.runtime.monitor()
        self.assertEqual(self.runtime.store.snapshot()['incidents']['source-measurements']['status'],'verified')
    def test_research_full_plan_source_gates_and_duplicates(self):
        job=self.runtime.submit('research',self.research_payload()); done=self.finish(job['id'])
        self.assertEqual(done['status'],'done',done.get('error')); self.assertTrue(done['results']['plan_gate']['pass'])
        self.assertEqual(len(research.verified(done)),1)
        self.assertEqual(sum(c['status']=='duplicate' for c in done['claims']),3)
        self.assertEqual(sum(stage.startswith('plan-verify-') for seat,stage,req in self.provider.calls),3)
        self.assertEqual(done['results']['release']['verdict'],'PASS')
    def test_fabricated_quote_number_and_wrong_goal_rejected_by_code(self):
        job=self.runtime.submit('research',self.research_payload()); research.prepare(self.root,job)
        research.check_findings(job,[{'finding':'A fabricated finding','quotes':['Not present in the source'],'source':'fixture-measurement'}],'baseline')
        research.check_findings(job,[{'finding':'There were 99 outcomes.','quotes':['The measured run produced 12 outcomes from 100 exposures.'],'source':'fixture-measurement','numbers':['99']}],'baseline')
        self.assertTrue(all(c['status']=='unsupported' for c in job['claims']))
        with self.assertRaises(ServiceError): research.check_plan(job,'Goal: A different goal\nTrial TRIAL-0001: invented')
    def test_hiring_missing_tools_then_review_provision_and_held_out_onboarding(self):
        payload={'goal':'Build a fixture specialist','requirements':['Cite evidence'],'seat':{'id':'fixture-specialist','title':'Fixture Specialist','type':'specialized','reports_to':'cos','spawn':[],'needs':['fixture-read']}}
        job=self.runtime.submit('hire',payload); self.runtime.approve(job['id'],'approve')
        result=self.runtime.tick(job['id']); self.assertEqual(result['status'],'retry'); self.assertFalse(self.provider.calls)
        atomic(self.root/'workspaces/plumber/work/proof.txt',b'fixture readback\n')
        proof=self.runtime.submit('proof',{'goal':'Prove file access','seat':'plumber','tool':'fixture-read','fixture':{'type':'read-file','path':'work/proof.txt'}})
        self.assertEqual(self.finish(proof['id'])['status'],'done')
        self.runtime.retry(job['id']); pending=self.finish(job['id']); self.assertEqual(pending['status'],'awaiting-approval')
        self.runtime.approve(job['id'],'approve'); ready=self.finish(job['id']); self.assertEqual(ready['status'],'ready-to-provision')
        self.assertTrue((self.root/'custom/agents/fixture-specialist/qualification.json').exists())
        activate(self.root,job['id'],True); self.runtime=Runtime(self.root,self.provider); done=self.finish(job['id'])
        self.assertEqual(done['status'],'done'); self.assertTrue(done['results']['onboarded'])
        entry=read(self.root/'generated/openclaw.fragment.json')['agents']['entries']['fixture-specialist']
        self.assertEqual(entry['tools']['allow'],['read','write'])
        self.assertFalse(f.doctor(SimpleNamespace(root=self.root))['ready_for_autonomy'])
    def test_proof_needs_actual_readback_and_independent_checker(self):
        atomic(self.root/'workspaces/push-queue/work/proof.txt',b'other contents')
        job=self.runtime.submit('proof',{'goal':'Prove file access','seat':'push-queue','tool':'file','fixture':{'type':'read-file','path':'work/proof.txt'}})
        self.assertEqual(self.runtime.tick(job['id'])['status'],'retry')
        self.assertFalse(read(self.root/'state/proofs.json',{'proofs':{}})['proofs'])
    def test_bridge_scope_results_and_approval_rejection(self):
        folder=self.root/'workspaces/plumber/work/requests'
        atomic(folder/'context.json',json_bytes({'action':'context','payload':{'goal':'Current context'}}))
        atomic(folder/'bad.json',json_bytes({'action':'approve','payload':{}}))
        atomic(folder/'hire.json',json_bytes({'action':'hire','payload':{'goal':'Escalate'}}))
        processed=bridge.process(self.runtime); self.assertEqual(len(processed['requests']),3)
        self.assertTrue(read(self.root/'workspaces/plumber/work/results/context.json')['ok'])
        self.assertFalse(read(self.root/'workspaces/plumber/work/results/bad.json')['ok']); self.assertFalse(read(self.root/'workspaces/plumber/work/results/hire.json')['ok'])
        self.assertEqual(bridge.process(self.runtime)['requests'],[])
    def test_backup_restore_checksum_private_and_rebind(self):
        atomic(self.root/'company/context/facts.json',json_bytes({'facts':[self.fact()]})); self.finish(self.work()['id'])
        atomic(self.root/'secrets/token.txt',b'private credential'); atomic(self.root/'state/native-backups/private.json',b'private native config')
        output=self.base/'recovery.zip'; result=maintenance.backup(self.root,output)
        self.assertEqual(output.stat().st_mode&0o777,0o600)
        import zipfile
        with zipfile.ZipFile(output) as z: self.assertFalse(any('secrets/' in n or 'native-backups/' in n for n in z.namelist()))
        fresh=self.base/'recovered'; maintenance.restore(output,fresh,True)
        self.assertEqual(read(fresh/'company/context/facts.json')['facts'][0]['value'],12)
        self.assertFalse(read(fresh/'config/backend.json')['native']['enabled'])
        self.assertEqual(len(Store(fresh).snapshot()['jobs']),1)
        f.update(SimpleNamespace(root=fresh,command='render',apply=True))
        self.assertEqual(read(fresh/'generated/openclaw.fragment.json')['agents']['entries']['cos']['workspace'],str(fresh/'workspaces/cos'))
        with self.assertRaises(ServiceError): maintenance.restore(output,fresh,True)
    def test_backup_refuses_active_work(self):
        job=self.work()
        with self.runtime.store.transaction() as state: state['jobs'][job['id']]['lease']={'token':'active','until':now()}
        with self.assertRaises(ServiceError): maintenance.backup(self.root,self.base/'busy.zip')
    def test_hygiene_archives_without_deleting_goals(self):
        memory=self.root/'workspaces/cos/memory/old.md'; atomic(memory,b'Historical fact\n'); os.utime(memory,(0,0))
        goals=self.root/'workspaces/cos/work/notes/GOALS.md'; atomic(goals,('Goal with context '*1000).encode())
        original=goals.read_bytes(); maintenance.hygiene(self.root,DEFAULT['hygiene'])
        self.assertFalse(memory.exists()); self.assertEqual((self.root/'archive/workspaces/cos/memory/old.md').read_bytes(),b'Historical fact\n')
        self.assertEqual(goals.read_bytes(),original)
        self.assertTrue(any(key.startswith('hygiene-cos-') for key in self.runtime.store.snapshot()['incidents']))
    def test_hq_escapes_private_text_and_has_job_status(self):
        job=self.work(goal='<script>malicious</script>'); maintenance.hq(self.root)
        text=(self.root/'generated/hq.html').read_text(); self.assertNotIn('<script>',text); self.assertIn('&lt;script&gt;',text); self.assertIn(job['id'],text)
    def test_explicit_schema_migration_and_newer_schema_rejection(self):
        state=initial(); state['schema']=1; state.pop('receipts'); state['jobs']['old']={'payload':{'goal':'Retain'},'attempts':2}
        atomic(self.root/'state/runtime.json',json_bytes(state))
        with self.runtime.store.transaction() as migrated: self.assertEqual(migrated['schema'],2)
        self.assertIn('old',read(self.root/'state/runtime.json')['jobs'])
        state['schema']=99; atomic(self.root/'state/runtime.json',json_bytes(state))
        with self.assertRaises(ServiceError): self.runtime.store.snapshot()
    def test_native_provision_previews_preserves_and_rolls_back(self):
        native=self.base/'native.json'; atomic(native,json_bytes({'gateway':{'port':19000},'agents':{'ownership':'explicit','entries':{}}}))
        self.cfg(native={'config_path':str(native),'binary':'fixture-openclaw'})
        before=native.read_bytes(); preview=deploy.provision(self.root,self.runtime.cfg)
        self.assertEqual(len(preview['changed_seats']),18); self.assertEqual(before,native.read_bytes())
        with patch('backend.deploy.subprocess.run',return_value=SimpleNamespace(returncode=0)):
            applied=deploy.provision(self.root,self.runtime.cfg,True)
        self.assertEqual(read(native)['gateway']['port'],19000)
        deploy.provision_rollback(self.root,self.runtime.cfg,applied['receipt'],True)
        self.assertEqual(native.read_bytes(),before)
    def test_native_schema_failure_collision_and_external_drift_refused(self):
        native=self.base/'native.json'; atomic(native,json_bytes({'agents':{'ownership':'explicit','entries':{}}})); self.cfg(native={'config_path':str(native)})
        before=native.read_bytes()
        with patch('backend.deploy.subprocess.run',return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(ServiceError): deploy.provision(self.root,self.runtime.cfg,True)
        self.assertEqual(before,native.read_bytes())
        atomic(native,json_bytes({'agents':{'entries':{'cos':{'name':'Another company'}}}}))
        with self.assertRaises(ServiceError): deploy.provision(self.root,self.runtime.cfg)
    def test_service_files_and_archive_runtime_cli(self):
        files=deploy.service_files(self.root,sys.executable); self.assertFalse(files['activated'])
        import plistlib
        plist=plistlib.loads(Path(files['launchd']).read_bytes()); self.assertEqual(plist['ProgramArguments'][2],'serve')
        p=subprocess.run([sys.executable,str(self.root/'foundation'),'serve','--once'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr); self.assertTrue(read(self.root/'state/service-health.json')['ok'])
        self.assertFalse(f.doctor(SimpleNamespace(root=self.root))['ready_for_autonomy'])
    def test_idle_specialist_and_controls_do_not_wake(self):
        self.cfg(wake={'enabled':True}); result=self.runtime.wake()
        self.assertEqual(result['woken'],['cos'])
        self.assertEqual(self.runtime.wake()['woken'],[])
    def test_update_refuses_running_service_and_keeps_runtime_state(self):
        job=self.work(); self.finish(job['id']); before=self.runtime.store.snapshot()['jobs']
        lock=self.root/'state/service.lock'
        with lock.open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(f.Error): f.update(SimpleNamespace(root=self.root,command='render',apply=True))
        f.update(SimpleNamespace(root=self.root,command='render',apply=True)); self.assertEqual(self.runtime.store.snapshot()['jobs'],before)
    def test_native_recovery_keeps_auth_private_and_separate(self):
        profile=self.base/'native-state'; atomic(profile/'agents/cos/auth-profiles.json',b'{"fixture_auth":"private"}')
        cfgfile=self.base/'native.json'; atomic(cfgfile,b'{"agents":{"entries":{}}}')
        self.cfg(native={'config_path':str(cfgfile),'state_dir':str(profile)})
        output=self.base/'full.zip'; maintenance.backup(self.root,output,self.runtime.cfg['native'])
        app=self.base/'app-restored'; maintenance.restore(output,app,True)
        self.assertFalse((app/'native').exists())
        native=self.base/'profile-restored'; maintenance.restore_native(output,native,True)
        self.assertEqual((native/'state/agents/cos/auth-profiles.json').read_bytes(),b'{"fixture_auth":"private"}')
        self.assertEqual((native/'config.json').stat().st_mode&0o777,0o600)
    def test_schedules_do_not_overlap_pending_jobs(self):
        atomic(self.root/'config/automations.json',json_bytes({'enabled':True,'jobs':[{'id':'fixture-watch','kind':'work','every_seconds':300,'payload':{'goal':'Read the new approved export'}}]}))
        first=self.runtime.schedule()['scheduled']; self.assertEqual(len(first),1)
        with self.runtime.store.transaction() as state: state['schedules']['fixture-watch']['next']=0
        self.assertEqual(self.runtime.schedule()['scheduled'],[])
        self.assertEqual(len(self.runtime.store.snapshot()['jobs']),1)
    def test_bible_proposal_is_reviewed_before_canonical_write(self):
        from backend.cli import dispatch
        folder=self.root/'workspaces/librarian/work/requests'
        proposal={'goal':'File the verified fixture baseline','snapshot':'# Verified fixture snapshot\n','facts':[self.fact()]}
        atomic(folder/'proposal.json',json_bytes({'action':'bible-propose','payload':proposal})); bridge.process(self.runtime)
        job=read(self.root/'workspaces/librarian/work/results/proposal.json')['result']; jid=job['id']
        before=(self.root/'bible/SNAPSHOT.md').read_bytes()
        with self.assertRaises(ServiceError): dispatch(SimpleNamespace(root=self.root,command='bible-apply',job=jid,apply=True))
        self.runtime.approve(jid,'approve'); self.assertEqual(self.finish(jid)['status'],'done')
        preview=dispatch(SimpleNamespace(root=self.root,command='bible-apply',job=jid,apply=False)); self.assertFalse(preview['applied']); self.assertEqual(before,(self.root/'bible/SNAPSHOT.md').read_bytes())
        result=dispatch(SimpleNamespace(root=self.root,command='bible-apply',job=jid,apply=True)); self.assertTrue(result['applied'])
        self.assertIn('Verified fixture',(self.root/'bible/SNAPSHOT.md').read_text()); self.assertEqual((self.root/'archive/bible'/jid/'bible/SNAPSHOT.md').read_bytes(),before)
    def test_one_parent_signoff_covers_exact_helper_with_budget_ceiling(self):
        original=self.provider.turn
        helper={'goal':'Independently summarize evidence','seat':{'id':'fixture-helper','title':'Fixture Helper','type':'control','reports_to':'fixture-parent','spawn':[],'declared_tools':['read','write']},'requirements':['Cite evidence'],'cost_reason':'No paid tools needed','budget_proposal':{'monthly_usd':0,'reason':'Scripted fixture only'}}
        def propose(seat,stage,request):
            response,meta=original(seat,stage,request)
            if stage=='draft' and request['brief']['seat']['id']=='fixture-parent': response['helpers']=[helper]
            return response,meta
        self.provider.turn=propose
        p={'goal':'Build a fixture parent','requirements':['Cite evidence'],'seat':{'id':'fixture-parent','title':'Fixture Parent','type':'specialized','reports_to':'cos','spawn':[]}}
        parent=self.runtime.submit('hire',p); self.assertEqual(self.finish(parent['id'])['status'],'awaiting-approval')
        self.runtime.approve(parent['id'],'approve'); self.assertEqual(self.finish(parent['id'])['status'],'ready-to-provision')
        activated=activate(self.root,parent['id'],True); child=activated['helper_jobs'][0]
        self.runtime=Runtime(self.root,self.provider); self.assertEqual(self.finish(parent['id'])['status'],'done')
        self.assertEqual(self.finish(child)['status'],'ready-to-provision')
        self.assertNotIn(child,self.runtime.store.snapshot()['approvals'])
        activate(self.root,child,True); self.runtime=Runtime(self.root,self.provider); self.assertEqual(self.finish(child)['status'],'done')
        with self.runtime.store.transaction() as state: state['jobs'][child]['results']['draft']['budget_proposal']['monthly_usd']=100
        self.assertFalse(self.runtime.authorized(self.runtime.store.snapshot(),self.runtime.store.snapshot()['jobs'][child]))
    def test_repository_checks_and_self_review_rejection(self):
        repo=self.base/'repo'; repo.mkdir()
        def git(*args): return subprocess.run(['git']+list(args),cwd=repo,capture_output=True,text=True,check=True).stdout.strip()
        git('init'); git('config','commit.gpgsign','false'); git('config','core.hooksPath',os.devnull); git('config','user.email','fixture@example.invalid'); git('config','user.name','Fixture')
        (repo/'check.py').write_text('assert 2 + 2 == 4\n'); git('add','check.py'); git('commit','-m','fixture'); sha=git('rev-parse','HEAD')
        self.cfg(repositories={'fixture':{'path':str(repo),'checks':[[sys.executable,'check.py']]}})
        p={'goal':'Review the exact fixture change','repository':'fixture','head':sha,'pr':1,'maker':'plumber','reviewer':'push-queue','artifact':'fixture diff'}
        job=self.runtime.submit('gate',p); self.runtime.approve(job['id'],'approve'); self.assertEqual(self.finish(job['id'])['status'],'release-ready')
        self.assertEqual(self.runtime.store.snapshot()['jobs'][job['id']]['results']['checks']['head'],sha)
        bad=dict(p,maker='push-queue'); job=self.runtime.submit('gate',bad); self.runtime.approve(job['id'],'approve')
        self.assertEqual(self.runtime.tick(job['id'])['status'],'retry')
        self.assertIn('own change',self.runtime.store.snapshot()['jobs'][job['id']]['error'])
    def test_declared_read_only_tools_are_not_promoted_to_write(self):
        directory=self.root/'custom/agents/fixture-reader'; atomic(directory/'seat.json',json_bytes({'id':'fixture-reader','title':'Fixture Reader','type':'control','reports_to':'cos','spawn':[],'declared_tools':['read']})); atomic(directory/'role.md',b'# Reader\nRead the provided files.\n')
        f.update(SimpleNamespace(root=self.root,command='render',apply=True)); entry=read(self.root/'generated/openclaw.fragment.json')['agents']['entries']['fixture-reader']
        self.assertEqual(entry['tools']['allow'],['read']); self.assertIn('write',entry['tools']['deny']); self.assertIn('edit',entry['tools']['deny'])
    def test_duplicate_pending_hire_id_and_nonfinite_confidence_rejected(self):
        p={'goal':'Build a bounded role','seat':{'id':'fixture-reserved','title':'Reserved','type':'control','reports_to':'cos','spawn':[]}}
        self.runtime.submit('hire',p,key='first')
        with self.assertRaises(ServiceError): self.runtime.submit('hire',p,key='second')
        original=self.provider.turn
        def invalid(seat,stage,request):
            result,meta=original(seat,stage,request)
            if stage=='verify': result['confidence']=float('nan')
            return result,meta
        self.provider.turn=invalid; job=self.work(); self.assertEqual(self.finish(job['id'])['status'],'retry')
        self.assertIn('finite',self.runtime.store.snapshot()['jobs'][job['id']]['error'])
    def test_configured_model_family_overrides_reach_plan_verifiers(self):
        self.cfg(research={'verifier_models':['alpha/reviewer','beta/reviewer'],'required_model_families':['alpha','beta']})
        job=self.runtime.submit('research',self.research_payload()); self.assertEqual(self.finish(job['id'])['status'],'done')
        models=[request['model_override'] for seat,stage,request in self.provider.calls if stage.startswith('plan-verify-')]
        self.assertEqual(models,['alpha/reviewer','beta/reviewer','alpha/reviewer'])
    def test_completed_wake_does_not_feed_its_own_inbox_and_off_is_honored(self):
        self.cfg(wake={'enabled':True})
        job=self.runtime.wake()['woken']; self.assertEqual(job,['cos'])
        jid=self.runtime.store.snapshot()['wakes']['cos']['job']; self.assertEqual(self.finish(jid)['status'],'done')
        self.assertEqual(list((self.root/'workspaces/cos/work/inbox').glob('*.json')),[])
        atomic(self.root/'workspaces/cos/work/notes/GOALS.md',b'# Goals\nWake: OFF\n- [ ] Paused goal\n')
        with self.runtime.store.transaction() as state: state['wakes']['cos']['last']=0
        self.assertEqual(self.runtime.wake()['woken'],[])
    def test_bridge_research_cannot_read_private_paths_or_assert_primary_class(self):
        folder=self.root/'workspaces/plumber/work/requests'
        payload=self.research_payload(); payload['sources']=[{'id':'private','path':'secrets/token.txt','class':'internal_measurement'}]
        atomic(self.root/'secrets/token.txt',b'private fixture')
        atomic(folder/'private.json',json_bytes({'action':'research','payload':payload})); bridge.process(self.runtime)
        self.assertFalse(read(self.root/'workspaces/plumber/work/results/private.json')['ok']); self.assertFalse(self.runtime.store.snapshot()['jobs'])
        payload=self.research_payload(); atomic(folder/'inline.json',json_bytes({'action':'research','payload':payload})); bridge.process(self.runtime)
        result=read(self.root/'workspaces/plumber/work/results/inline.json')['result']
        self.assertEqual(result['payload']['sources'][0]['class'],'tertiary')

if __name__=='__main__': unittest.main()

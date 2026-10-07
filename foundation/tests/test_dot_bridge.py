"""Auth, isolation, durable admission and webhook lifecycle tests; synthetic records only."""
import base64
import http.client
import ipaddress
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.common import ServiceError
from backend.dot_auth import Database, OAuth, SCOPES, pkce, random
from backend.dot_bridge import Bridge, Adapter
from backend.dot_events import Events, EVENT, signature, https_post
from backend.dot_http import Server
from backend.dot_cli import Application

class FakeAdapter:
    def __init__(self): self.sent=[]; self.fail=False; self.done=False
    def call(self,owner,name,args):
        if name=='foundation_agents': return {'agents':[{'id':'cos','name':'COS','role':'coordination'},{'id':'hidden','name':'Hidden'}]}
        if name=='foundation_send':
            self.sent.append(args.copy())
            if self.fail: raise ServiceError('Uncertain network result')
            return {'task_id':'upstream-fixture','status':'accepted'}
        return {'task_id':args['task_id'],'status':'completed' if self.done else 'pending','reply':'Fixture reply' if self.done else None}

class DotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.config={'public_url':'https://fixture.example/dot','port':8766,'default_agent':'cos','adapter_command':['/fixture/client']}
        self.store=Database(self.root); self.oauth=OAuth(self.store,self.config)
        self.password=self.oauth.owner('owner',['cos']); self.other=self.oauth.owner('other',['cos'])
        self.client=self.oauth.register({'redirect_uris':['https://chatgpt.com/connector_platform_oauth_redirect']})['client_id']
        self.deliveries=[]; self.reject=False
        self.events=Events(self.store,self.oauth,self.post)
        self.adapter=FakeAdapter(); self.bridge=Bridge(self.store,self.oauth,self.events,self.config,self.adapter)
        self.tokens=self.login('owner',self.password); self.auth=self.oauth.authenticate(self.tokens['access_token'])
    def tearDown(self): self.temp.cleanup()
    def login(self,name,password):
        verifier=random(); args={'client_id':self.client,'redirect_uri':'https://chatgpt.com/connector_platform_oauth_redirect','response_type':'code','resource':self.oauth.resource,'code_challenge_method':'S256','code_challenge':pkce(verifier),'state':'fixture','scope':' '.join(SCOPES)}
        handle,nonce=self.oauth.begin(args); destination=self.oauth.consent(handle,nonce,name,password)
        code=parse_qs(urlsplit(destination).query)['code'][0]
        self.assertEqual(parse_qs(urlsplit(destination).query)['iss'][0],self.config['public_url'])
        params={'grant_type':'authorization_code','resource':self.oauth.resource,'client_id':self.client,'code':code,'redirect_uri':args['redirect_uri'],'code_verifier':verifier}
        result=self.oauth.exchange(params)
        with self.assertRaises(ServiceError): self.oauth.exchange(params)
        return result
    def post(self,url,body,headers):
        payload=json.loads(body); self.deliveries.append((payload,headers,body))
        self.assertEqual(headers['webhook-signature'].split()[0],signature(self.secret(),headers['webhook-id'],headers['webhook-timestamp'],body))
        if self.reject: return 503,b'{}'
        return 200,json.dumps({'challenge':payload.get('challenge','')}).encode()
    def secret(self): return 'whsec_'+base64.b64encode(b'x'*32).decode()
    def subscribe(self,auth=None,conversation=None):
        return self.events.subscribe(auth or self.auth,{'name':EVENT,'arguments':{'conversation':conversation} if conversation else {},'delivery':{'mode':'webhook','url':'https://callbacks.example/fixture','secret':self.secret()}})
    def send(self,auth=None,**kwargs):
        return self.bridge.send(auth or self.auth,dict({'message':'Fixture authorized task','conversation':'fixture','idempotency_key':'fixture-key'},**kwargs))
    def allow_poll(self):
        with self.store.transaction() as db:
            for k,j in self.store.items(db,'jobs'): j['after']=0; self.store.put(db,'jobs',k,j)
    def test_scoped_discovery_and_private_tasks(self):
        self.assertEqual([a['id'] for a in self.bridge.agents(self.auth)['agents']],['cos'])
        receipt=self.send(); other=self.oauth.authenticate(self.login('other',self.other)['access_token'])
        with self.assertRaises(ServiceError): self.bridge.status(other,receipt['task_id'])
        self.assertEqual(self.bridge.conversation(other,'fixture')['tasks'],[])
        with self.assertRaises(ServiceError): self.send(agent='hidden')
    def test_key_is_owner_scoped_and_immutable(self):
        first=self.send(); self.assertEqual(first,self.send())
        with self.assertRaises(ServiceError): self.send(message='Changed request')
        other=self.oauth.authenticate(self.login('other',self.other)['access_token'])
        self.assertNotEqual(first['task_id'],self.send(other)['task_id'])
    def test_real_reply_and_restart(self):
        self.subscribe(); first=self.send(); self.bridge.tick(); self.adapter.done=True; self.allow_poll()
        newstore=Database(self.root); newoauth=OAuth(newstore,self.config); events=Events(newstore,newoauth,self.post)
        restarted=Bridge(newstore,newoauth,events,self.config,self.adapter); restarted.tick()
        self.assertEqual(restarted.status(self.auth,first['task_id'])['status'],'completed')
        self.assertEqual(len(self.adapter.sent),1)
        self.assertEqual(self.deliveries[-1][0]['data']['task_id'],first['task_id'])
        self.assertNotIn('reply',self.deliveries[-1][0]['data'])
    def test_uncertain_admission_preserves_exact_key(self):
        self.adapter.fail=True; first=self.send()
        for _ in range(3): self.allow_poll(); self.bridge.tick()
        self.assertEqual(len(self.adapter.sent),3)
        self.assertTrue(all(x==self.adapter.sent[0] for x in self.adapter.sent))
        self.assertEqual(self.bridge.status(self.auth,first['task_id'])['status'],'admission_unknown')
        self.bridge.tick(); self.assertEqual(len(self.adapter.sent),3)
    def test_filter_unsubscribe_revocation_and_expiry(self):
        sub=self.subscribe(conversation='other-conversation'); self.send(); self.bridge.tick()
        self.assertEqual(len(self.deliveries),1)
        params={'name':EVENT,'arguments':{'conversation':'other-conversation'},'delivery':{'mode':'webhook','url':'https://callbacks.example/fixture'}}
        self.events.unsubscribe(self.auth,params); self.events.unsubscribe(self.auth,params)
        self.subscribe(); self.oauth.disable('owner'); self.allow_poll(); self.bridge.tick()
        with self.assertRaises(ServiceError): self.oauth.authenticate(self.tokens['access_token'])
        self.assertEqual(len(self.deliveries),2)
    def test_failed_challenge_stores_no_subscription(self):
        self.reject=True
        with self.assertRaises(ServiceError): self.subscribe()
        with self.store.transaction() as db: self.assertEqual(self.store.items(db,'subscriptions'),[])
    def test_duplicate_subscription_refresh(self):
        first=self.subscribe(); second=self.subscribe(); self.assertEqual(first['id'],second['id'])
        with self.store.transaction() as db: self.assertEqual(len(self.store.items(db,'subscriptions')),1)
    def test_failed_delivery_retries_same_event_id(self):
        self.subscribe(); self.reject=True; self.send(); self.bridge.tick()
        body=self.deliveries[-1][2]; ident=self.deliveries[-1][1]['webhook-id']
        self.reject=False
        with self.store.transaction() as db:
            for k,v in self.store.items(db,'deliveries'): v['after']=0; self.store.put(db,'deliveries',k,v)
        self.events.deliver(); self.assertEqual(body,self.deliveries[-1][2]); self.assertEqual(ident,self.deliveries[-1][1]['webhook-id'])
    def test_oauth_refresh_resource_and_revoke(self):
        params={'grant_type':'refresh_token','client_id':self.client,'refresh_token':self.tokens['refresh_token'],'resource':'https://wrong.example/mcp'}
        with self.assertRaises(ServiceError): self.oauth.exchange(params)
        params['resource']=self.oauth.resource; new=self.oauth.exchange(params)
        with self.assertRaises(ServiceError): self.oauth.exchange(params)
        with self.assertRaises(ServiceError): self.oauth.authenticate(self.tokens['access_token'])
        self.oauth.revoke(new['refresh_token'],self.client)
        with self.assertRaises(ServiceError): self.oauth.authenticate(new['access_token'])
    def test_login_and_pkce_rejected(self):
        with self.assertRaises(ServiceError): self.oauth.register({'redirect_uris':['https://attacker.example/callback']})
        params={'client_id':self.client,'redirect_uri':'https://chatgpt.com/connector_platform_oauth_redirect','response_type':'code','resource':self.oauth.resource,'code_challenge_method':'plain','code_challenge':'x'*43}
        with self.assertRaises(ServiceError): self.oauth.begin(params)
    def test_expired_access_and_owner_reset_stop_delivery(self):
        self.subscribe(); self.send()
        with self.store.transaction() as db:
            for k,item in self.store.items(db,'access'): item['until']=0; self.store.put(db,'access',k,item)
        with self.assertRaises(ServiceError): self.oauth.authenticate(self.tokens['access_token'])
        self.oauth.owner('owner',['cos']); self.bridge.tick()
        self.assertEqual(len(self.deliveries),1)
    def test_bad_password_csrf_and_pkce(self):
        verifier=random(); params={'client_id':self.client,'redirect_uri':'https://chatgpt.com/connector_platform_oauth_redirect','response_type':'code','resource':self.oauth.resource,'code_challenge_method':'S256','code_challenge':pkce(verifier)}
        handle,nonce=self.oauth.begin(params)
        with self.assertRaises(ServiceError): self.oauth.consent(handle,'wrong-nonce','owner',self.password)
        with self.assertRaises(ServiceError): self.oauth.consent(handle,nonce,'owner','wrong-password')
        handle,nonce=self.oauth.begin(params); url=self.oauth.consent(handle,nonce,'owner',self.password)
        code=parse_qs(urlsplit(url).query)['code'][0]
        exchange={'grant_type':'authorization_code','resource':self.oauth.resource,'client_id':self.client,'code':code,'redirect_uri':params['redirect_uri'],'code_verifier':random()}
        with self.assertRaises(ServiceError): self.oauth.exchange(exchange)
        exchange['code_verifier']=verifier; self.oauth.exchange(exchange)
    def test_scope_and_schema_cannot_be_bypassed(self):
        restricted=dict(self.auth,scope='agents:read')
        with self.assertRaises(ServiceError): self.bridge.call(restricted,'foundation_send',{'message':'Fixture','conversation':'fixture','idempotency_key':'test'})
        with self.assertRaises(ServiceError): self.bridge.call(self.auth,'foundation_send',{'message':'Fixture','conversation':'fixture','idempotency_key':'test','principal':'other'})
        with self.assertRaises(ServiceError): self.bridge.call(self.auth,'approve',{})
    def test_receipt_adapter_normalizes_existing_relay(self):
        from types import SimpleNamespace
        result=SimpleNamespace(returncode=0,stdout=json.dumps({'id':'fixture-task','state':'completed','reply':'Fixture reply'}))
        with patch('backend.dot_bridge.subprocess.run',return_value=result) as run:
            normalized=Adapter(self.config).call({},'foundation_send',{'message':'literal $(test); text'})
        self.assertEqual(normalized['task_id'],'fixture-task'); self.assertEqual(normalized['status'],'completed')
        self.assertNotIn('shell',run.call_args.kwargs)

    def test_callback_blocks_private_dns_and_redirect_scheme(self):
        with self.assertRaises(ServiceError): https_post('http://callbacks.example',b'{}',{})
        with patch('backend.dot_events.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ServiceError): https_post('https://callbacks.example',b'{}',{})
    def test_rate_limits(self):
        self.store.rate('fixture','owner',1)
        with self.assertRaises(ServiceError): self.store.rate('fixture','owner',1)
    def test_http_transport_and_discovery(self):
        app=Application(self.config,self.store,self.oauth,self.events,self.bridge); server=Server(('127.0.0.1',0),app)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            conn.request('GET','/.well-known/oauth-authorization-server/dot'); response=conn.getresponse(); metadata=json.loads(response.read()); self.assertEqual(metadata['issuer'],self.config['public_url'])
            conn.request('POST','/dot/mcp',json.dumps({'jsonrpc':'2.0','id':1,'method':'server/discover'}),{'Content-Type':'application/json'}); response=conn.getresponse(); result=json.loads(response.read()); self.assertEqual(result['result']['supportedVersions'],['2026-07-28'])
            conn.request('POST','/dot/mcp',json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'foundation_agents'}}),{'Content-Type':'application/json'}); response=conn.getresponse(); response.read(); self.assertEqual(response.status,401)
            conn.request('POST','/dot/mcp',json.dumps({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'foundation_agents'}}),{'Content-Type':'application/json','Authorization':'Bearer '+self.tokens['access_token']}); response=conn.getresponse(); result=json.loads(response.read()); self.assertEqual(response.status,200); self.assertFalse(result['result']['isError'])
        finally: server.shutdown(); server.server_close(); thread.join()

if __name__=='__main__': unittest.main()

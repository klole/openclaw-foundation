"""Invite-only OAuth 2.1 for a single operator-owned messaging installation."""
import base64
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit
from .common import ServiceError, atomic, json_bytes

SCOPES = ['agents:read', 'messages:send', 'messages:read', 'events:subscribe']
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'))
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def random(): return secrets.token_urlsafe(32)
def pkce(value): return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).decode().rstrip('=')

class Database:
    def __init__(self, root):
        self.root = Path(root).absolute()
        if self.root.is_symlink(): raise ServiceError('Dot root cannot be a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'dot.sqlite3'
        if self.path.is_symlink(): raise ServiceError('Dot database cannot be a symlink')
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, value TEXT, PRIMARY KEY(kind,key))')
        os.chmod(self.path, 0o600)
    @contextlib.contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()
    def get(self, db, kind, key):
        row = db.execute('SELECT value FROM records WHERE kind=? AND key=?', (kind,key)).fetchone()
        return json.loads(row[0]) if row else None
    def put(self, db, kind, key, value):
        db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind,key,canonical(value)))
    def delete(self, db, kind, key): db.execute('DELETE FROM records WHERE kind=? AND key=?', (kind,key))
    def items(self, db, kind): return [(k,json.loads(v)) for k,v in db.execute('SELECT key,value FROM records WHERE kind=?',(kind,)).fetchall()]
    def rate(self, category, identity, limit, window=60):
        key = category + ':' + digest(identity)
        with self.transaction() as db:
            item = self.get(db,'rates',key) or {'until':0,'count':0}
            if item['until'] <= time.time(): item = {'until':time.time()+window,'count':0}
            if item['count'] >= limit: raise ServiceError('Rate limit exceeded')
            item['count'] += 1; self.put(db,'rates',key,item)
            for table in ('logins','codes','access','refresh'):
                for ident,record in self.items(db,table):
                    if record['until']<time.time(): self.delete(db,table,ident)
            for ident, record in self.items(db,'rates'):
                if record['until'] < time.time()-3600: self.delete(db,'rates',ident)

class OAuth:
    def __init__(self, store, config):
        self.store=store; self.config=config; self.issuer=config['public_url']; self.resource=self.issuer+'/mcp'
    def metadata(self):
        return {'issuer':self.issuer,'authorization_response_iss_parameter_supported':True,
                'authorization_endpoint':self.issuer+'/authorize','token_endpoint':self.issuer+'/token',
                'registration_endpoint':self.issuer+'/register','revocation_endpoint':self.issuer+'/revoke',
                'response_types_supported':['code'],'grant_types_supported':['authorization_code','refresh_token'],
                'token_endpoint_auth_methods_supported':['none'],'code_challenge_methods_supported':['S256'],
                'scopes_supported':SCOPES}
    def protected(self): return {'resource':self.resource,'authorization_servers':[self.issuer],'scopes_supported':SCOPES}
    def owner(self, principal, agents, command=None):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,62}',principal): raise ServiceError('Invalid principal')
        password=random(); salt=secrets.token_hex(16)
        record={'salt':salt,'hash':hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex(),
                'agents':agents,'enabled':True,'command':command,'generation':random()}
        with self.store.transaction() as db:
            self.store.put(db,'owners',principal,record)
            for key,family in self.store.items(db,'families'):
                if family['owner']==principal: self.store.delete(db,'families',key)
        return password
    def disable(self, principal):
        with self.store.transaction() as db:
            owner=self.store.get(db,'owners',principal)
            if not owner: raise ServiceError('Unknown owner')
            owner['enabled']=False; self.store.put(db,'owners',principal,owner)
            for key,item in self.store.items(db,'families'):
                if item['owner']==principal: self.store.delete(db,'families',key)
    def redirect_ok(self, uri):
        return uri in self.config.get('redirect_uris',['https://chatgpt.com/connector_platform_oauth_redirect'])
    def register(self, params):
        uris=params.get('redirect_uris')
        if not isinstance(uris,list) or not uris or len(uris)>5 or any(not self.redirect_ok(x) for x in uris): raise ServiceError('Redirect URI is not operator-allowlisted')
        if params.get('token_endpoint_auth_method','none')!='none': raise ServiceError('Only public PKCE clients are supported')
        cid=random()
        item={'client_id':cid,'redirect_uris':uris,'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code']}
        with self.store.transaction() as db:
            if len(self.store.items(db,'clients'))>=1000: raise ServiceError('OAuth client registration capacity reached')
            self.store.put(db,'clients',cid,item)
        return item
    def begin(self, params):
        with self.store.transaction() as db:
            client=self.store.get(db,'clients',params.get('client_id',''))
            if not client or params.get('redirect_uri') not in client['redirect_uris']: raise ServiceError('Invalid client or redirect URI')
            if params.get('response_type')!='code' or params.get('resource')!=self.resource or params.get('code_challenge_method')!='S256': raise ServiceError('Authorization code, exact resource and S256 PKCE are required')
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}',params.get('code_challenge','')): raise ServiceError('Invalid PKCE challenge')
            scopes=params.get('scope',' '.join(SCOPES)).split()
            if not scopes or not set(scopes)<=set(SCOPES): raise ServiceError('Invalid scopes')
            nonce=random(); handle=random()
            self.store.put(db,'logins',digest(handle),dict(params,scope=' '.join(scopes),until=time.time()+600,csrf=digest(nonce)))
        return handle,nonce
    def consent(self, handle, nonce, principal, password):
        with self.store.transaction() as db:
            login=self.store.get(db,'logins',digest(handle)); owner=self.store.get(db,'owners',principal)
            if not login or login['until']<time.time() or not hmac.compare_digest(login['csrf'],digest(nonce)): raise ServiceError('Login expired; restart connection')
            self.store.delete(db,'logins',digest(handle))
            # A dummy scrypt computation keeps nonexistent identities from bypassing login cost.
            salt=(owner or {}).get('salt','0'*32)
            value=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
            if not owner or not owner['enabled'] or not hmac.compare_digest(value,owner['hash']): raise ServiceError('Invalid owner credentials')
            code=random(); family=random()
            self.store.put(db,'families',family,{'owner':principal,'until':time.time()+30*86400,'generation':owner['generation']})
            self.store.put(db,'codes',digest(code),dict(login,owner=principal,family=family,until=time.time()+120))
        query={'code':code,'state':login.get('state',''),'iss':self.issuer}
        return login['redirect_uri']+'?'+urlencode(query)
    def active(self, db, family):
        item=self.store.get(db,'families',family)
        owner=self.store.get(db,'owners',(item or {}).get('owner',''))
        if not item or item['until']<=time.time() or not owner or not owner['enabled'] or item['generation']!=owner['generation']: raise ServiceError('Account authorization expired or revoked')
        return item['owner'],owner
    def tokens(self, db, item):
        access=random(); refresh=random()
        record={k:item[k] for k in ('owner','family','client_id','scope','resource')}
        self.store.put(db,'access',digest(access),dict(record,until=time.time()+3600))
        self.store.put(db,'refresh',digest(refresh),dict(record,until=time.time()+30*86400))
        return {'access_token':access,'refresh_token':refresh,'token_type':'Bearer','expires_in':3600,'scope':item['scope']}
    def exchange(self, params):
        with self.store.transaction() as db:
            if params.get('resource')!=self.resource: raise ServiceError('Wrong OAuth resource')
            kind=params.get('grant_type'); key=digest(params.get('code' if kind=='authorization_code' else 'refresh_token',''))
            table='codes' if kind=='authorization_code' else 'refresh' if kind=='refresh_token' else None
            if not table: raise ServiceError('Unsupported grant')
            item=self.store.get(db,table,key)
            if not item or item['until']<=time.time() or item['client_id']!=params.get('client_id'): raise ServiceError('Invalid or expired grant')
            self.active(db,item['family'])
            if kind=='authorization_code':
                verifier=params.get('code_verifier','')
                if not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}',verifier) or not hmac.compare_digest(pkce(verifier),item['code_challenge']) or params.get('redirect_uri')!=item['redirect_uri']: raise ServiceError('PKCE or redirect mismatch')
            self.store.delete(db,table,key)
            # Old refresh tokens cannot be replayed, and no parallel active access token remains after rotation.
            if kind=='refresh_token':
                for ident, old in self.store.items(db,'access'):
                    if old['family']==item['family']: self.store.delete(db,'access',ident)
            return self.tokens(db,item)
    def authenticate(self, token, scope=None):
        with self.store.transaction() as db:
            item=self.store.get(db,'access',digest(token))
            if not item or item['until']<=time.time() or item['resource']!=self.resource: raise ServiceError('Invalid access token')
            principal,owner=self.active(db,item['family'])
            if scope and scope not in item['scope'].split(): raise ServiceError('Insufficient OAuth scope')
            return dict(item,principal=principal,owner_record=owner)
    def revoke(self, token, client_id):
        with self.store.transaction() as db:
            item=self.store.get(db,'refresh',digest(token)) or self.store.get(db,'access',digest(token))
            if item and item['client_id']==client_id: self.store.delete(db,'families',item['family'])

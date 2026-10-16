import importlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('PROMPT_DB_PATH',str(tmp_path/'skills.sqlite3'))
    monkeypatch.setenv('PROMPT_DEV_USER','user-1')
    monkeypatch.delenv('PROMPT_AI_BASE_URL',raising=False)
    monkeypatch.delenv('PROMPT_AI_MODELS',raising=False)
    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as client:
        client.headers['Origin']='http://localhost:5173'
        yield client


def skill():
    return dict(id='skill-1',slug='crear-rubricas',name='Crear rúbricas',description='Crea rúbricas a partir de criterios',category='assessment',tags=[],language='es',stage='primary',author='Docente',license='CC-BY-SA-4.0',version='1.0.0',instructions='Genera una rúbrica con criterios observables.',parameters=[dict(id='context',name='Contexto',type='textarea',description='',required=True,options=[])],procedure=['Analiza los criterios.'],resources=[],examples=[dict(language='ca-valencia',input='Exposició oral',output='Rúbrica observable')],outputFormat='Markdown',requirements='',restrictions='Sin datos personales',mode='instructions',ownerId='oidc:user-1',source='personal',status='draft',visibility='private',reviewed=True,revision=1)


def test_skills_crud_ownership_and_conflict(client):
    saved=client.put('/api/skills/skill-1',json=skill() | {'ownerId':'forged','visibility':'public'}).json()
    assert saved['ownerId']=='oidc:user-1'
    assert saved['visibility']=='private'
    assert len(client.get('/api/skills').json()['skills'])==1
    assert client.put('/api/skills/skill-1',json=skill() | {'name':'Editada'}).status_code==409
    assert client.put('/api/skills/skill-1',json=skill() | {'name':'Editada','revision':2}).status_code==200
    assert client.delete('/api/skills/skill-1').status_code==204
    assert client.get('/api/skills').json()=={'skills':[]}


def test_skills_do_not_cross_users(client):
    import app.main as main
    client.put('/api/skills/skill-1',json=skill())
    main.DEV_USER='user-2'
    assert client.get('/api/skills').json()=={'skills':[]}
    assert client.delete('/api/skills/skill-1').status_code==204
    client.put('/api/skills/skill-1',json=skill() | {'name':'Otra'})
    main.DEV_USER='user-1'
    assert client.get('/api/skills').json()['skills'][0]['name']=='Crear rúbricas'
    main.DEV_USER=''
    assert client.get('/api/skills').status_code==401


@pytest.mark.parametrize('patch',[{'slug':'bad--slug'},{'instructions':''},{'resources':[{'path':'../run.sh','content':'bad'}]},{'parameters':[{'id':'file','type':'file'}]},{'revision':True},{'source':'builtin'}])
def test_invalid_skills(client,patch):
    assert client.put('/api/skills/skill-1',json=skill() | patch).status_code==400


def test_skills_require_trusted_origin_and_size_limit(client):
    assert client.put('/api/skills/skill-1',json=skill(),headers={'Origin':'https://evil.invalid'}).status_code==403
    assert client.put('/api/skills/skill-1',content=b' ' * 1_500_001,headers={'Content-Type':'application/json'}).status_code==413
    assert client.put('/api/skills/skill-1',content=b'{}',headers={'Content-Type':'text/plain'}).status_code==415
    del client.headers['Origin']
    assert client.delete('/api/skills/skill-1').status_code==403


def inference(**patch):
    return dict(task='execute',skill=skill(),values={'context':'4.º Primaria'},language='ca-valencia',provider='configured',model='test-model',consent=True,prepared='Petición revisada: responde en ca-valencia') | patch


def configured(monkeypatch):
    monkeypatch.setenv('PROMPT_AI_BASE_URL','http://127.0.0.1:11434/v1')
    monkeypatch.setenv('PROMPT_AI_MODELS','test-model')


def test_no_inference_by_default(client):
    assert client.get('/api/skills/capabilities').json()=={'providers':[]}
    assert client.post('/api/skills/infer',json=inference()).status_code==503


def test_inference_constraints(client,monkeypatch):
    configured(monkeypatch)
    for patch in [dict(consent=False),dict(model='unknown'),dict(language='xx'),dict(values={}),dict(skill=skill()|{'mode':'external'}),dict(skill=skill()|{'reviewed':False}),dict(prepared='')]:
        assert client.post('/api/skills/infer',json=inference(**patch)).status_code==400
    assert client.post('/api/skills/infer',json=inference(skill=skill()|{'ownerId':'oidc:another'})).status_code==403


def test_provider_execution_and_errors(client,monkeypatch):
    configured(monkeypatch)
    real_client=httpx.AsyncClient
    sent=[]
    def handler(request):
        data=json.loads(request.content)
        sent.append(data)
        return httpx.Response(200,json={'choices':[{'message':{'content':'Rúbrica en valencià'}}]})
    monkeypatch.setattr('app.skills.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    response=client.post('/api/skills/infer',json=inference())
    assert response.json()=={'text':'Rúbrica en valencià'}
    assert sent[0]['messages'][1]['content']==inference()['prepared']
    assert 'tools' not in sent[0]
    assert client.post('/api/skills/infer',json=inference(task='create',goal='Crear rúbricas')).status_code==200
    def failure(request):
        return httpx.Response(401,json={'sensitive':'provider response not to expose'})
    monkeypatch.setattr('app.skills.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(failure),**kw))
    assert client.post('/api/skills/infer',json=inference()).json()=={'detail':'provider unavailable'}
    assert 'base' not in client.get('/api/skills/capabilities').json()['providers'][0]


def test_inference_rate_limit(client,monkeypatch):
    configured(monkeypatch)
    real_client=httpx.AsyncClient
    monkeypatch.setattr('app.skills.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(lambda request:httpx.Response(500)),**kw))
    for _ in range(10):
        assert client.post('/api/skills/infer',json=inference()).status_code==502
    assert client.post('/api/skills/infer',json=inference()).status_code==429

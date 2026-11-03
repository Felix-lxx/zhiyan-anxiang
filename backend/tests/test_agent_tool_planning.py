from copy import deepcopy
from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.operations import DrillCommand
from app.schemas.agent import GoalCreate
from app.services.agent_contract import goal_constraints
from app.services.agent_tool_planning import recommend, planning_context
from test_exercise_world import exercise


def test_natural_floor_constraints_do_not_confuse_building_numbers():
    assert goal_constraints(GoalCreate(request_id='contract-00001', goal='疏散三号楼三层和十二层居民，降低暴露，不要走北门')) == {
        'floors': [3, 12], 'objective': 'low_exposure', 'forbidden_exits': ['north']}
    assert goal_constraints(GoalCreate(request_id='contract-00002', goal='疏散三号楼居民'))['floors'] == []
    with pytest.raises(HTTPException):
        goal_constraints(GoalCreate(request_id='contract-00003', goal='疏散三至六层居民'))
    with pytest.raises(HTTPException):
        goal_constraints(GoalCreate(request_id='contract-00004', goal='先不要疏散三层居民'))


def test_floor_and_exit_constraints_reach_domain_forecast_and_recovery(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    floor = data['simulation']['residents'][0]['floor']
    expected = {p['id'] for p in data['simulation']['residents'] if p['floor'] == floor and p['status'] != 'evacuated'}
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id': 'contract-actual-0001', 'goal': '分流疏散目标居民', 'floors': [floor],
        'forbidden_exits': ['north'], 'objective': 'low_exposure', 'priority_assist': False, 'pause_for_review': True})
    assert response.status_code == 201, response.text
    run = response.json()
    assert set(run['scope']['resident_ids']) == expected
    assert run['planning']['objective'] == 'low_exposure'
    assert run['planning']['event_sequence'] == run['execution']['event_sequence']
    assert all(p['exit'] == 'south' for c in run['candidates'] for p in c['assignments'])
    assert {item['tool'] for item in run['planning']['trace']} >= {'observe_scene', 'search_knowledge', 'check_routes_resources', 'compare_candidates'}
    with operations.SessionLocal() as session:
        assert not list(session.scalars(select(DrillCommand)))
    refreshed = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers,
                            json={'action':'replan','revision':run['revision']})
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert new['scope']['forbidden_exits'] == ['north']
    assert new['planning']['mode'] == 'deterministic'
    assert all(p['exit'] == 'south' for c in new['candidates'] for p in c['assignments'])
    candidate=next((c for c in new['candidates'] if c['can_apply']),None)
    if candidate:
        approved=client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers,
            json={'action':'approve','revision':new['revision'],'candidate_id':candidate['id']})
        assert approved.status_code==200,approved.text
        assert all(step['exit']=='south' for step in approved.json()['steps'] if step.get('resident_ids'))


def proposal():
    return {'goal': '降低烟气暴露并疏散居民', 'scope': {'building_name': '一号楼', 'priority_assist': True,
        'completion':'到场与清点', 'floors':[3], 'forbidden_exits':[]}, 'summary': {'total':8,'priority':2},
        'knowledge': {'hits': [{'id':'K1','title':'已发布资料','content':'引用内容'}]},
        'planning': {'at_seconds':10,'event_sequence':5,'objective_label':'优先降低暴露',
            'recommended_candidate_id':'candidate-1','mode':'deterministic','trace':[],'checks':[]},
        'candidates':[{'id':'candidate-1','can_apply':True,'metrics':{}}, {'id':'candidate-2','can_apply':False,'metrics':{}}]}


def call(name, args=None):
    return {'role':'assistant','tool_calls':[{'id':'tool-'+name,'type':'function',
        'function':{'name':name,'arguments':args or {}}}]}


def test_model_reads_tools_and_repairs_rejected_candidate_without_executing(monkeypatch):
    monkeypatch.setattr('app.services.agent_tool_planning.provider_status', lambda _: {'configured':True})
    sequence = iter([
        call('observe_scene'),call('search_knowledge'),call('assess_knowledge'),call('compare_candidates'),
        call('recommend_candidate', {'candidate_id':'candidate-2','explanation':'这个方案虽然不可执行但试图选中它','citations':['K1']}),
        call('recommend_candidate', {'candidate_id':'candidate-1','explanation':'改选工具确认可执行的方案，仍需人工批准','citations':['K1']}),
    ])
    requests=[]
    def model(messages, tools, **kwargs):
        requests.append(deepcopy(messages))
        return next(sequence)
    monkeypatch.setattr('app.services.agent_tool_planning.call_tools',model)
    result=recommend(proposal(),True)
    assert result['mode']=='model_tools'
    assert result['recommended_candidate_id']=='candidate-1'
    assert any(item['status']=='rejected' for item in result['trace'])
    assert 'error' in requests[-1][-1]['content']
    assert len(requests)==6


def test_fake_knowledge_reference_and_unregistered_tools_never_become_success(monkeypatch):
    monkeypatch.setattr('app.services.agent_tool_planning.provider_status',lambda _: {'configured':True})
    sequence=iter([call('observe_scene'),call('search_knowledge'),call('assess_knowledge'),call('compare_candidates'),
        call('recommend_candidate',{'candidate_id':'candidate-1','explanation':'引用列表看似合法，但说明中伪造 [K999]','citations':['K1']}),
        call('dispatch_robot',{'target':'unknown'})])
    monkeypatch.setattr('app.services.agent_tool_planning.call_tools',lambda *args,**kwargs:next(sequence))
    result=recommend(proposal(),True)
    assert result['mode']=='deterministic'
    assert result['recommended_candidate_id']=='candidate-1'
    assert '预算' in result['notice']
    assert sum(item['status']=='rejected' for item in result['trace'])==2


def test_changed_experience_cannot_be_cited_as_current_recommendation(monkeypatch):
    monkeypatch.setattr('app.services.agent_tool_planning.provider_status',lambda _: {'configured':True})
    value=proposal()
    value['knowledge']['hits'][0].update(category='experience',applicability={'status':'different','label':'条件有差异'})
    value['knowledge']['hits'][0]['experience']={'actual':{'arrived':2}}
    filtered=planning_context(value)['search_knowledge']['hits'][0]
    assert '不作为本场推荐依据' in filtered['content'] and 'experience' not in filtered
    assert value['knowledge']['hits'][0]['content']=='引用内容'
    sequence=iter([call('observe_scene'),call('search_knowledge'),call('assess_knowledge'),call('compare_candidates'),
        call('recommend_candidate',{'candidate_id':'candidate-1','explanation':'依据不同人数的经验 [K1] 推断本场效果','citations':['K1']}),
        call('recommend_candidate',{'candidate_id':'candidate-1','explanation':'改用本场领域工具的有效预测，经验需复核','citations':[]})])
    monkeypatch.setattr('app.services.agent_tool_planning.call_tools',lambda *args,**kwargs:next(sequence))
    result=recommend(value,True)
    assert result['mode']=='model_tools'
    assert result['citations']==[]
    assert any(item['status']=='rejected' for item in result['trace'])


def test_offline_planning_never_calls_provider(monkeypatch):
    monkeypatch.setattr('app.services.agent_tool_planning.call_tools',lambda *args,**kwargs:pytest.fail('Unexpected model request'))
    assert recommend(proposal(),False)['mode']=='deterministic'

"""Human reports change the world; verification changes task credit separately."""
from copy import deepcopy

from app.services.fire_environment import EnvironmentTimeline
from app.services.agent_task_graph import case_task_view
from app.services.task_guidance import guidance_view
from test_exercise_world import exercise  # noqa: F401
from test_community_training import community_run  # noqa: F401


def test_report_releases_worker_but_does_not_verify_or_rewrite_replay(community_run):
    client, headers, root, data, tick, clock, _ = community_run
    task = next(t for t in data['tasks'] if t['kind'] == 'power_off')
    url = root+'/tasks/'+task['id']+'/actions'
    assert data['simulation']['world']['task_workflow_version'] == 2
    assert client.post(url, headers=headers, json={'action':'report','evidence':'已检查充电棚断电结果'}).status_code == 409
    assert client.post(url, headers=headers, json={'action':'accept'}).status_code == 200
    arrived = client.post(url, headers=headers, json={'action':'arrive'}).json()
    at = arrived['elapsed_seconds']
    assert client.post(url, headers=headers, json={'action':'report','evidence':'已核对现场断电操作'}).status_code == 409
    ready = tick(at+task['duration_seconds']+1)
    current = next(t for t in ready['tasks'] if t['id']==task['id'])
    assert current['can_report'] and not current['can_submit']
    assert guidance_view(ready, current)['next_action']['kind'] == 'report'
    assert next(t for t in case_task_view([], ready) if t['id']==task['id'])['can_report']
    assert not ready['simulation']['environment']['power_off']
    assert client.post(url, headers=headers, json={'action':'submit','evidence':'未报告动作不能跳过核验'}).status_code == 409
    assert client.post(url, headers=headers, json={'action':'report','evidence':'短'}).status_code == 422
    invite = client.post(root+'/participant-invite', headers=headers).json()
    participant_root = root.replace('/drills/', '/participant/drills/')
    for role, expected in [('居民代表', 403), ('物业/网格员', 409)]:
        member = client.post(participant_root+'/join?code='+invite['code'],
            json={'role':role, 'display_name':'其他参演者'}).json()
        denied = client.post(participant_root+'/tasks/'+task['id']+'/actions?code='+invite['code'],
            json={'action':'report', 'evidence':'不能覆盖责任人的动作报告', 'participant_token':member['token']})
        assert denied.status_code == expected
    reported = client.post(url, headers=headers, json={'action':'report','evidence':'现场已断电并核对设备状态'}).json()
    current = next(t for t in reported['tasks'] if t['id']==task['id'])
    assert current['status']=='verifying' and current['can_submit']
    assert guidance_view(reported, current)['next_action']['kind'] == 'submit'
    assert current['evidence'] is None and reported['simulation']['environment']['power_off']
    assert not any(s['state']=='task' for s in reported['simulation']['environment']['response_staff'])
    other = next(t for t in reported['tasks'] if t['kind']=='manual')
    reused = client.post(root+'/tasks/'+other['id']+'/actions', headers=headers, json={'action':'accept'}).json()
    assert next(t for t in reused['tasks'] if t['id']==other['id'])['staff_id'] == current['staff_id']
    retried = client.post(url, headers=headers, json={'action':'report','evidence':'同一动作重复报告不重复执行'}).json()
    assert sum(e['event_type']=='task.action_reported' for e in retried['events']) == 1
    assert client.post(url, headers=headers, json={'action':'release'}).status_code == 409
    replay = client.get(root+'/replay?at_seconds='+str(at), headers=headers).json()
    assert not replay['simulation']['environment']['power_off']
    verified = client.post(url, headers=headers, json={'action':'submit','evidence':'已核对动作报告及设备处置结果'}).json()
    assert next(t for t in verified['tasks'] if t['id']==task['id'])['status']=='completed'
    assert verified['simulation']['environment']['power_off']
    assert any(s['state']=='task' for s in verified['simulation']['environment']['response_staff'])
    # Verifying an earlier action cannot release the worker's new assignment.
    assert client.patch(root+'/state', headers=headers, json={'action':'end'}).status_code == 200
    archive = client.get(root+'/archive', headers=headers).json()['archive']['data']
    saved = next(t for t in archive['final_state']['tasks'] if t['id']==task['id'])
    assert saved['action_reported_at'] == current['action_reported_at']
    assert saved['completed_at'] is not None and saved['staff_id'] == current['staff_id']
    assert saved['action_report_evidence'] != saved['evidence']
    assert other['id'] in archive['unresolved']['tasks']


def test_legacy_frozen_world_keeps_its_original_completion_effect(community_run):
    _, _, _, data, *_ = community_run
    world=deepcopy(data['simulation']['world'])
    world.pop('task_workflow_version', None)
    event={'event_type':'task.completed','elapsed_seconds':10,'sequence':1,'payload':{'kind':'power_off'}}
    assert EnvironmentTimeline(world,[event]).at(11)[1]['power_off']
    world['task_workflow_version']=2
    assert not EnvironmentTimeline(world,[event]).at(11)[1]['power_off']
    event['event_type']='task.action_reported'
    assert EnvironmentTimeline(world,[event]).at(11)[1]['power_off']

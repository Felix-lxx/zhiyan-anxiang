"""Read projections must explain actual execution without generating commands."""
from copy import deepcopy
from types import SimpleNamespace

from app.services.agent_execution import coordination_view


def fixture():
    person = {"id": "resident-1", "label": "居民 1", "status": "moving", "waiting_for_edge": "stairs-1", "queue_seconds": 19,
              "smoke_exposure": 7, "route_reachable": False}
    run = SimpleNamespace(scope={"resident_ids": [person["id"]]}, status="executing", reason="人员正在撤离", revision=2, candidates=[])
    observed = {"id": person["id"], "label": "居民 1", "arrived": False, "blocked": True, "smoke_exposure": 7, "queue_seconds": 19}
    steps = [{"kind": "residents.assign", "status": "executing", "reason": "排队", "resident_ids": [person["id"]],
              "execution": {"attention": [observed], "stalled": False}}]
    data = {"elapsed_seconds": 32, "latest_event_sequence": 12, "status": "running",
            "simulation": {"residents": [person], "spatial_network": {"edges": [{"id": "stairs-1", "name": "二层楼梯"}]}},
            "robot": {"state": "moving", "battery": 80, "reason": "前往楼门"}}
    return run, data, steps


def test_coordination_locates_risk_and_queue_without_mutating_inputs():
    run, data, steps = fixture()
    original = deepcopy((vars(run), data, steps))
    view = coordination_view(run, data, steps)
    assert view["next_action"]["resident_id"] == "resident-1"
    assert view["issues"][0]["severity"] == "danger"
    assert view["bottlenecks"] == [{"edge_id": "stairs-1", "name": "二层楼梯", "waiting": 1,
                                     "resident_id": "resident-1", "max_wait_seconds": 19}]
    assert len(view["lanes"]) == 4
    assert (vars(run), data, steps) == original


def test_review_and_rollcall_keep_human_decision_as_next_action():
    run, data, steps = fixture()
    run.status = "needs_review"
    assert coordination_view(run, data, steps)["next_action"]["kind"] == "replan"
    run.status = "awaiting_rollcall"
    assert coordination_view(run, data, steps)["next_action"]["kind"] == "rollcall"
    data["status"] = "paused"
    assert coordination_view(run, data, steps)["status"] == "paused"


def test_robot_wait_is_not_reported_as_resident_progress():
    run, data, steps = fixture()
    run.scope["robot_broadcast"] = True
    steps.append({"kind": "robot.command", "status": "waiting", "reason": "等待真实到位", "resident_ids": [],
                  "execution": {"attention": [], "stalled": False}})
    view = coordination_view(run, data, steps)
    assert view["robot"]["included"] and view["robot"]["steps_total"] == 1
    assert view["robot"]["steps_completed"] == 0
    assert next(p for p in view["lanes"] if p["id"] == "resources")["state"] == "waiting"


def test_supervision_counts_beyond_the_display_sample():
    run, data, steps = fixture()
    data["simulation"]["residents"] = [{**data["simulation"]["residents"][0], "id": f"resident-{i}"} for i in range(10)]
    run.scope["resident_ids"] = [p["id"] for p in data["simulation"]["residents"]]
    view = coordination_view(run, data, steps)
    assert view["issue_count"] == 10 and len(view["issues"]) == 6
    assert view["bottlenecks"][0]["waiting"] == 10


def test_closed_door_links_to_exact_control_before_routine_case_tasks():
    run, data, steps = fixture()
    run.scope['include_case_tasks'] = True
    data['tasks'] = [{'id':'task', 'title':'燃气核验', 'status':'active'}]
    data['simulation']['environment'] = {'indoor': {'zones': [], 'doors': [
        {'id':'door-2-east', 'label':'二层东侧房门', 'state':'closed',
         'occupants':[{'id':'resident-1','kind':'resident'}]}]}}
    view = coordination_view(run, data, steps)
    assert view['next_action']['kind'] == 'indoor'
    assert view['next_action']['door_id'] == 'door-2-east'
    data['simulation']['environment']['indoor']['doors'][0]['state']='open'
    assert coordination_view(run, data, steps)['next_action']['kind'] == 'focus'


def test_ready_verification_links_to_specific_task_before_routine_work():
    run, data, steps = fixture()
    run.scope['include_case_tasks'] = True
    data['simulation']['residents'][0].update(route_reachable=True, smoke_exposure=0)
    data['tasks'] = [
        {'id':'gas', 'kind':'gas_off', 'title':'燃气核验', 'status':'executing',
         'responsible_role':'物业', 'remaining_seconds':1, 'overdue':True},
        {'id':'door', 'kind':'containment', 'title':'房门核验', 'status':'verifying',
         'responsible_role':'网格员', 'remaining_seconds':20, 'verification_ready':True}]
    before = deepcopy(data)
    view = coordination_view(run, data, steps)
    assert view['next_action']['task_id'] == 'door'
    assert view['next_action']['label'] == '立即核验：房门核验'
    assert view['case_tasks']['verification_ready'] == 1
    assert view['case_tasks']['overdue'] == 1
    assert data == before


def test_release_wave_completion_and_manual_takeover_do_not_overwrite_drill_state():
    run, data, steps = fixture()
    steps[0].update(release_wave=1, status='completed')
    data['simulation']['residents'][0]['building_id'] = 'building-1'
    data['simulation']['residents'][0]['status'] = 'evacuated'
    view = coordination_view(run, data, steps)
    assert view['status'] == 'executing'
    assert view['release_waves'][0]['state'] == 'completed'
    assert view['release_waves'][0]['arrived'] == 1
    assert view['release_waves'][0]['buildings'] == [{'id':'building-1','name':'building-1','total':1,'arrived':1}]
    assert '集合核验' in view['release_waves'][0]['reason']

    run.status = 'taken_over'
    steps[0].update(status='waiting', reason='等待广播')
    view = coordination_view(run, data, steps)
    assert view['status'] == 'taken_over'
    assert view['release_waves'][0]['state'] == 'stopped'
    assert '人工' in view['release_waves'][0]['reason']

    run.status = 'waiting'
    data['status'] = 'paused'
    steps[0].update(status='failed', reason='水源失效')
    view = coordination_view(run, data, steps)
    assert view['status'] == 'paused'
    assert view['release_waves'][0]['state'] == 'blocked'
    assert view['release_waves'][0]['reason'] == '水源失效'

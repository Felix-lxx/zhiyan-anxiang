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

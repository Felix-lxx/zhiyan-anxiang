from types import SimpleNamespace

from app.services.command_feedback import command_feedback


def test_old_active_receipt_is_reconciled_after_more_than_24_commands():
    events = [SimpleNamespace(
        sequence=i, elapsed_seconds=i, actor="导演", message=f"指令 {i}",
        event_type="command.accepted",
        payload={"command_id": f"command-{i}", "kind": "residents.assign" if i == 1 else "road.reopen",
                 "arguments": {"resident_ids": ["resident-1"]} if i == 1 else {}, "event_ids": []},
    ) for i in range(1, 31)]
    person = {"id": "resident-1", "label": "居民 1", "status": "moving", "progress": .5, "remaining_seconds": 20}
    receipt = next(item for item in command_feedback(events, {"residents": [person]}, None, 30, "running") if item["id"] == "command-1")
    assert receipt["status"] == "executing"
    person["status"] = "evacuated"
    receipt = next(item for item in command_feedback(events, {"residents": [person]}, None, 60, "running") if item["id"] == "command-1")
    assert receipt["status"] == "completed"
    assert receipt["completed_count"] == 1

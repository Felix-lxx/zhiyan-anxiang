"""Finite, named training staff shared by search, escort and goal planning."""
from copy import deepcopy


def roster(world):
    if world.get("response_staff") is not None:
        return deepcopy(world["response_staff"])
    # Historical worlds keep a deterministic four-person simulation roster.
    return [{"id": f"escort-{i+1}", "name": f"模拟值守员 {i+1}", "role": "物业/网格员",
             "available": True, "source": "simulation", "origin": deepcopy(world["robot_origin"])} for i in range(4)]


def capacity(world):
    return sum(p.get("available", True) for p in roster(world or {"robot_origin": {"x": 18, "y": 53}}))


def projection(world, helpers, events):
    staff = roster(world)
    for person in staff:
        binding = next((e["payload"] for e in reversed(events)
            if e["event_type"] == "staff.bound" and e["payload"].get("staff_id") == person["id"]), None)
        if binding:
            person.update(participant_id=binding.get("participant_id"), responsible=binding.get("responsible"))
        assignments = [h for h in helpers.values() if h.get("staff_id") == person["id"]]
        active = next((h for h in assignments if h["state"] != "completed"), None)
        person.update(state=active["state"] if active else "available" if person.get("available", True) else "off_duty",
                      resident_id=active["resident_id"] if active else None,
                      completed_count=sum(h["state"] == "completed" for h in assignments))
    return staff

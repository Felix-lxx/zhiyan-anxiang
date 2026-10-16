"""Clone event history, never copy future events or participant credentials."""
from copy import deepcopy
from uuid import uuid4


def fork_events(events, username):
    chosen = [e for e in events if e.event_type not in {"participant.joined", "drill.ended", "drill.branched"}]
    ids = {e.id: str(uuid4()) for e in chosen}
    result = []
    for e in chosen:
        payload = deepcopy(e.payload)
        for key in ("participant_token", "token_hash"): payload.pop(key, None)
        if payload.get("target_event_id") in ids: payload["target_event_id"] = ids[payload["target_event_id"]]
        if payload.get("mission_id") in ids: payload["mission_id"] = ids[payload["mission_id"]]
        if isinstance(payload.get("event_ids"), list): payload["event_ids"] = [ids.get(key, key) for key in payload["event_ids"]]
        # Historical evidence stays intact, but pending tasks are actionable by
        # the branch director; old mobile credentials never authorize this fork.
        if e.event_type.startswith("task.") and "participant_id" in payload:
            payload["source_participant_id"] = payload["participant_id"]
            payload["participant_id"] = "director:"+username
        result.append(dict(id=ids[e.id], sequence=e.sequence, elapsed_seconds=e.elapsed_seconds, event_type=e.event_type, actor=e.actor, message=e.message, payload=payload))
    return result

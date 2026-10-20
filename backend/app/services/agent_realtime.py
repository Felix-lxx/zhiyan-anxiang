"""Connection-scoped, read-only projection for a director's latest goal plan.

The scene and plan have separate revisions: approval and cancellation can happen
while the scene clock is paused. Never cache this private projection in the
shared drill snapshot or send it to participant sockets.
"""
from hashlib import sha256

from sqlalchemy import select

from app.models.agent import AgentRun


class AgentProjection:
    def __init__(self):
        self._key = None
        self._value = None

    def read(self, session, drill, username: str, data: dict):
        from app.services.agent_workflow import buildings_for, run_payload

        run = session.scalar(select(AgentRun).where(
            AgentRun.drill_session_id == drill.id, AgentRun.actor == username,
        ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1))
        key = (drill.id, username, data["state_version"], data["status"],
               (run.id, run.revision, run.status, run.updated_at.isoformat()) if run else None)
        if key == self._key:
            return self._value
        value = {"id": drill.id, "state_version": "agent:" + sha256(repr(key).encode()).hexdigest(),
                 "source_version": data["state_version"], "drill_status": data["status"],
                 "buildings": buildings_for(data), "runs": [run_payload(session, run, data)] if run else []}
        self._key, self._value = key, value
        return value

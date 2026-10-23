"""Bind the command application to the incumbent domain handlers.

The adapter is the explicit remaining migration boundary. The application itself
does not import API routes; handlers can be extracted behind this port one at a time.
"""
from fastapi import HTTPException
from sqlalchemy import select

from app.application.drill_commands import CommandRejected, DrillCommandApplication
from app.models.operations import RobotAgent
from app.services.movement_commands import assign_residents, command_robot
from app.schemas.operations import (DrillAction, EventInject, ResidentCommand, RobotCommand,
    VehicleCommand, SearchAssignment, ParticipantAction, TaskAssignment, TaskAction, DirectorConfig)


def translate(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else '指令未通过现场校验。'
        raise CommandRejected(exc.status_code, detail, exc.headers) from exc


class ExistingDrillRuntime:
    def __init__(self, operations):
        self.operations = operations

    def require_drill(self, session, drill_id, username):
        return translate(self.operations.require_drill, session, drill_id, username)

    def snapshot(self, session, drill):
        return translate(self.operations.snapshot, session, drill)

    def append_event(self, session, drill, kind, actor, message, payload):
        return translate(self.operations.append_event, session, drill, kind, actor, message, payload)

    def elapsed(self, drill):
        return self.operations.effective_elapsed(drill)

    def simulation(self, session, drill, events, elapsed):
        return translate(self.operations.simulation_state, drill, events, elapsed, session=session)

    def robot(self, session, drill, events, elapsed):
        agent = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
        return translate(self.operations.robot_runtime, agent, events, elapsed)

    def resident_preview(self, session, drill, payload, events):
        return translate(self.operations.spatial_preview, session, drill, payload, events)

    def robot_target(self, event):
        return self.operations.robot_target(event)

    def plan_robot(self, session, drill, start, target):
        return translate(self.operations.plan_robot_route, session, drill, start, target)

    def replan_robot(self, session, drill, robot, reason):
        return translate(self.operations.replan_robot_queue, session, drill, robot, reason)

    def apply_residents(self, session, drill_id, payload, identity):
        drill = self.require_drill(session, drill_id, identity.username)
        return assign_residents(self, session, drill, payload, identity)

    def apply_robot(self, session, drill_id, payload, identity):
        drill = self.require_drill(session, drill_id, identity.username)
        return command_robot(self, session, drill, payload, identity)

    def apply(self, session, drill, command, identity):
        ops = self.operations
        if command.kind == 'indoor.door.set':
            from app.services.indoor_commands import set_door
            return set_door(self, session, drill, command.arguments, identity)
        if command.kind == 'residents.assign':
            return self.apply_residents(session, drill.id, ResidentCommand.model_validate(command.arguments), identity)
        if command.kind == 'robot.command':
            return self.apply_robot(session, drill.id, RobotCommand.model_validate(command.arguments), identity)
        if command.kind == 'road.reopen':
            return translate(ops.reopen_road, drill.id, command.target_id, identity, session)
        dispatch = {
            'state': (DrillAction, ops.change_state), 'event.inject': (EventInject, ops.inject_event),
            'vehicle.command': (VehicleCommand, ops.command_vehicle), 'search.assign': (SearchAssignment, ops.assign_search),
            'participant.feedback': (ParticipantAction, ops.participant_action), 'task.assign': (TaskAssignment, ops.assign_task),
            'task.action': (TaskAction, ops.director_task_action), 'director.configure': (DirectorConfig, ops.configure_director),
        }
        schema, handler = dispatch[command.kind]
        arguments = schema.model_validate(command.arguments)
        if command.kind in {'task.assign', 'task.action'}:
            return translate(handler, drill.id, command.target_id, arguments, identity, session)
        return translate(handler, drill.id, arguments, identity, session)


def command_application():
    from app.api.routes import operations
    return DrillCommandApplication(ExistingDrillRuntime(operations))

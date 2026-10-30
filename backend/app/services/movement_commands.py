"""Residents and robot command rules shared by HTTP and approved agent steps."""
from sqlalchemy import select

from app.domain.errors import CommandRejected
from app.models.operations import DrillEvent, DrillSession, RobotAgent
from app.schemas.operations import RobotCommand
from app.services.command_feedback import commit_changes
from app.services.drill_simulation import plan_route
from app.services.exercise_world import frozen_world
from app.services.response_staff import capacity as staff_capacity


def assign_residents(runtime, session, drill, payload, identity):
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    if drill.status != 'running':
        raise CommandRejected(409, '只有运行中的演练可以指挥居民。')
    world = frozen_world(session, drill)
    valid_ids = {p['id'] for p in world['residents']} if world else {f'resident-{i}' for i in range(1, 19)}
    if not set(payload.resident_ids).issubset(valid_ids):
        raise CommandRejected(422, '包含无效居民编号。')
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    exit_name = '北门' if payload.exit == 'north' else '南门'
    action_name = '重点护送' if payload.action == 'priority_assist' else '分流疏散'
    before = runtime.simulation(session, drill, events, runtime.elapsed(drill))
    from app.services.agent_claims import manual_takeover, staff_assignments
    origin = session.info.get('command_origin')
    agent_id = origin.plan_id if origin and origin.kind == 'agent' else None
    if not agent_id:
        manual_takeover(session, drill.id, 'residents.assign', payload.model_dump(), runtime.elapsed(drill))
    bindings = {}
    if world and payload.action == 'priority_assist':
        selected = [p for p in before['residents'] if p['id'] in payload.resident_ids and p['status'] != 'evacuated']
        if any(not p['vulnerable'] for p in selected):
            raise CommandRejected(422, '重点护送仅用于重点人员；普通居民请使用分流疏散。')
        active = {h['resident_id'] for h in before['helpers'] if h['state'] != 'completed'}
        if len(active | {p['id'] for p in selected}) > staff_capacity(world):
            raise CommandRejected(409, '本场可用值守员均有在途任务，请等待护送完成或调整人员安排。')
        bindings = staff_assignments(session, drill.id, before, [p['id'] for p in selected], agent_id)
    if all(p['status'] == 'evacuated' for p in before['residents'] if p['id'] in payload.resident_ids):
        raise CommandRejected(409, '所选居民已全部到达安全出口，无需重复下达疏散指令。')
    exits = [n for n in before['road_network']['nodes'] if n['is_exit']]
    node = (min(exits, key=lambda n:n['y']) if payload.exit == 'north' else max(exits, key=lambda n:n['y'])) if exits else None
    target = (node['x'], node['y']) if node else (12., 12.) if payload.exit == 'north' else (84., 88.)
    spatial = runtime.resident_preview(session, drill, payload, events) if world and world.get('schema_version', 2) >= 3 else None
    for person in before['residents']:
        if person['id'] in payload.resident_ids and person['status'] != 'evacuated':
            if spatial:
                points = next(p['route_points'] if p['route_reachable'] else [] for p in spatial['residents'] if p['id'] == person['id'])
            else:
                _, points, _, _, _ = plan_route(before['road_network'], (person['x'], person['y']), target, runtime.elapsed(drill))
            if len(points) < 2:
                raise CommandRejected(409, f"{person['label']} 无法沿当前道路到达{exit_name}，请选择另一出口。")
    event = runtime.append_event(session, drill, 'resident.command', '应急指挥人员',
        f'已指挥 {len(payload.resident_ids)} 名居民向{exit_name}{action_name}。',
        {**payload.model_dump(), **({'staff_assignments': bindings} if bindings else {})})
    if not agent_id:
        # The approved agent candidate already owns a forecast and observation
        # check. Re-running two future worlds for every group delays the next
        # group while the real exercise clock continues ticking.
        at = runtime.elapsed(drill) + 30
        baseline = runtime.simulation(session, drill, events, at)
        after = runtime.simulation(session, drill, [*events, event], at)
        event.payload = {**event.payload, 'impact': {
            'congested_before': baseline['summary']['congested'], 'congested_after': after['summary']['congested'],
            'smoke_exposed_before': baseline['summary']['smoke_exposed'], 'smoke_exposed_after': after['summary']['smoke_exposed'],
            'forecast_horizon_seconds': 30, 'selected_count': len(payload.resident_ids),
        }}
    commit_changes(session)
    return runtime.snapshot(session, drill)


def command_robot(runtime, session, drill, payload, identity):
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    if drill.status != 'running':
        raise CommandRejected(409, '只有运行中的演练可以驱动机器人执行任务。')
    robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    if robot is None:
        raise CommandRejected(404, '未找到机器人。')
    origin = session.info.get('command_origin')
    if not origin or origin.kind != 'agent':
        from app.services.agent_claims import manual_takeover
        manual_takeover(session, drill.id, 'robot.command', payload.model_dump(), runtime.elapsed(drill))
    if payload.command == 'move':
        if payload.x is None or payload.y is None:
            raise CommandRejected(422, '空间目标必须包含坐标。')
        live = runtime.snapshot(session, drill)['robot']
        pending = [item for item in live.get('task_queue', []) if item['status'] in {'executing', 'queued'}]
        if pending:
            robot.x, robot.y = runtime.robot_target(session.get(DrillEvent, pending[-1]['id']))
        else:
            robot.x, robot.y = live['x'], live['y']
        route, points, edges, distance, risks = runtime.plan_robot(session, drill, (robot.x, robot.y), (payload.x, payload.y))
        if len(points) < 2 or '目标不可达' in route:
            raise CommandRejected(409, '目标在当前道路封锁条件下不可达，请调整目标或解除封锁。')
        robot.state, robot.route = 'executing', route
        robot.current_task = live.get('current_task') if pending else payload.target or '空间目标处置'
        robot.battery = max(0, robot.battery - max(1, round(distance / 18)))
        robot.reason = f'A* 风险路径已生成，共 {max(0, len(points)-1)} 段'
        kind = 'robot.target_assigned'
        message = f"机器人已接受目标：{payload.target or '空间目标处置'}（队列第 {len(pending)+1} 项）"
        data = {'state': robot.state, 'x': robot.x, 'y': robot.y, 'target_x': payload.x, 'target_y': payload.y,
            'target': payload.target or '空间目标处置', 'task_id': payload.task_id, 'route': route,
            'route_points': points, 'route_edge_ids': edges, 'route_distance': distance, 'route_risks': risks,
            'planned_duration_seconds': max(8, round(distance/3.5)), 'queue_position': len(pending)+1}
    elif payload.command == 'replan':
        runtime.replan_robot(session, drill, robot, '依据当前道路封锁、宽度与烟气风险重新规划任务队列。')
        commit_changes(session)
        return runtime.snapshot(session, drill)
    elif payload.command == 'cancel':
        live = runtime.snapshot(session, drill)['robot']
        item = next((t for t in live['task_queue'] if t['id'] == payload.task_id and t['status'] in {'queued', 'executing', 'blocked'}), None)
        if item is None:
            raise CommandRejected(409, '只能取消当前场次中尚未完成的机器人任务。')
        runtime.append_event(session, drill, 'robot.task_cancelled', identity.username, f"已取消任务：{item['label']}",
            {'target_event_id': item['id'], 'x': live['x'], 'y': live['y']})
        robot.x, robot.y = live['x'], live['y']
        runtime.replan_robot(session, drill, robot, '取消任务后从当前位置衔接后续队列。')
        commit_changes(session)
        return runtime.snapshot(session, drill)
    elif payload.command == 'broadcast':
        live = runtime.snapshot(session, drill)['robot']
        if live['state'] == 'completed':
            return runtime.snapshot(session, drill)
        if live['state'] not in {'arrived', 'completed'}:
            progress = next((t['progress'] for t in live.get('task_queue', []) if t['status'] == 'executing'), 0)
            raise CommandRejected(409, f'机器人尚未到达任务点（{round(progress*100)}%），不能提前完成现场广播。')
        robot.state, robot.current_task = 'completed', live.get('current_task') or '目标点疏散广播'
        robot.x, robot.y = live['x'], live['y']
        robot.battery = max(0, robot.battery-3)
        robot.reason = '已在目标点完成现场广播，任务形成闭环证据'
        kind, message = 'robot.broadcast_completed', robot.reason
        data = {'state': robot.state, 'x': live['x'], 'y': live['y'], 'target': robot.current_task}
    else:
        live = runtime.snapshot(session, drill)['robot']
        if not live['task_queue'] or all(t['status'] == 'cancelled' for t in live['task_queue']):
            return command_robot(runtime, session, drill, RobotCommand(command='move', x=58, y=54, target='3 号楼入口疏散广播'), identity)
        kind = 'robot.telemetry'
        message = f"机器人实况：{live['state']}，位置 ({live['x']}, {live['y']})"
        data = {'state': live['state'], 'x': live['x'], 'y': live['y']}
    data['battery'] = robot.battery
    runtime.append_event(session, drill, kind, robot.name, message, data)
    commit_changes(session)
    return runtime.snapshot(session, drill)

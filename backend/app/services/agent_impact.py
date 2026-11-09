"""Bounded, evidence-based impact and revision differences for one goal run."""
from collections import defaultdict, deque

from sqlalchemy import select

from app.models.operations import DrillCommand, DrillEvent
from app.services.water_resources import affected_release_steps

WATCHED = {'inject.channel_blocked', 'road.reopened', 'inject.resident_missing',
           'inject.hydrant_failure',
           'indoor.door_changed', 'robot.replanned', 'robot.target_assigned',
           'robot.task_cancelled', 'robot.broadcast_completed', 'resident.command'}


def remaining_route(route, person, edges):
    """Trim walked edges before comparing decisions; walking alone is not a revision."""
    current = person.get('current_edge_id') or person.get('edge_id')
    if current in route:
        return route[route.index(current):], True
    node = person.get('node_id')
    touching = [index for index, key in enumerate(route) if node and node in (
        edges.get(key, {}).get('start_node_id'), edges.get(key, {}).get('end_node_id'))]
    if touching:
        return route[max(touching):], True
    return route, False


def remaining_resident_routes(run, data):
    """Share current-route relevance between execution guards and their UI."""
    selected = set(run.scope.get('resident_ids', []))
    people = {p['id']: p for p in data['simulation']['residents']
              if p['id'] in selected and p['status'] != 'evacuated'}
    edges = {edge['id']: edge for edge in data['simulation'].get('spatial_network', {}).get('edges', [])}
    routes = defaultdict(set)
    for candidate in run.candidates:
        if run.selected_candidate and candidate['id'] != run.selected_candidate:
            continue
        for person in candidate.get('assignments', []):
            if person['id'] in people:
                route, _ = remaining_route(person.get('route_edge_ids', []), people[person['id']], edges)
                routes[person['id']].update(route)
    for step in run.steps:
        for pid in step.get('resident_ids', []):
            if pid in people and not routes[pid]:
                route, _ = remaining_route(people[pid].get('route_edge_ids') or step.get('route_edge_ids', []), people[pid], edges)
                routes[pid].update(route)
    return routes


def impact_view(session, run, data):
    from app.services.agent_resources import owned_steps
    selected = set(run.scope.get('resident_ids', []))
    people = {p['id']: p for p in data['simulation']['residents'] if p['id'] in selected}
    edges = {edge['id']: edge for edge in data['simulation'].get('spatial_network', {}).get('edges', [])}
    remaining = {pid for pid, person in people.items() if person['status'] != 'evacuated'}
    routes = remaining_resident_routes(run, data)
    robot_edges = set()
    for candidate in run.candidates:
        if run.selected_candidate and candidate['id'] != run.selected_candidate:
            continue
        robot_edges.update((candidate.get('robot_support') or {}).get('route_edge_ids', []))
    command_ids = sorted({step['command_id'] for step in owned_steps(run) if step.get('command_id')})
    own_events = set()
    for offset in range(0, len(command_ids), 500):
        for event_ids in session.scalars(select(DrillCommand.event_ids).where(
                DrillCommand.drill_session_id == run.drill_session_id, DrillCommand.command_id.in_(command_ids[offset:offset + 500]))):
            own_events.update(event_ids or [])
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == run.drill_session_id,
        DrillEvent.sequence > run.observed_sequence, DrillEvent.event_type.in_(WATCHED))
        .where(DrillEvent.sequence <= data['latest_event_sequence'])
        .order_by(DrillEvent.sequence.desc()).limit(101)))
    affected, direct, changes = set(), set(), []
    robot_included = bool(run.scope.get('robot_broadcast') and not run.scope.get('robot_broadcast_evidence')
        and (not run.steps or any(step.get('kind') == 'robot.command' and step['status'] != 'completed' for step in run.steps)))
    water_affected = set()
    for event in reversed(events[:100]):
        if event.id in own_events or event.payload.get('purpose') == 'inspection':
            continue
        kind, payload = event.event_type, event.payload
        edge_id = payload.get('blocked_edge_id') or payload.get('door_id')
        robot_changed = robot_included and (kind.startswith('robot.') or bool(edge_id and edge_id in robot_edges))
        members = {pid for pid in remaining if edge_id and edge_id in routes[pid]}
        steps = {step['id'] for step in run.steps if step.get('status') != 'completed' and edge_id and (
            edge_id in step.get('route_edge_ids', []) or edge_id == step.get('arguments', {}).get('door_id'))}
        if kind == 'inject.hydrant_failure':
            supply_steps = affected_release_steps(run.steps, payload.get('hydrant_id'))
            steps.update(step['id'] for step in supply_steps)
            members.update(pid for step in supply_steps for pid in step.get('resident_ids', []) if pid in remaining)
            water_affected.update(members)
        elif kind == 'inject.resident_missing':
            members = {payload['resident_id']} & remaining
        elif kind == 'resident.command':
            members = set(payload.get('resident_ids', [])) & remaining
        elif kind.startswith('robot.') and robot_included:
            steps.update(step['id'] for step in run.steps if step.get('kind') == 'robot.command' and step['status'] != 'completed')
        if not members and not steps and not robot_changed:
            continue
        direct.update(steps)
        affected.update(members)
        changes.append({'id': event.id, 'sequence': event.sequence, 'kind': kind,
            'at_seconds': event.elapsed_seconds, 'message': event.message[:240],
            'edge_id': edge_id, 'resource_id': payload.get('hydrant_id'),
            'location': payload.get('target') if kind == 'inject.hydrant_failure' else edges.get(edge_id, {}).get('name'), 'resident_count': len(members),
            'robot_affected': robot_changed})
    for step in run.steps:
        if set(step.get('resident_ids', [])) & affected and step['status'] != 'completed':
            direct.add(step['id'])
    impacted = set(direct)
    # Dependencies propagate only to unfinished downstream tasks.
    downstream = defaultdict(list)
    for step in run.steps:
        if step['status'] != 'completed':
            for dependency in step.get('depends_on', []):
                downstream[dependency].append(step['id'])
    pending = deque(direct)
    while pending:
        for child in downstream[pending.popleft()]:
            if child not in impacted:
                impacted.add(child)
                pending.append(child)
    return {'observed_sequence': run.observed_sequence, 'current_sequence': data['latest_event_sequence'],
        'at_seconds': data['elapsed_seconds'], 'affected_count': len(affected), 'step_count': len(impacted),
        'changes': changes[-8:], 'changes_count': len(changes), 'events_truncated': len(events) > 100,
        'robot_affected': any(change['robot_affected'] for change in changes),
        'residents': [{'id': pid, 'label': people[pid].get('label', pid),
            'blocked': not people[pid].get('route_reachable', True), 'location': people[pid].get('last_location', ''),
            'reason': '本批所用水源失效，请核对压制与后续放行；已受理移动继续保留' if pid in water_affected else
                '原方案途经变化位置；当前路线不可达' if not people[pid].get('route_reachable', True) else '原方案途经变化位置，请核对已改道后的路线'}
            for pid in sorted(affected)[:8]],
        'steps': [{'id': step['id'], 'label': step['label'], 'kind': step.get('kind', 'residents.assign'),
                   'direct': step['id'] in direct} for step in run.steps if step['id'] in impacted][:8]}


def revision_difference(run, data, candidates, impact):
    previous = next((candidate for candidate in run.candidates if candidate['id'] == run.selected_candidate),
                    run.candidates[0] if run.candidates else None)
    old_assignments = {person['id']: person for person in (previous or {}).get('assignments', [])}
    if not old_assignments:
        for step in run.steps:
            if step.get('exit'):
                old_assignments.update({pid: {'exit': step['exit'], 'route_edge_ids': step.get('route_edge_ids', [])}
                                        for pid in step.get('resident_ids', [])})
    people = {p['id']: p for p in data['simulation']['residents']}
    edges = {edge['id']: edge for edge in data['simulation'].get('spatial_network', {}).get('edges', [])}
    differences = []
    for candidate in candidates:
        changed = []
        for person in candidate['assignments']:
            old = old_assignments.get(person['id'])
            if not old:
                continue
            exit_changed = old.get('exit') != person['exit']
            old_route, located = remaining_route(old.get('route_edge_ids', []), people.get(person['id'], {}), edges)
            new_route = person.get('route_edge_ids', [])
            route_changed = old_route != new_route if located else bool(set(new_route) - set(old_route))
            if exit_changed or route_changed:
                changed.append({'resident_id': person['id'], 'label': people.get(person['id'], {}).get('label', person['id']),
                    'old_exit': old.get('exit'), 'new_exit': person['exit'], 'exit_changed': exit_changed,
                    'route_changed': route_changed})
        differences.append({'candidate_id': candidate['id'], 'changed_count': len(changed), 'residents': changed[:8]})
    return {'from_revision': (getattr(run, 'approved_revision', None) or run.revision) if run.selected_candidate else run.revision,
            'baseline': 'approved' if run.selected_candidate else 'draft',
            'at_seconds': data['elapsed_seconds'], 'impact': impact,
            'previous_objective': run.scope.get('objective', 'balanced'),
            'previous_forbidden_exits': run.scope.get('forbidden_exits', []), 'candidates': differences}

"""Queue-free timing estimates, kept separate from simulated outcome metrics."""
from math import ceil


def release_schedule(groups, routes, resource_steps, support, data):
    """Estimate every serial building's timing without inventing arrivals.

    Uses current route travel times and the robot's planned segments. This is
    an optimistic schedule check, not a future simulation: queues, escort
    approach, traffic and human verification can only add unresolved work.
    """
    batches = {}
    for group in groups:
        if group.get('release_wave'):
            batches.setdefault(group['release_wave'], []).append(group)
    if not batches:
        return None
    start = data['elapsed_seconds']
    deployment = support.get('duration_seconds')
    known = deployment is not None or support.get('already_active')
    previous_arrival = start + (deployment or 0)
    robot_free = previous_arrival
    waves = []
    for number, members in sorted(batches.items()):
        building_id = members[0].get('building_id')
        move = next((step for step in resource_steps if step.get('building_id') == building_id
                     and step.get('arguments', {}).get('command') == 'move'), None)
        segment = move.get('planned_duration_seconds') if move else 0
        travel_times = []
        for group in members:
            for resident_id in group['resident_ids']:
                route = routes.get(group['exit'], {}).get(resident_id, {})
                remaining = route.get('remaining_seconds', route.get('estimated_seconds'))
                if not route.get('route_reachable') or remaining is None:
                    known = False
                else:
                    travel_times.append(max(0, float(remaining)))
        if segment is None:
            known = False
        release_at = max(previous_arrival, robot_free + (segment or 0)) + (1 if move else 0)
        arrival_at = release_at + max(travel_times, default=0)
        waves.append({'wave': number, 'building_id': building_id,
                      'release_at': ceil(release_at) if known else None,
                      'arrival_at': ceil(arrival_at) if known else None})
        robot_free, previous_arrival = release_at, arrival_at
    alarm = next((e for e in data.get('events', []) if e['event_type'] == 'robot.alarm_confirmed'), None)
    risks = []
    if alarm and known:
        for task in data.get('tasks', []):
            if task['status'] == 'completed' or task.get('kind') not in {'broadcast', 'escort'}:
                continue
            deadline = task.get('deadline_seconds')
            if deadline is None:
                continue
            finish = waves[-1]['release_at'] if task['kind'] == 'broadcast' else waves[-1]['arrival_at']
            deadline_at = alarm['elapsed_seconds'] + deadline
            if finish > deadline_at:
                risks.append({'task_id': task['id'], 'title': task['title'],
                              'deadline_at': deadline_at, 'estimated_ready_at': finish,
                              'delay_seconds': ceil(finish - deadline_at)})
    return {'kind': 'queue_free_schedule', 'complete': known,
            'estimated_completion_at': waves[-1]['arrival_at'] if known else None,
            'waves': waves, 'deadline_risks': risks,
            'notice': '逐栋时序估算使用当前路线与机器人行程，不含新增拥堵、护送接近、交通等待及人工核验；不是全程仿真或到场保证。'}

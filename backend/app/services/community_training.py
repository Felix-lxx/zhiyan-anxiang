"""Versioned, anonymous community training inputs and event-derived notices.

Profiles are reproducible teaching assumptions, never surveyed resident data.
Broadcast coverage and a human receipt are deliberately different facts.
"""
from copy import deepcopy
from random import Random
from uuid import NAMESPACE_URL, uuid5


def freeze_community(world):
    params = world['parameters']
    if params.get('community_profile') != 'night_shift':
        return
    people = world['residents']
    rng = Random(int(params.get('simulation_seed', 2026)))
    needs_help = rng.randrange(len(people))
    houses, buildings = {}, {b['id']: b for b in world['objects']}
    for index, person in enumerate(people):
        building = buildings[person['building_id']]
        zone = person.get('start_zone_id', '')
        side = ('东' if zone.endswith(':east') else '西') if world['parameters'].get('fire_source_type') == 'kitchen' else ('东' if person['y'] >= building['y'] else '西')
        key = (person.get('start_zone_id') if world['parameters'].get('fire_source_type') == 'kitchen'
               else f"{building['id']}:{person['floor']}:{side}")
        house_id = str(uuid5(NAMESPACE_URL, 'zhiyan-household:' + key))
        house = houses.setdefault(house_id, {'id': house_id, 'building_id': building['id'],
            'building_name': building['name'], 'floor': person['floor'],
            'label': f"{building['name']} · {person['floor']}层{side}侧训练户",
            'resident_ids': [], 'source': 'simulation'})
        house['resident_ids'].append(person['id'])
        profile = 'mobility' if index == needs_help else 'hearing' if index % 5 == 1 else 'sleeping' if index % 3 == 0 else 'standard'
        person.update(household_id=house_id, household_label=house['label'], profile=profile,
            profile_label={'mobility':'行动受限', 'hearing':'需直接联系', 'sleeping':'夜间熟睡', 'standard':'自主行动'}[profile],
            vulnerable=profile == 'mobility', notification_need='direct_contact' if profile == 'hearing' else 'standard',
            walking_speed=.65 if profile == 'mobility' else 1.25,
            preparation_seconds=rng.randint(15, 35) if profile == 'sleeping' else rng.randint(6, 12))
    origin = world['robot_origin']
    world['response_staff'] = [{'id': f'escort-{i+1}', 'name': f'夜班值守员 {i+1}',
        'role':'物业/网格员', 'available':True, 'source':'simulation', 'origin':deepcopy(origin)}
        for i in range(int(params.get('duty_staff_count', 4)))]
    world['community_training'] = {'version':2, 'source':'simulation',
        'label':'社区夜班模拟画像', 'seed':int(params.get('simulation_seed', 2026)),
        'households':list(houses.values()), 'environment_model':'causal_training_v2',
        'visit_smoke_limit':.15}


def project_community(world, events, people):
    model = world.get('community_training')
    if not model:
        return None
    residents = {p['id']:p for p in people}
    houses = []
    for house in model['households']:
        sent, received, channels, at, evidence = False, False, [], None, ''
        for event in events:
            payload = event.payload
            if event.event_type == 'robot.broadcast_completed' and (
                payload.get('building_id') is None or payload['building_id'] == house['building_id']
            ):
                sent = True
                if 'broadcast' not in channels: channels.append('broadcast')
            if payload.get('household_id') != house['id']:
                continue
            if event.event_type == 'participant.household_notified':
                sent = True
                if payload['channel'] not in channels: channels.append(payload['channel'])
                at, evidence = event.elapsed_seconds, payload.get('message', '')
            if event.event_type == 'participant.household_confirmed':
                received, at, evidence = True, event.elapsed_seconds, payload.get('message', '')
        members = [residents[pid] for pid in house['resident_ids'] if pid in residents]
        houses.append({**house, 'notification_state':'confirmed' if received else 'sent' if sent else 'unnotified',
            'channels':channels, 'last_report_at':at, 'evidence':evidence,
            'direct_contact_required':any(p.get('notification_need') == 'direct_contact' for p in members),
            'arrived':sum(p.get('status')=='evacuated' for p in members),
            'priority':sum(p['vulnerable'] for p in members),
            'profiles':list(dict.fromkeys(p.get('profile_label', '') for p in members))})
    return {**model, 'households':houses, 'summary':{
        'total':len(houses), 'confirmed':sum(h['notification_state']=='confirmed' for h in houses),
        'unnotified':sum(h['notification_state']=='unnotified' for h in houses),
        'awaiting_confirmation':sum(h['notification_state']=='sent' for h in houses)},
        'notice':'模拟画像；广播仅表示覆盖。收到通知由现场回执确认，不代表传感器或定位核验。'}


def validate_notice(world, events, payload):
    from fastapi import HTTPException
    if payload.role not in {'物业/网格员', '居民代表', '应急指挥人员'}:
        raise HTTPException(403, '当前角色不能提交住户通知回执。')
    house = next((h for h in (world.get('community_training') or {}).get('households', [])
                  if h['id']==payload.household_id), None)
    if house is None:
        raise HTTPException(422, '请选择本场冻结的训练住户。')
    if not payload.channel or len(payload.message.strip()) < 6:
        raise HTTPException(422, '请选择通知方式并填写至少六个字的现场回执。')
    view = project_community(world, events, world['residents'])
    item = next(h for h in view['households'] if h['id']==house['id'])
    if payload.action == 'household_confirmed':
        if payload.channel not in item['channels']:
            raise HTTPException(409, '尚无该方式的通知记录，请先完成通知再确认收到。')
        if item['direct_contact_required'] and payload.channel=='broadcast':
            raise HTTPException(409, '本户有需直接联系的居民，请电话或敲门核实后回执。')

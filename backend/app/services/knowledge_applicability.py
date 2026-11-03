"""Compare recorded simulation conditions without treating similarity as validity."""
from math import isclose

from app.services.simulation_checkpoints import ENGINE_REVISION


PARAMETERS = {
    'fire_source_type': '火源类型', 'fire_source_object_id': '起火对象',
    'fire_floor': '起火楼层', 'fire_room': '起火房间', 'resident_count': '场景居民人数',
    'stair_width': '楼梯净宽', 'south_lane_status': '南侧通道', 'room_door_state': '初始房门状态',
}


def situation(data, scope=None):
    """Use the caller's exact snapshot, including historical snapshots."""
    world = data.get('simulation', {}).get('world', {})
    return {'parameters': world.get('parameters', {}), 'engine_revision': ENGINE_REVISION,
            'at_seconds': data['elapsed_seconds'], 'event_sequence': data.get('latest_event_sequence'),
            'target_population': len(scope['resident_ids']) if scope else None}


def equal(left, right):
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        return isclose(left, right, rel_tol=0, abs_tol=1e-6)
    return type(left) is type(right) and left == right


def assess_experience(source, current):
    if not source:
        return {'status': 'unverified', 'label': '缺少原始观察', 'differences': [], 'missing': ['系统观察来源'],
                'notice': '人工撰写的经验未关联系统观察，请人工核对适用条件。'}
    if not current:
        return {'status': 'unchecked', 'label': '尚未对照具体场次', 'differences': [], 'missing': [],
                'notice': '资料检索未绑定演练现场；进入具体场次后再核对条件。'}
    recorded, actual = source.get('parameters') or {}, current.get('parameters') or {}
    differences, missing = [], []
    for key, label in PARAMETERS.items():
        if key not in actual:
            continue
        if key not in recorded:
            missing.append(label)
        elif not equal(recorded[key], actual[key]):
            differences.append({'field': key, 'label': label, 'recorded': recorded[key], 'current': actual[key]})
    observed_revision = source.get('observed_engine_revision')
    if observed_revision is None:
        missing.append('观察模型修订号')
    elif observed_revision != current['engine_revision']:
        differences.append({'field': 'engine_revision', 'label': '模型修订号',
                            'recorded': observed_revision, 'current': current['engine_revision']})
    if current.get('target_population') is not None:
        if source.get('population') is None:
            missing.append('目标居民人数')
        elif source['population'] != current['target_population']:
            differences.append({'field': 'population', 'label': '目标居民人数',
                                'recorded': source['population'], 'current': current['target_population']})
    status = 'different' if differences else 'unverified' if missing or not actual else 'matched'
    labels = {'different': '条件有差异', 'unverified': '条件记录不完整', 'matched': '已核对记录条件'}
    return {'status': status, 'label': labels[status], 'differences': differences, 'missing': missing,
            'at_seconds': current['at_seconds'], 'event_sequence': current.get('event_sequence'),
            'notice': '有条件差异，不能把原观察指标用于本场预测。' if differences else
                      '缺少完整条件，需人工核对；本场效果以工具预演为准。' if status == 'unverified' else
                      '记录字段一致；人员个体、动态事件与行动时序仍需核对，本场效果以工具预演为准。'}


def assessment(hits):
    experiences = [hit for hit in hits if hit.get('category') == 'experience']
    excluded = [hit['id'] for hit in experiences if hit.get('applicability', {}).get('status') != 'matched']
    return {'experience_count': len(experiences), 'matched_count': len(experiences) - len(excluded),
            'excluded_citations': excluded,
            'notice': f'检索到 {len(experiences)} 条经验，{len(excluded)} 条需复核，不作为当前方案的推荐依据。',
            'items': [{'id': hit['id'], 'title': hit['title'], **hit.get('applicability', {})} for hit in experiences]}

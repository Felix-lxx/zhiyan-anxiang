"""One publication contract shared by preparation, publishing and new runs."""
from pydantic import ValidationError
from app.schemas.scene import ChargingShedParametersUpdate, KitchenParametersUpdate
from app.services.scenario_contracts import scene_contract
from app.services.fire_sources import resolve_fire_source, InvalidFireSource

FIELDS = {
    'scenario_kind': ('案例能力', 'scenario-template', 4),
    'fire_source_type': ('起火类型', 'fire-source', 2),
    'fire_source_object_id': ('起火点', 'fire-source', 2),
    'fire_floor': ('起火楼层', 'fire-floor', 2),
    'fire_room': ('起火房间', 'fire-room', 2),
    'room_door_state': ('房门初始状态', 'room-door-state', 2),
    'start_time': ('起火时间', 'start-time', 2),
    'wind_direction': ('风向', 'wind-direction', 2),
    'resident_count': ('居民人数（1–1000）', 'resident-count', 1),
    'hydrant_status': ('水源状态', 'hydrant-status', 1),
    'south_lane_status': ('通道状态', 'south-lane-status', 1),
    'stair_width': ('楼梯宽度（0.6–3 米）', 'stair-width', 1),
    'tasks': ('案例标准处置任务', 'scenario-tasks', 3),
}


def validate_configuration(session, scene, parameter_override=None):
    version = max(scene.versions, key=lambda item: item.version_number, default=None)
    contract = scene_contract(scene)
    details = []

    def issue(key, message):
        _, field, step = FIELDS[key]
        details.append(dict(key=key, message=message, target='scenes',
                            query=dict(scene=scene.id, field=field, preparation=str(step))))

    if not contract.available:
        issue('scenario_kind', contract.notice)
    elif version is None:
        issue('fire_source_object_id', '场景没有可用版本，请重新创建草稿。')
    else:
        from app.services.scenario_tasks import missing_tasks
        missing = missing_tasks(session, version, contract.code)
        if missing:
            issue('tasks', '缺少标准处置任务：' + '、'.join(item[1] for item in missing) + '。请在决策任务中补齐后发布。')
        parameters = {**version.parameters, **(parameter_override or {})}
        try:
            (KitchenParametersUpdate if contract.code == 'kitchen_fire' else ChargingShedParametersUpdate).model_validate(parameters)
        except ValidationError as exc:
            for error in exc.errors():
                key = str(error['loc'][0])
                if key in FIELDS:
                    issue(key, f'请检查{FIELDS[key][0]}：缺失或格式不正确。')
        if parameters.get('fire_source_type') not in contract.source_types:
            issue('fire_source_type', '起火类型与当前案例不一致，请返回参数页重新保存。')
        try:
            resolve_fire_source(session, version.community_version_id, parameters)
        except InvalidFireSource as exc:
            if not any(item['key'] == 'fire_source_object_id' for item in details):
                issue('fire_source_object_id', str(exc))
    return dict(passed=not details, issues=[item['message'] for item in details], issue_details=details,
                capabilities=contract.payload(),
                message='场景运行参数校验通过，可发布。' if not details else '场景尚不能发布，请定位并修改下列配置。')

"""One publication contract shared by preparation, publishing and new runs."""
from pydantic import ValidationError
from sqlalchemy import select
from app.models.domain import MapObject, MapObjectType
from app.schemas.scene import ChargingShedParametersUpdate

FIELDS = {
    'fire_source_object_id': ('起火点', 'fire-source', 2),
    'start_time': ('起火时间', 'start-time', 2),
    'wind_direction': ('风向', 'wind-direction', 2),
    'resident_count': ('居民人数（1–1000）', 'resident-count', 1),
    'hydrant_status': ('水源状态', 'hydrant-status', 1),
    'south_lane_status': ('通道状态', 'south-lane-status', 1),
    'stair_width': ('楼梯宽度（0.6–3 米）', 'stair-width', 1),
}


def validate_configuration(session, scene):
    version = max(scene.versions, key=lambda item: item.version_number, default=None)
    details = []

    def issue(key, message):
        _, field, step = FIELDS[key]
        details.append(dict(key=key, message=message, target='scenes',
                            query=dict(scene=scene.id, field=field, preparation=str(step))))

    if version is None:
        issue('fire_source_object_id', '场景没有可用版本，请重新创建草稿。')
    else:
        try:
            ChargingShedParametersUpdate.model_validate(version.parameters)
        except ValidationError as exc:
            for error in exc.errors():
                key = str(error['loc'][0])
                if key in FIELDS:
                    issue(key, f'请检查{FIELDS[key][0]}：缺失或格式不正确。')
        source = session.scalar(select(MapObject).where(
            MapObject.id == version.parameters.get('fire_source_object_id'),
            MapObject.community_version_id == version.community_version_id,
            MapObject.object_type == MapObjectType.CHARGING_SHED))
        if source is None and not any(item['key']=='fire_source_object_id' for item in details):
            issue('fire_source_object_id', '起火点不存在、已删除或不属于该底图的充电棚，请重新选择。')
    return dict(passed=not details, issues=[item['message'] for item in details], issue_details=details,
                message='场景运行参数校验通过，可发布。' if not details else '场景尚不能发布，请定位并修改下列配置。')

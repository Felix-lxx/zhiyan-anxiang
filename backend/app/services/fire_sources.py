"""Resolve a legal ignition address; never substitute a different map object."""
import math

from sqlalchemy.orm import Session

from app.models.domain import MapObject, MapObjectType


class InvalidFireSource(ValueError):
    pass


def resolve_fire_source(session: Session, community_version_id: str, parameters: dict) -> MapObject:
    source_id = parameters.get("fire_source_object_id")
    source = session.get(MapObject, source_id) if isinstance(source_id, str) and source_id else None
    kitchen = parameters.get('fire_source_type') == 'kitchen'
    expected = MapObjectType.BUILDING if kitchen else MapObjectType.CHARGING_SHED
    if source is None or source.community_version_id != community_version_id or source.object_type != expected:
        if kitchen:
            raise InvalidFireSource('请选择该场景底图中的住宅楼。')
        raise InvalidFireSource("起火点不存在、已删除或不属于该底图的充电棚，请重新选择。")
    try:
        floors = int(source.properties.get('floors', 6)) if kitchen else 1
        if kitchen and not 1 <= floors <= 20: raise ValueError()
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidFireSource('住宅楼层数据无效，请先在底图修正楼层。') from exc
    if kitchen and (type(parameters.get('fire_floor')) is not int or not 1 <= parameters['fire_floor'] <= floors or parameters.get('fire_room') not in {'east', 'west'}):
        raise InvalidFireSource('起火楼层或房间无效，请选择该住宅楼实际存在的楼层与厨房。')
    if kitchen and parameters.get('resident_count',0) > floors*8:
        raise InvalidFireSource('室内人口超过当前示例户型容量（每层最多8人），请减少人口或选择更多楼层的住宅。')
    geometry = source.geometry if isinstance(source.geometry, dict) else {}
    coordinates = [geometry.get(key) for key in ("x", "y")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100 for value in coordinates):
        raise InvalidFireSource("起火对象坐标无效，请先在社区底图修正位置。")
    if kitchen:
        from app.services.indoor_layout import kitchen_rooms
        try:
            dimensions = [float(source.properties.get('width', 5)), float(source.properties.get('depth', 3)),
                          float(source.properties.get('stair_width', parameters.get('stair_width', 1.2)))]
            if not all(math.isfinite(value) for value in dimensions):
                raise ValueError('建筑尺寸必须为有限数值。')
            kitchen_rooms({'x': coordinates[0], 'y': coordinates[1],
                           'width': max(2, min(20, dimensions[0])), 'depth': max(2, min(20, dimensions[1]))}, max(.4, dimensions[2]))
        except (TypeError, ValueError) as exc:
            raise InvalidFireSource(str(exc)) from exc
    return source


def fire_source_address(source: MapObject, parameters: dict | None = None) -> dict:
    # IDs are authoritative. Client-supplied coordinates or cached addresses are
    # not accepted as input; the world adds its own immutable position snapshot.
    if parameters and parameters.get('fire_source_type') == 'kitchen':
        return {'schema_version': 1, 'source_type': 'kitchen', 'location': {
            'kind': 'room', 'object_id': source.id, 'community_version_id': source.community_version_id,
            'floor': parameters['fire_floor'], 'room': parameters['fire_room'],
            'node_id': f"indoor:{source.id}:{parameters['fire_floor']}:{parameters['fire_room']}"}}
    return {"schema_version": 1, "source_type": source.object_type.value,
            "location": {"kind": "object", "object_id": source.id,
                         "community_version_id": source.community_version_id}}

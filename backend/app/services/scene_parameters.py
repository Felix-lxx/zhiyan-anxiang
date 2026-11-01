"""Complete initial draft parameters without replacing an explicit fire address."""
from sqlalchemy import select

from app.models.domain import MapObject, MapObjectType
from app.services.fire_sources import InvalidFireSource, resolve_fire_source
from app.services.scenario_contracts import canonical_defaults


def initial_parameters(session, community_version_id, template_defaults):
    values = canonical_defaults(template_defaults)
    kitchen = values.get('fire_source_type') == 'kitchen'
    values = {
        'resident_count': 8 if kitchen else 18, 'hydrant_status': 'available',
        'south_lane_status': 'restricted', 'stair_width': 1.2,
        **({'fire_floor': 1, 'fire_room': 'east', 'room_door_state': 'open'} if kitchen else {}),
        **values,
    }
    if values.get('fire_source_object_id'):
        return values
    kind = MapObjectType.BUILDING if kitchen else MapObjectType.CHARGING_SHED
    candidates = []
    for obj in session.scalars(select(MapObject).where(
        MapObject.community_version_id == community_version_id, MapObject.object_type == kind
    ).order_by(MapObject.created_at)):
        try:
            resolve_fire_source(session, community_version_id, {**values, 'fire_source_object_id': obj.id})
        except InvalidFireSource:
            continue
        candidates.append(obj)
    # A curated example house is explicitly marked in the built-in map. An
    # arbitrary map with multiple possible sources still requires user choice.
    curated = [obj for obj in candidates if obj.properties.get('indoor_layout_version') == 3] if kitchen else []
    source = candidates[0] if len(candidates) == 1 else curated[0] if len(curated) == 1 else None
    if source:
        values['fire_source_object_id'] = source.id
    return values

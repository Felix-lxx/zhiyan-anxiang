"""Read-only preparation checklist; not a real-world fire-safety assessment."""
from collections import Counter, defaultdict
from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.domain import MapObject, RoadNode, RoadEdge, Scene
from app.services.map_objects import current_version
from app.services.scene_validation import validate_configuration


def inspect_community(session, community):
    version = current_version(community)
    objects = list(session.scalars(select(MapObject).where(MapObject.community_version_id == version.id))) if version else []
    nodes = list(session.scalars(select(RoadNode).where(RoadNode.community_version_id == version.id))) if version else []
    edges = list(session.scalars(select(RoadEdge).where(RoadEdge.community_version_id == version.id))) if version else []
    scenes = list(session.scalars(select(Scene).where(Scene.community_id == community.id).options(selectinload(Scene.versions))))
    counts = Counter(o.object_type.value for o in objects)
    object_ids = {o.id for o in objects}
    adjacency = defaultdict(set)
    for edge in edges:
        if edge.status.value != 'blocked':
            adjacency[edge.start_node_id].add(edge.end_node_id)
            adjacency[edge.end_node_id].add(edge.start_node_id)
    exits = [n.id for n in nodes if n.is_exit]
    reachable, pending = set(exits), list(exits)
    while pending:
        for neighbor in adjacency[pending.pop()] - reachable:
            reachable.add(neighbor); pending.append(neighbor)
    stranded = [n.name for n in nodes if n.id not in reachable]
    valid_scenes = []
    scene_results = [(scene, validate_configuration(session, scene)) for scene in scenes]
    for scene, validation in scene_results:
        latest = max(scene.versions, key=lambda v:v.version_number, default=None)
        params = latest.parameters if latest else {}
        if (version and latest and latest.community_version_id == version.id
            and scene.status.value == 'published'
            and params.get('fire_source_object_id') in object_ids and validation['passed']):
            valid_scenes.append(scene)
    checks = []
    def check(key, title, passed, detail, target, action):
        checks.append(dict(key=key, title=title, passed=bool(passed), detail=detail, target=target, action=action))
    check('buildings', '住宅楼栋', counts['building'] > 0,
          f"已配置 {counts['building']} 栋住宅；新场次按楼栋生成室内疏散空间。" if counts['building'] else '还没有住宅楼栋，无法按楼栋组织室内疏散。', 'map', '配置楼栋')
    check('roads', '出口与通道连通', bool(exits and edges and not stranded),
          f"{len(nodes)} 个节点、{len(edges)} 条道路、{len(exits)} 个出口。" + (
              '请先配置道路节点、连接道路并标记至少一个出口。' if not (nodes and edges and exits)
              else '无法通往出口：'+ '、'.join(stranded[:6]) + ('等' if len(stranded)>6 else '') if stranded
              else '请在地图中复核楼门接入位置。'), 'map', '检查路网')
    check('water', '消防水源', counts['fire_hydrant'] > 0,
          f"已配置 {counts['fire_hydrant']} 处消火栓；实际状态以场景参数为准。", 'map', '维护水源')
    check('assembly', '集合区域', counts['assembly_point'] > 0,
          f"地图中有 {counts['assembly_point']} 处集合区标记。演练到达与清点以运行时集合点为准。", 'map', '检查集合区')
    check('scene', '可用场景', bool(valid_scenes),
          f"{len(scenes)} 个场景中，{len(valid_scenes)} 个已发布且引用当前底图、有效起火点和基本参数。", 'scenes', '准备场景')
    for item in checks:
        key = item['key']
        if key == 'roads':
            node = next((node for node in nodes if node.id not in reachable), None)
            item['query'] = dict(layer='network', node=node.id) if node else dict(layer='network', tool='place-node' if not exits else 'connect')
        elif key != 'scene':
            kind = {'buildings':'building', 'water':'fire_hydrant', 'assembly':'assembly_point'}[key]
            obj = next((obj for obj in objects if obj.object_type.value == kind), None)
            item['query'] = dict(object=obj.id) if obj else dict(object_type=kind, tool='place-object')
        else:
            candidate = next(((scene, result) for scene, result in scene_results if not result['passed']), None)
            if candidate:
                scene, result = candidate
                item['query'] = result['issue_details'][0]['query']
                item['detail'] += f" {scene.name}：{result['issues'][0]}"
            else:
                draft = next((scene for scene in scenes if scene.status.value != 'published'), None)
                item['query'] = dict(scene=draft.id, preparation='4', step='publish') if draft else {}
    return dict(community_id=community.id, version_name=version.name if version else '尚无底图版本',
                checked_at=datetime.now(UTC).isoformat(), checks=checks,
                passed_count=sum(c['passed'] for c in checks), total_count=len(checks),
                notice='仅检查平台数据完整性与道路图连通性，不代替场景发布校验、演练结果或现实消防安全评估。')

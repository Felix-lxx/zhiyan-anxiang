"""Schematic, explicitly versioned indoor topology; coordinates are training units.

No surveyed building or life-safety accuracy is implied by this example layout.
"""
from copy import deepcopy
import math
from app.services.navigation_geometry import building_obstacles, outdoor_connector
from app.services.indoor_layout import kitchen_rooms


def add_spatial_layout(world: dict, home: dict) -> dict:
    world["schema_version"] = 3
    world["model_notice"] = "示例户型与规则仿真，坐标为训练单位；非实测建筑、非消防安全认证。"
    roads = world["road_network"]
    for edge in roads["edges"]:
        if "南" in edge["name"]:
            edge["status"] = world["parameters"].get("south_lane_status", edge["status"])
    nodes = [{**n, "height": 0, "kind": "outdoor", "floor": 0} for n in roads["nodes"]]
    edges = deepcopy(roads["edges"])
    width = float(world["parameters"].get("stair_width", 1.2))
    buildings = [o for o in world.get("objects", []) if o.get("type") == "building"] or [home]
    obstacles = building_obstacles(world)
    roads["obstacles"] = obstacles
    active_building = home.get("id")
    kitchen = world['parameters'].get('fire_source_type') == 'kitchen'
    if kitchen:
        world['spatial_units'] = {'horizontal_meters_per_unit': 1, 'height_mode': 'meters', 'floor_height_meters': 3.2, 'ground_floor_height_meters': .18}
        world['model_notice'] = '厨房示例户型，平面每单位按1米、高程按米冻结；非实测建筑，烟气为分区训练规则。'
    def floor_height(floor): return round((floor-1)*3.2+.18, 4) if kitchen else floor*1.92

    def node(key, label, px, py, height=0, kind="outdoor", floor=0):
        value = dict(id=key, name=label, x=px, y=py, height=height, kind=kind, floor=floor, is_exit=False, building_id=active_building)
        nodes.append(value)
        return key

    def link(a, b, kind, lane_width=1.5):
        edges.append(dict(id=f"space:{a}:{b}", name={"room": "房门", "corridor": "走廊", "stairs": "楼梯", "door": "楼门", "outdoor": "室外连接", "assembly": "集合通道"}[kind], start_node_id=a, end_node_id=b, width_meters=lane_width, status="open", kind=kind))

    building_ids = {b.get("id") for b in buildings}
    for person in world["residents"]:
        if person.get("building_id") not in building_ids: person["building_id"] = home.get("id")
    for building in buildings:
        active_building = building.get("id")
        prefix = "home" if active_building == home.get("id") else f"building:{active_building}"
        name = building.get("name", "住宅楼")
        x, y = building["x"], building["y"]
        w, d = building.get("width", 5), building.get("depth", 3)
        floors = max(1, building.get("floors", 1))
        stair_width = max(.4, float(building.get("properties", {}).get("stair_width", width)))
        room_geometry = None
        if kitchen:
            try:
                room_geometry = kitchen_rooms(building, stair_width)
            except ValueError:
                if active_building == home.get('id'):
                    raise
                # Other buildings can retain their ordinary residential topology.
        door = node(f"{prefix}:door", name+"楼门", x, y+d/2+.3, kind="door")
        base = node(f"{prefix}:stair:0", name+"首层楼梯出口", x-w*.3, y, kind="stairs")
        foyer = node(f"{prefix}:foyer", name+"门厅", x, y+d/2-.5, kind="door")
        link(base, foyer, "door", 1.5)
        link(foyer, door, "door", 1.5)
        if roads["nodes"]:
            connector = outdoor_connector((x, y+d/2+.3), roads["nodes"], obstacles)
            if connector:
                points, entry = connector
                previous = door
                for index, point in enumerate(points[:-1]):
                    waypoint = node(f"{prefix}:walkway:{index}", name+"门前通道", *point)
                    link(previous, waypoint, "outdoor", 1.2)
                    previous = waypoint
                link(previous, entry["id"], "outdoor", 1.2)
                building["entry"] = {"x": entry["x"], "y": entry["y"]}
                building["access_notice"] = "楼门经可通行路径连接路网。"
            else:
                building["access_notice"] = "楼门无法接入路网，请调整建筑或道路节点。"
        for floor in range(1, floors+1):
            landing = node(f"{prefix}:stair:{floor}", f"{name} · {floor}层楼梯", x-w*.3, y+(.2*d if floor % 2 else -.2*d), floor_height(floor), "stairs", floor)
            hall = node(f"{prefix}:hall:{floor}", f"{name} · {floor}层走廊", x, y, floor_height(floor), "corridor", floor)
            link(hall, landing, "corridor", 1.5)
            link(landing, f"{prefix}:stair:{floor-1}", "stairs", stair_width)
            if room_geometry:
                for side in ('east', 'west'):
                    geometry = room_geometry[side]
                    room_id = node(f'indoor:{active_building}:{floor}:{side}', f"{name} · {floor}层{'东' if side == 'east' else '西'}侧厨房",
                                   geometry['x'], geometry['y'], floor_height(floor), 'room', floor)
                    nodes[-1].update(width=geometry['width'], depth=geometry['depth'])
                    portal = node(f'{room_id}:entry', f'{name} · {floor}层厨房门前走廊', geometry['x'], y, floor_height(floor), 'corridor', floor)
                    nodes[-1].update(width=.9, depth=max(.3, d*.1))
                    link(room_id, portal, 'room', .9)
                    link(portal, hall, 'corridor', 1.5)
        room_occupants = {}
        for index, person in enumerate(p for p in world["residents"] if p.get("building_id") == active_building):
            floor = max(1, min(floors, person["floor"]))
            if room_geometry:
                first_side=world['parameters'].get('fire_room','east')
                side=first_side if (index//floors)%2==0 else ('west' if first_side=='east' else 'east')
                room_id = f"indoor:{active_building}:{floor}:{side}"
                fixed = next(n for n in nodes if n['id'] == room_id)
                slot=room_occupants.get(room_id,0);room_occupants[room_id]=slot+1
                px,py=fixed['x']+(-.32 if slot%2==0 else .32),fixed['y']+(.35 if slot//2==0 else -.35)
                berth=node(f"room-berth:{person['id']}",fixed['name']+' · '+person['label'],px,py,floor_height(floor),'room_berth',floor)
                nodes[-1]['zone_id']=room_id
                link(berth,room_id,'room',.9)
                person.update(floor=floor, current_floor=float(floor), x=px, y=py, height=floor_height(floor), start_node_id=berth,start_zone_id=room_id)
                continue
            px, py = x + w*(.12+.2*((index//floors) % 3)/2), y + (1 if index % 2 else -1)*d*.32
            room = node(f"room:{person['id']}", f"{name} · {floor}层 {person['label']} 房间", px, py, floor_height(floor), "room", floor)
            link(room, f"{prefix}:hall:{floor}", "room", .9)
            person.update(floor=floor, current_floor=float(floor), x=px, y=py, height=floor_height(floor), start_node_id=room)
    active_building = None
    entries = {b.get("id"): b.get("entry") for b in buildings}
    for task in world.get("tasks", []):
        if task.get("target_object_id") in entries:
            task["target_position"] = deepcopy(entries[task["target_object_id"]])
    if home.get("id") in entries:
        world["broadcast_target"] = deepcopy(entries[home["id"]])
    exits = [n for n in roads["nodes"] if n.get("is_exit")]
    destinations = {}
    for direction, choose in (("north", min), ("south", max)):
        if not exits:
            continue
        exit_node = choose(exits, key=lambda n: n["y"])
        dest = node(f"assembly:{direction}", ("北" if direction == "north" else "南")+"侧集合点", exit_node["x"] + (3 if exit_node["x"] < 90 else -3), max(1, min(99, exit_node["y"]+(-4 if direction == "north" else 4))), kind="assembly")
        link(exit_node["id"], dest, "assembly", 3)
        destinations[direction] = dest
    # Dedicated assembly berths keep arrived residents visible as individuals.
    berths = {}
    for direction, hub in destinations.items():
        center = next(n for n in nodes if n["id"] == hub)
        berths[direction] = {}
        columns = max(8, math.ceil(math.sqrt(len(world["residents"]))))
        rows = math.ceil(len(world["residents"])/columns)
        left = max(1., min(99-(columns-1)*.85, center["x"]-(columns-1)*.85/2))
        first_y = max(1+(rows-1)*.85, min(99., center["y"]-.85)) if direction == "south" else max(1., min(99-(rows-1)*.85, center["y"]+.85))
        for i, person in enumerate(world["residents"]):
            slot = node(f"{hub}:{person['id']}", center["name"]+" · "+person["label"], left+(i%columns)*.85, first_y+(i//columns)*.85*(1 if direction == "north" else -1), kind="assembly")
            link(hub, slot, "assembly", .8)
            berths[direction][person["id"]] = slot
    lookup = {n["id"]: n for n in nodes}
    for edge in edges:
        edge.setdefault("kind", "outdoor")
        edge.update(start={k: lookup[edge["start_node_id"]][k] for k in ("x", "y", "height")}, end={k: lookup[edge["end_node_id"]][k] for k in ("x", "y", "height")})
    world["spatial_network"] = {"nodes": nodes, "edges": edges, "destinations": destinations, "berths": berths, "building_id": home.get("id"), "building_ids": [b.get("id") for b in buildings], "stair_width": width}
    if kitchen:
        world['spatial_network']['indoor_layout_version'] = 2
    return world

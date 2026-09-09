"""Schematic, explicitly versioned indoor topology; coordinates are training units.

No surveyed building or life-safety accuracy is implied by this example layout.
"""
from copy import deepcopy
import math


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
    x, y = home["x"], home["y"]
    w, d = home["width"], home["depth"]

    def node(key, label, px, py, height=0, kind="outdoor", floor=0):
        value = dict(id=key, name=label, x=px, y=py, height=height, kind=kind, floor=floor, is_exit=False)
        nodes.append(value)
        return key

    def link(a, b, kind, lane_width=1.5):
        edges.append(dict(id=f"space:{a}:{b}", name={"room": "房门", "corridor": "走廊", "stairs": "楼梯", "door": "楼门", "outdoor": "室外连接", "assembly": "集合通道"}[kind], start_node_id=a, end_node_id=b, width_meters=lane_width, status="open", kind=kind))

    door = node("home:door", "住宅楼门", x, y+d/2+.3, kind="door")
    base = node("home:stair:0", "首层楼梯出口", x-w*.3, y, kind="stairs")
    link(base, door, "door", 1.5)
    if roads["nodes"]:
        entry = min(roads["nodes"], key=lambda n: math.dist((n["x"], n["y"]), (home["entry"]["x"], home["entry"]["y"])))
        link(door, entry["id"], "outdoor", 2)
    for floor in range(1, home.get("floors", 1)+1):
        landing = node(f"home:stair:{floor}", f"{floor}层楼梯", x-w*.3, y+(.2*d if floor % 2 else -.2*d), floor*1.92, "stairs", floor)
        hall = node(f"home:hall:{floor}", f"{floor}层走廊", x, y, floor*1.92, "corridor", floor)
        link(hall, landing, "corridor", 1.5)
        link(landing, f"home:stair:{floor-1}", "stairs", width)
    for index, person in enumerate(world["residents"]):
        floor = person["floor"]
        px, py = x + w*(.12+.2*((index//home.get("floors", 1)) % 3)/2), y + (1 if index % 2 else -1)*d*.32
        room = node(f"room:{person['id']}", f"{floor}层 {person['label']} 房间", px, py, floor*1.92, "room", floor)
        link(room, f"home:hall:{floor}", "room", .9)
        person.update(x=px, y=py, height=floor*1.92, start_node_id=room)
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
        for i, person in enumerate(world["residents"]):
            slot = node(f"{hub}:{person['id']}", center["name"]+" · "+person["label"], center["x"]+(i%8-3.5)*.85, center["y"]+(i//8+1)*.85*(1 if direction == "north" else -1), kind="assembly")
            link(hub, slot, "assembly", .8)
            berths[direction][person["id"]] = slot
    lookup = {n["id"]: n for n in nodes}
    for edge in edges:
        edge.setdefault("kind", "outdoor")
        edge.update(start={k: lookup[edge["start_node_id"]][k] for k in ("x", "y", "height")}, end={k: lookup[edge["end_node_id"]][k] for k in ("x", "y", "height")})
    world["spatial_network"] = {"nodes": nodes, "edges": edges, "destinations": destinations, "berths": berths, "building_id": home.get("id"), "stair_width": width}
    return world

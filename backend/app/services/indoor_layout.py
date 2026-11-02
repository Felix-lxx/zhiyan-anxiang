"""Geometry for newly frozen kitchen worlds, shared by fire and walking nodes."""
import math


CORRIDOR_CLEAR_WIDTH = 1.5


def door_portal(room: dict, hall: dict, width: float) -> dict:
    """Freeze the wall intersection, not the room centre or the hallway node."""
    dx, dy = hall['x'] - room['x'], hall['y'] - room['y']
    length = math.hypot(dx, dy)
    if length < 1e-8:
        raise ValueError('房门通道缺少方向，请检查房间与走廊位置。')
    t = min(1., room['width'] / (2 * abs(dx)) if dx else math.inf,
            room['depth'] / (2 * abs(dy)) if dy else math.inf)
    return dict(x=room['x'] + dx*t, y=room['y'] + dy*t, height=room['height'],
                width=width, normal_x=dx/length, normal_y=dy/length,
                clearance_radius=.28, wall_depth=.1)


def kitchen_rooms(building: dict, stair_width: float = 1.2) -> dict:
    x, y = building['x'], building['y']
    width, depth = building['width'], building['depth']
    # Reserve the stair flight, its slab opening and a solid landing margin.
    left = x - width * .3 + stair_width / 2 + .2
    right = x + width / 2 - .2
    room_width = (right - left - .2) / 2
    # The room wall must sit beyond the actual corridor half-width and wall margin.
    # The previous 5%-of-depth gap was only .4 m in an 8 m building.
    corridor_front = y - CORRIDOR_CLEAR_WIDTH / 2 - .10
    rear_wall = y - depth / 2 + .10
    room_depth = min(depth * .4, corridor_front - rear_wall)
    if room_width < 1.2 or room_depth < 1.12:
        raise ValueError('住宅平面过小或楼梯过宽，无法容纳两间厨房及独立通道；请调整建筑宽深或楼梯宽度。')
    return {
        side: {'x': left + room_width / 2 + index * (room_width + .2),
               'y': corridor_front - room_depth / 2, 'width': room_width, 'depth': room_depth}
        for index, side in enumerate(('west', 'east'))
    }

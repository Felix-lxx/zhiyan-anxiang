"""Geometry for newly frozen kitchen worlds, shared by fire and walking nodes."""


def kitchen_rooms(building: dict, stair_width: float = 1.2) -> dict:
    x, y = building['x'], building['y']
    width, depth = building['width'], building['depth']
    # Reserve the stair flight, its slab opening and a solid landing margin.
    left = x - width * .3 + stair_width / 2 + .2
    right = x + width / 2 - .2
    room_width = (right - left - .2) / 2
    room_depth = depth * .4
    if room_width < 1.2 or room_depth < 1.12:
        raise ValueError('住宅平面过小或楼梯过宽，无法容纳两间厨房及独立通道；请调整建筑宽深或楼梯宽度。')
    return {
        side: {'x': left + room_width / 2 + index * (room_width + .2),
               'y': y - depth * .25, 'width': room_width, 'depth': room_depth}
        for index, side in enumerate(('west', 'east'))
    }

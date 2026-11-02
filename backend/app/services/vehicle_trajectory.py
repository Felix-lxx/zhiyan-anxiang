"""Persist vehicle turn samples with the command, so live and replay use one path."""

import math

from app.services.mobility_geometry import half_length
from app.services.navigation_geometry import clear_segment


def rounded_trajectory(points: list[dict], actor: dict, edges: dict, obstacles: list[dict]) -> list[dict]:
    """Round a planned turn only when the sampled vehicle envelope clears buildings."""
    if len(points) < 3 or actor.get("kind") == "stretcher":
        return points

    output = [points[0]]
    for previous, corner, following in zip(points, points[1:], points[2:]):
        incoming = math.dist((previous["x"], previous["y"]), (corner["x"], corner["y"]))
        outgoing = math.dist((corner["x"], corner["y"]), (following["x"], following["y"]))
        if min(incoming, outgoing) < 0.01:
            output.append(corner)
            continue

        entry = ((corner["x"] - previous["x"]) / incoming,
                 (corner["y"] - previous["y"]) / incoming)
        exit_ = ((following["x"] - corner["x"]) / outgoing,
                 (following["y"] - corner["y"]) / outgoing)
        if entry[0] * exit_[0] + entry[1] * exit_[1] > 0.995:
            output.append(corner)
            continue

        width = min(
            edges.get(point.get("edge_id"), {}).get("width_meters", actor["minimum_width"])
            for point in (corner, following)
        )
        radius = min(incoming * 0.25, outgoing * 0.25, width * 0.4)
        start = (corner["x"] - entry[0] * radius, corner["y"] - entry[1] * radius)
        end = (corner["x"] + exit_[0] * radius, corner["y"] + exit_[1] * radius)

        samples = []
        for index in range(13):
            t = index / 12
            x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * corner["x"] + t * t * end[0]
            y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * corner["y"] + t * t * end[1]
            dx = (1 - t) * (corner["x"] - start[0]) + t * (end[0] - corner["x"])
            dy = (1 - t) * (corner["y"] - start[1]) + t * (end[1] - corner["y"])
            tangent_length = math.hypot(dx, dy)
            if tangent_length < 1e-8:
                samples = []
                break

            reach = half_length(actor)
            front = (x + dx / tangent_length * reach, y + dy / tangent_length * reach)
            rear = (x - dx / tangent_length * reach, y - dy / tangent_length * reach)
            if not clear_segment(rear, front, obstacles, actor["minimum_width"] / 2):
                samples = []
                break
            samples.append({"x": x, "y": y,
                            "edge_id": corner.get("edge_id") if t < 0.5 else following.get("edge_id")})

        # A rejected curve never changes the already validated road path.
        output.extend(samples if samples else [corner])

    output.append(points[-1])
    return output

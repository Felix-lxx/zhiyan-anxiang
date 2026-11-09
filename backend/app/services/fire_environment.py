"""One event-derived environmental curve for live, forecast and replay."""
from bisect import bisect_right


class EnvironmentTimeline:
    def __init__(self, world, events):
        self.kitchen = bool(world.get('indoor_environment'))
        self.indoor = None
        self.times, self.knots = [], []
        failed = world["parameters"].get("hydrant_status") in {"faulty", "failed"}
        resources = world.get('water_resources')
        sources = {item['id']: dict(item) for item in resources['sources']} if resources else None
        primary_id = resources['primary_id'] if resources else None
        self.primary_id = primary_id
        if sources is not None:
            failed = sources.get(primary_id, {}).get('state') == 'failed'
        resource, power, intensity, smoke, previous = False, False, 18., 7., 0.
        active = {}
        changes = []
        for event in events:
            kind, data, at = event["event_type"], event["payload"], event["elapsed_seconds"]
            if kind in {"inject.hydrant_failure", "participant.resource_ready", "task.completed", "vehicle.action_stopped", "vehicle.action_started"}:
                changes.append((at, event["sequence"], kind, data))
            if kind == "vehicle.action_started" and data.get("action") == "spray":
                changes.append((at + data["duration_seconds"], -1, "spray.expired", data))
        def rates():
            water = (any(sources.get(source_id, {}).get('state') == 'available' for source_id in active.values())
                     if sources is not None else bool(active) and not failed) and not self.kitchen
            growth = (1.15 if failed else .82) * (.55 if resource else 1) * (.35 if power else 1)
            return (-3.2 if water else growth if intensity > 0 else 0), (-.35 if water else .34 * growth / .82 if intensity > 0 else -.15), water
        def knot(at):
            rate, smoke_rate, water = rates()
            self.times.append(at)
            self.knots.append((intensity, smoke, rate, smoke_rate, failed, resource, power, water,
                               [dict(item) for item in sources.values()] if sources is not None else None))
        knot(0.)
        for at, _, kind, data in sorted(changes, key=lambda item: (item[0], item[1])):
            rate, smoke_rate, _ = rates()
            intensity = max(0., min(100., intensity + (at - previous) * rate))
            smoke = max(0., min(48., smoke + (at - previous) * smoke_rate))
            previous = at
            if kind == "inject.hydrant_failure":
                if sources is None:
                    failed = True
                else:
                    source_id = data.get('hydrant_id') or primary_id
                    if source_id in sources:
                        sources[source_id]['state'] = 'failed'
                    failed = sources.get(primary_id, {}).get('state') == 'failed'
            elif kind == "participant.resource_ready": resource = True
            elif kind == "task.completed" and data.get("kind") in {"power_off", "gas_off"}: power = True
            elif kind == "vehicle.action_started" and data.get("action") == "spray":
                active[data['action_id']] = (data.get('water_source') or {}).get('id') or primary_id
            elif kind in {"vehicle.action_stopped", "spray.expired"}: active.pop(data.get("action_id"), None)
            knot(at)
        if self.kitchen:
            from app.services.indoor_fire import KitchenSmokeTimeline
            self.indoor = KitchenSmokeTimeline(world, events, self._base_at)

    def _base_at(self, elapsed):
        index = max(0, bisect_right(self.times, elapsed) - 1)
        intensity, smoke, rate, smoke_rate, failed, resource, power, water, sources = self.knots[index]
        delta = max(0, elapsed - self.times[index])
        intensity = max(0., min(100., intensity + delta * rate))
        smoke = max(0., min(48., smoke + delta * smoke_rate))
        return ({"intensity": round(intensity, 1), "smoke_radius": round(smoke, 2), "temperature": round(34 + intensity * 3.8, 1)},
                {"east_hydrant": "failed" if failed else "available", "resource_ready": resource, "power_off": power and not self.kitchen, "water_suppression": water,
                 **({'hydrants': [dict(item) for item in sources], 'primary_hydrant_id': self.primary_id} if sources is not None else {}),
                 **({'gas_off':power} if self.kitchen else {})})

    def at(self, elapsed):
        fire, environment = self._base_at(elapsed)
        if self.indoor:
            indoor = self.indoor.at(elapsed)
            environment['indoor'] = indoor
        return fire, environment

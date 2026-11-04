"""Accumulate the existing smoke dose and retain its first threshold crossing."""
EXPOSURE_THRESHOLD = 5


def accumulate_exposure(person, density, duration, at_seconds):
    previous = person['smoke_exposure']
    increment = density * duration * (1.2 if person['vulnerable'] else .85)
    person['smoke_exposure'] = previous + increment
    if previous <= EXPOSURE_THRESHOLD < person['smoke_exposure'] and increment > 0:
        person.setdefault('smoke_exposed_at_seconds', at_seconds + duration * (EXPOSURE_THRESHOLD - previous) / increment)
        person.setdefault('smoke_exposed_location', {key: person.get(key) for key in ('node_id', 'edge_id', 'x', 'y', 'height')})

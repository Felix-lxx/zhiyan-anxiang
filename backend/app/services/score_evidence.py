"""Explain outcome times separately from the commands that influenced them."""
from math import ceil

from app.services.exposure import EXPOSURE_THRESHOLD


def attach_result_evidence(details, history, simulation):
    observed = simulation.get('elapsed_seconds')
    commands = [event for event in history if event.event_type == 'resident.command']
    related_at = max((event.elapsed_seconds for event in commands), default=None)
    for detail in details:
        detail['time_basis'] = 'event' if detail['event_ids'] else 'observation'
        if not detail['event_ids'] and observed is not None:
            detail['at_seconds'] = observed
        if observed is not None:
            detail['observed_at_seconds'] = observed
    people = simulation['residents']
    missing = {event.payload.get('resident_id'): event for event in history if event.event_type == 'inject.resident_missing'}
    nodes = {node['id']: node.get('name', node['id']) for node in simulation.get('spatial_network', {}).get('nodes', [])}
    edges = {edge['id']: edge.get('name', edge['id']) for edge in simulation.get('spatial_network', {}).get('edges', [])}
    risk = details[1]
    occurrences = []
    for person in people:
        if person.get('smoke_exposure', 0) > EXPOSURE_THRESHOLD:
            location = person.get('smoke_exposed_location') or {}
            occurrences.append({'resident_id': person['id'], 'label': person.get('label', person['id']),
                'kind': 'smoke_exposure', 'at_seconds': person.get('smoke_exposed_at_seconds'),
                'location': edges.get(location.get('edge_id')) or nodes.get(location.get('node_id'))})
        if person.get('status') == 'missing':
            event = missing.get(person['id'])
            occurrences.append({'resident_id': person['id'], 'label': person.get('label', person['id']),
                'kind': 'missing', 'at_seconds': event.elapsed_seconds if event else None, 'location': None})
    known = [item['at_seconds'] for item in occurrences if item['at_seconds'] is not None]
    risk.update(related_command_at_seconds=related_at, affected_count=len({item['resident_id'] for item in occurrences}),
                occurrence_count=len(occurrences), occurrences=sorted(occurrences, key=lambda item: item['at_seconds'] if item['at_seconds'] is not None else float('inf'))[:12])
    if known:
        # Replay uses integer seconds: never round back before the dose crossed.
        risk.update(at_seconds=ceil(min(known) + 1e-7), time_basis='occurrence')
    elif observed is not None:
        risk.update(at_seconds=observed, time_basis='observation')
    else:
        risk['time_basis'] = 'related_event'
    for detail, selected in [(details[3], [p for p in people if p.get('vulnerable') and p.get('assisted')]), (details[5], people)]:
        arrivals = [p.get('assembly_arrived_at_seconds', p.get('evacuated_at_seconds')) for p in selected if p['status'] == 'evacuated']
        arrivals = [at for at in arrivals if at is not None]
        detail['related_command_at_seconds'] = related_at
        if arrivals:
            detail.update(at_seconds=ceil(max(arrivals)), time_basis='occurrence')
        elif observed is not None:
            detail.update(at_seconds=observed, time_basis='observation')
        else:
            detail['time_basis'] = 'related_event'

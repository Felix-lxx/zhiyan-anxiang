"""Independent, reproducible member needs frozen with each new community world."""
from random import Random


TRAIT_LABELS = {'mobility':'需协助行动', 'direct_contact':'需直接联系', 'sleeping':'夜间熟睡'}


def assign_profiles(people, parameters):
    count = len(people)
    seed = int(parameters.get('simulation_seed', 2026))
    configured = parameters.get('population_profile')
    profile = {
        'mobility_count': 1, 'direct_contact_count': max(1, count//5),
        'sleeping_count': max(1, count//3), 'awake_preparation_seconds':8,
        'sleeping_preparation_seconds':25, 'walking_speed':1.25, 'mobility_walking_speed':.65,
    }
    profile.update(configured or {})
    members = {}
    # Independent streams: adjusting one need does not reshuffle the other two.
    for offset, (trait, field) in enumerate((('mobility','mobility_count'),
                                           ('direct_contact','direct_contact_count'),
                                           ('sleeping','sleeping_count'))):
        indices = list(range(count))
        Random(f'{seed}:{trait}:{offset}').shuffle(indices)
        members[trait] = set(indices[:profile[field]])
    for index, person in enumerate(people):
        traits = [trait for trait in TRAIT_LABELS if index in members[trait]]
        mobility, sleeping = 'mobility' in traits, 'sleeping' in traits
        person.update(
            traits=traits, profile='mobility' if mobility else 'hearing' if 'direct_contact' in traits else 'sleeping' if sleeping else 'standard',
            profile_label=' · '.join(TRAIT_LABELS[trait] for trait in traits) or '自主行动',
            vulnerable=mobility, notification_need='direct_contact' if 'direct_contact' in traits else 'standard',
            walking_speed=profile['mobility_walking_speed'] if mobility else profile['walking_speed'],
            preparation_seconds=profile['sleeping_preparation_seconds'] if sleeping else profile['awake_preparation_seconds'],
        )
    return {'version':1, 'configuration':profile, 'configured':bool(configured),
            'overlap_count':sum(len(person['traits'])>1 for person in people)}

"""Freeze independent model identities; reading history never upgrades its rules."""


def freeze_model_manifest(world):
    community = world.get('community_training') or {}
    indoor = world.get('indoor_environment') or {}
    world['model_manifest'] = {
        'version': 1,
        'environment': 'causal_training_v2',
        'residents': f"community_v{community['version']}" if community else 'baseline_v1',
        'orchestration': 'notice_gates_v1' if community.get('version', 0) >= 4 else 'commands_v1',
        'height_coordinates': world.get('spatial_units', {}).get('height_mode', 'schematic'),
        'indoor_geometry': indoor.get('geometry_revision'),
        'kitchen_equipment': indoor.get('equipment_layout_version'),
        'residential_units': (world.get('residential_units') or {}).get('version'),
        'scoring': 4,
    }


def causal_environment(world):
    manifest = world.get('model_manifest')
    if manifest is None:
        # Exact historical fallback, including pre-manifest night-shift worlds.
        return bool(world.get('community_training'))
    model = manifest['environment']
    if model not in {'causal_training_v2', 'legacy_training_v1'}:
        raise ValueError('不支持该冻结环境模型，请核对场次版本。')
    return model == 'causal_training_v2'

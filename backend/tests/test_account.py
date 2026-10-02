from app.core.security import create_access_token


def headers(username='admin'):
    return {'Authorization': 'Bearer ' + create_access_token(username)}


def profile_data(**changes):
    return {'display_name': '安巷值班员', 'organization': '安巷社区', 'text_size': 'large',
            'reduced_motion': True, 'default_community_id': None, 'revision': 0, **changes}


def test_profile_persists_and_isolates_accounts(client):
    assert client.get('/api/v1/account/profile').status_code == 401
    before = client.get('/api/v1/account/profile', headers=headers()).json()
    assert before['revision'] == 0
    response = client.patch('/api/v1/account/profile', headers=headers(), json=profile_data())
    assert response.status_code == 200, response.text
    restored = client.get('/api/v1/account/profile', headers=headers()).json()
    assert restored['display_name'] == '安巷值班员'
    assert restored['text_size'] == 'large' and restored['reduced_motion'] is True
    assert restored['revision'] == 1 and restored['updated_at']
    other = client.get('/api/v1/account/profile', headers=headers('another')).json()
    assert other['display_name'] == 'another' and other['organization'] == ''


def test_profile_validation_and_concurrent_edit_protection(client):
    assert client.patch('/api/v1/account/profile', headers=headers(), json=profile_data(display_name='   ')).status_code == 422
    assert client.patch('/api/v1/account/profile', headers=headers(), json=profile_data(role='系统管理员')).status_code == 422
    assert client.patch('/api/v1/account/profile', headers=headers(), json=profile_data()).status_code == 200
    assert client.patch('/api/v1/account/profile', headers=headers(), json=profile_data(display_name='过期页面')).status_code == 409
    assert client.get('/api/v1/account/profile', headers=headers()).json()['display_name'] == '安巷值班员'
    assert client.patch('/api/v1/account/profile', headers=headers(), json=profile_data(display_name='新的名称', revision=1)).status_code == 200
    assert client.get('/api/v1/account/profile', headers=headers()).json()['revision'] == 2


def test_default_community_and_activity_are_owner_scoped(client):
    demo = client.post('/api/v1/communities/demo-ready', headers=headers()).json()
    community = demo['community']['id']
    saved = client.patch('/api/v1/account/profile', headers=headers(), json=profile_data(default_community_id=community))
    assert saved.status_code == 200, saved.text
    forbidden = client.patch('/api/v1/account/profile', headers=headers('another'), json=profile_data(default_community_id=community))
    assert forbidden.status_code == 422
    own = client.get('/api/v1/account/activity', headers=headers()).json()
    assert own['community_count'] == 1 and own['drill_count'] >= 1
    assert own['recent'][0]['community_id'] == community
    assert own['recent'][0]['score'] is None  # no invented score for an unfinished drill
    other = client.get('/api/v1/account/activity', headers=headers('another')).json()
    assert other['drill_count'] == 0 and other['recent'] == []

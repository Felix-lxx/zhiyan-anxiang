from sqlalchemy import select

from app.api.routes import operations
from app.core.config import get_settings
from app.models.domain import MapObject
from app.schemas.scene import KitchenParametersUpdate
from app.services.scene_parameters import initial_parameters


def prepare(client):
    token = client.post('/api/v1/auth/login', json={'username':'admin','password':get_settings().bootstrap_admin_password}).json()['access_token']
    headers={'Authorization':'Bearer '+token}
    community=client.post('/api/v1/communities/demo',headers=headers).json()
    template=next(t for t in client.get('/api/v1/scene-templates',headers=headers).json() if t['code']=='kitchen_fire')
    return headers,community,template


def test_kitchen_draft_contains_real_source_and_all_required_defaults(client):
    headers,community,template=prepare(client)
    response=client.post('/api/v1/communities/'+community['id']+'/scenes',headers=headers,json={'template_id':template['id'],'name':'完整厨房草稿'})
    assert response.status_code==201,response.text
    scene=response.json();parameters=scene['versions'][-1]['parameters']
    KitchenParametersUpdate.model_validate(parameters)
    assert scene['status']=='draft' and parameters['resident_count']==8
    root='/api/v1/scenes/'+scene['id']
    preview=client.get(root+'/preview',headers=headers)
    assert preview.status_code==200,preview.text
    world=preview.json()['simulation']['world']
    assert world['fire_source']['location']['object_id']==parameters['fire_source_object_id']
    assert world['fire_source']['location']['floor']==parameters['fire_floor']
    assert len(world['tasks'])==4


def test_ambiguous_custom_map_does_not_silently_pick_a_house(client):
    _,community,template=prepare(client)
    with operations.SessionLocal() as db:
        objects=list(db.scalars(select(MapObject)))
        for obj in objects:
            obj.properties={k:v for k,v in obj.properties.items() if k!='indoor_layout_version'}
        db.flush()
        version=objects[0].community_version_id
        parameters=initial_parameters(db,version,template['defaults'])
        assert 'fire_source_object_id' not in parameters
        explicit=initial_parameters(db,version,{**template['defaults'],'fire_source_object_id':'explicit-selection','resident_count':16})
        assert explicit['fire_source_object_id']=='explicit-selection'
        assert explicit['resident_count']==16

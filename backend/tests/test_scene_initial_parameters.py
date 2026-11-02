from sqlalchemy import select

from app.api.routes import operations
from app.core.config import get_settings
from app.models.domain import Community, MapObject, MapObjectType, SceneVersion
from app.schemas.scene import KitchenParametersUpdate
from app.services.scene_parameters import initial_parameters
from app.services.fire_sources import resolve_fire_source
from app.services.exercise_world import capture_world
from app.services.demo_community import repair_builtin_demo_buildings


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


def test_all_builtin_houses_accept_kitchen_fire_selection(client):
    headers, community, template = prepare(client)
    created = client.post('/api/v1/communities/'+community['id']+'/scenes', headers=headers,
                          json={'template_id': template['id'], 'name': '五栋住宅厨房选点'}).json()
    with operations.SessionLocal() as db:
        version = db.get(SceneVersion, created['versions'][-1]['id'])
        assert version is not None
        houses = list(db.scalars(select(MapObject).where(
            MapObject.community_version_id == community['versions'][-1]['id'],
            MapObject.object_type == MapObjectType.BUILDING,
        )))
        assert len(houses) == 5
        for house in houses:
            params = {**template['defaults'], 'fire_source_type': 'kitchen',
                      'fire_source_object_id': house.id, 'fire_floor': 2,
                      'fire_room': 'east', 'resident_count': 8}
            assert resolve_fire_source(db, house.community_version_id, params).id == house.id
            world = capture_world(db, version, params)
            assert world['fire_source']['location']['object_id'] == house.id
            assert world['indoor_environment']['zones']


def test_builtin_demo_repair_respects_custom_house_geometry(client):
    _, community, _ = prepare(client)
    with operations.SessionLocal() as db:
        houses = {obj.name: obj for obj in db.scalars(select(MapObject).where(
            MapObject.community_version_id == community['versions'][-1]['id'],
            MapObject.object_type == MapObjectType.BUILDING,
        ))}
        houses['2 号楼'].properties = {'floors': 6, 'resident_groups': '普通居民'}
        houses['2 号楼'].geometry = {'x': 46, 'y': 24}
        houses['4 号楼'].geometry = {'x': 38, 'y': 66}
        db.flush()
        owner = db.get(Community, community['id'])
        assert repair_builtin_demo_buildings(db, owner)
        assert houses['2 号楼'].geometry == {'x': 46, 'y': 22}
        assert houses['2 号楼'].properties['width'] == 8.5
        assert houses['4 号楼'].geometry == {'x': 38, 'y': 66}
        assert not repair_builtin_demo_buildings(db, owner)


def test_ambiguous_custom_map_does_not_silently_pick_a_house(client):
    _,community,template=prepare(client)
    with operations.SessionLocal() as db:
        objects=list(db.scalars(select(MapObject)))
        for obj in objects:
            obj.properties={k:v for k,v in obj.properties.items() if k!='indoor_layout_version'}
            # Keep several houses eligible after the stricter kitchen/corridor
            # geometry validation. A single legal candidate is not ambiguous.
            if obj.object_type.value == 'building':
                obj.properties={**obj.properties,'width':8.5,'depth':8}
        db.flush()
        version=objects[0].community_version_id
        parameters=initial_parameters(db,version,template['defaults'])
        assert 'fire_source_object_id' not in parameters
        explicit=initial_parameters(db,version,{**template['defaults'],'fire_source_object_id':'explicit-selection','resident_count':16})
        assert explicit['fire_source_object_id']=='explicit-selection'
        assert explicit['resident_count']==16

from app.services.knowledge_applicability import assess_experience, situation, assessment
from app.services.simulation_checkpoints import ENGINE_REVISION
from app.services.knowledge import retrieve
from app.api.routes import operations
from test_exercise_world import exercise
from test_knowledge_experience import observed_plan, publish


def test_condition_differences_and_missing_source_are_not_treated_as_matches():
    current={'parameters':{'fire_source_object_id':'building-a','resident_count':60,'stair_width':1.2},
             'engine_revision':ENGINE_REVISION,'target_population':8,'at_seconds':20,'event_sequence':4}
    source={'parameters':dict(current['parameters']),'observed_engine_revision':ENGINE_REVISION,'population':8}
    assert assess_experience(source,current)['status']=='matched'
    changed={**source,'parameters':{**source['parameters'],'stair_width':.9},'population':2}
    result=assess_experience(changed,current)
    assert {d['field'] for d in result['differences']}=={'stair_width','population'}
    del source['parameters']['fire_source_object_id']
    assert assess_experience(source,current)['status']=='unverified'
    assert assess_experience(source,None)['status']=='unchecked'
    assert assess_experience(None,current)['status']=='unverified'


def test_model_revision_and_historical_snapshot_conditions_are_explicit():
    data={'elapsed_seconds':30,'latest_event_sequence':5,'simulation':{'world':{'parameters':{'resident_count':4}}}}
    current=situation(data,{'resident_ids':['p1']})
    source={'parameters':{'resident_count':4},'population':1,'observed_engine_revision':'old'}
    result=assess_experience(source,current)
    assert result['status']=='different' and result['differences'][0]['field']=='engine_revision'
    assert result['at_seconds']==30 and result['event_sequence']==5
    assert current['target_population']==1


def test_published_experience_retrieval_pins_scope_comparison(exercise):
    client,headers,_,root,*_=exercise
    plan=observed_plan(exercise)
    document=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1}).json()['document']
    publish(client,headers,document)
    source=document['experience']
    from app.models.operations import DrillSession
    from app.models.domain import Scene
    with operations.SessionLocal() as session:
        drill=session.get(DrillSession,root.split('/')[4])
        scene=session.get(Scene,drill.scene_id)
        current={'parameters':source['parameters'],'engine_revision':ENGINE_REVISION,
                 'at_seconds':90,'event_sequence':10,'target_population':source['population']+1}
        result=retrieve(session,'admin',document['title'],community_id=scene.community_id,
                        drill_id=drill.id,situation=current)
        session.commit()
    hit=next(hit for hit in result['hits'] if hit['document_id']==document['id'])
    assert hit['applicability']['status']=='different'
    assert hit['id'] in result['assessment']['excluded_citations']
    record=client.get('/api/v1/knowledge/retrievals/'+result['retrieval_id'],headers=headers).json()
    assert record['hits']==result['hits']
    assert assessment(record['hits'])==result['assessment']

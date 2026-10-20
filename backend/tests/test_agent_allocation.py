from app.services.agent_allocation import allocate_exits


def setup_routes(count=8):
    people = {f'p{i}': {'id':f'p{i}', 'vulnerable':i==0, 'status':'waiting'} for i in range(count)}
    edges = [{'id':exit, 'name':exit, 'length':10 if exit=='north' else 12,
        'flow_capacity_per_second':.35 if exit=='north' else 3, 'risk_score':0, 'smoke_risk':0, 'status':'open'} for exit in ('north','south')]
    routes = {exit: {pid: {'route_reachable':True, 'route_edge_ids':[exit], 'route_points':[{'x':0,'y':0},{'x':edge['length'],'y':0}]} for pid in people}
        for exit,edge in zip(('north','south'),edges)}
    return routes, people, edges


def test_capacity_policy_distributes_real_shared_demand_and_never_invents_unreachable_route():
    routes, people, edges = setup_routes()
    result = allocate_exits(routes, people, edges, list(people))
    shortest, balanced = result[0][0], result[1][0]
    assert set(shortest.values()) == {'north'}
    assert set(balanced.values()) == {'north','south'}
    assert result[1][1]['changed_residents'] > 0
    assert sum(b['assigned'] for b in result[1][1]['bottlenecks']) == len(people)
    routes['south']['p0']['route_reachable'] = False
    assert allocate_exits(routes, people, edges, list(people))[1][0]['p0'] == 'north'


def test_smoke_changes_allocation_but_equal_policies_are_reported_honestly():
    routes, people, edges = setup_routes(1)
    assert allocate_exits(routes, people, edges, list(people))[1][1]['same_allocation']
    edges[0].update(smoke_risk=90,risk_score=90)
    result = allocate_exits(routes, people, edges, list(people))
    assert result[0][0]['p0'] == 'north' and result[1][0]['p0'] == 'south'
    assert not result[1][1]['same_allocation']


def test_waiters_are_not_double_counted_and_confirmed_retreat_remains_available():
    routes, people, edges = setup_routes(1)
    people['p0']['waiting_for_edge'] = 'north'
    edges[0].update(waiting_count=1,status='blocked')
    result = allocate_exits(routes, people, edges, list(people))
    assert result[1][0]['p0'] == 'north'  # Authoritative route is a valid retreat.
    assert result[0][1]['bottlenecks'][0]['waiting'] == 0
    edges[0]['waiting_count'] = 20
    assert allocate_exits(routes, people, edges, list(people))[1][0]['p0'] == 'south'

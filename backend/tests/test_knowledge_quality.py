from app.evaluation.knowledge import evaluate
from app.services.knowledge_ranking import matching_phrases
from test_knowledge import login


def test_fixed_corpus_retrieves_expected_sources_and_abstains_from_unrelated_questions():
    result = evaluate()
    assert result['case_count'] == 22
    assert result['hit_at_3'] == 1, [case for case in result['cases'] if case['expected'] and (case['rank'] is None or case['rank'] > 3)]
    assert result['negative_empty_rate'] == 1, [case for case in result['cases'] if not case['expected'] and case['retrieved']]


def test_alias_questions_and_match_provenance_survive_retrieval_history(client):
    headers = login(client)
    client.get('/api/v1/knowledge/documents', headers=headers)
    for question in ['煤气漏了怎么办', '电动车在楼梯间停放']:
        response = client.post('/api/v1/knowledge/search', headers=headers, json={'query': question}).json()
        assert response['hits'], question
        hit = response['hits'][0]
        assert hit['match']['method'] == 'keyword'
        assert hit['match']['ranking_revision'] == 'lexical-v2'
        assert hit['match']['terms'] or hit['match']['expanded_terms']
        stored = client.get('/api/v1/knowledge/retrievals/' + response['retrieval_id'], headers=headers).json()
        assert stored['hits'][0]['match'] == hit['match']
    response = client.post('/api/v1/knowledge/search', headers=headers, json={'query': '小区附近有什么餐厅推荐？'}).json()
    assert response['hits'] == []
    assert '未找到足够匹配' in response['notice']


def test_match_labels_rejoin_adjacent_terms_without_inventing_phrases():
    assert matching_phrases('燃气泄漏与房门', {'燃气', '气泄', '泄漏', '房门'}) == ['燃气泄漏', '房门']

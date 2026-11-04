from copy import deepcopy

from app.services.knowledge_ingestion import chunks, digest
from test_knowledge import login, publish


def test_chunk_keeps_a_complete_condition_across_old_window_boundary():
    prefix = '日常巡查须记录设施状态。' * 60
    prefix = prefix[:570 - 1] + '。'
    condition = '海棠楼房门操作前必须核对走廊和房间内仍在等待的所有居民' + '，由负责值守员逐项核对通行与人员状态并记录证据' * 7 + '。'
    content = prefix + condition + '后续安排应记录交接人员与复核时间。' * 40
    legacy = [content[offset:offset + 700] for offset in range(0, len(content), 600)]
    parts = chunks([('正文', content)])
    assert not any(condition in part for part in legacy)
    assert any(condition in part for _, part in parts)
    assert all(0 < len(part) <= 700 for _, part in parts)


def test_long_unpunctuated_data_is_bounded_and_page_anchors_are_kept():
    parts = chunks([('PDF 第 1 页', '甲' * 1700), ('PDF 第 2 页', '第二页的核对说明。' * 20)])
    assert len(parts) == 4
    assert all(len(part) <= 700 for _, part in parts)
    assert parts[-1][0].startswith('PDF 第 2 页')
    assert ''.join(part for _, part in parts[:-1]) == '甲' * 1700


def test_late_section_is_retrieved_and_old_citation_survives_revision(client):
    headers = login(client)
    content = '\n\n'.join(f'第{index}项：日常设施检查说明。' * 30 for index in range(12))
    target = '海棠燃气隔离核验：由指定值守员确认设备身份、接受责任任务、到位后提交实际处置证据。'
    payload = {'title': '海棠厨房组织预案', 'content': content + '\n\n' + target, 'scenario': 'kitchen_fire'}
    doc = client.post('/api/v1/knowledge/documents', headers=headers, json=payload).json()
    publish(client, headers, doc)
    result = client.post('/api/v1/knowledge/search', headers=headers,
                         json={'query': '海棠燃气隔离核验', 'scenario': 'kitchen_fire'}).json()
    hit = next(item for item in result['hits'] if item['document_id'] == doc['id'])
    assert target in hit['content']
    version = doc['versions'][0]
    assert hit['chunk_id'] != version['chunks'][0]['id']
    assert hit['content_hash'] == digest(hit['content'])
    old_chunks = deepcopy(version['chunks'])
    payload['content'] += '\n\n新版本补充：值守员应报告复核结果。'
    revised = client.post('/api/v1/knowledge/documents/' + doc['id'] + '/versions', headers=headers, json=payload).json()
    publish(client, headers, revised)
    after = client.get('/api/v1/knowledge/documents/' + doc['id'], headers=headers).json()
    assert next(item for item in after['versions'] if item['id'] == version['id'])['chunks'] == old_chunks
    historical = client.get('/api/v1/knowledge/retrievals/' + result['retrieval_id'], headers=headers).json()
    assert historical['hits'] == result['hits']

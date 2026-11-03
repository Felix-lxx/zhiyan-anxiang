"""Optional explicit Embedding integration; never substitutes fabricated vectors."""
import math
import hashlib
from urllib.parse import urlsplit
import httpx
from app.core.config import get_settings


def configured():
    s = get_settings()
    return bool(s.knowledge_embedding_url and s.knowledge_embedding_model)


def index_identity():
    s = get_settings()
    fingerprint = hashlib.sha256(s.knowledge_embedding_url.encode()).hexdigest()[:12]
    return s.knowledge_embedding_model[:150] + '@' + fingerprint


def embed(texts):
    settings = get_settings()
    url = urlsplit(settings.knowledge_embedding_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Embedding 地址必须为不带查询参数的 HTTPS 接口。')
    headers = {'Content-Type': 'application/json'}
    if settings.knowledge_embedding_key.get_secret_value():
        headers['Authorization'] = 'Bearer ' + settings.knowledge_embedding_key.get_secret_value()
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        with client.stream('POST', settings.knowledge_embedding_url, headers=headers,
                           json={'model': settings.knowledge_embedding_model, 'input': texts}) as response:
            response.raise_for_status()
            raw = bytearray()
            for part in response.iter_bytes():
                raw.extend(part)
                if len(raw) > 4_000_000:
                    raise ValueError('向量结果过大。')
    import json
    data = sorted(json.loads(raw)['data'], key=lambda row: row['index'])
    if [row['index'] for row in data] != list(range(len(texts))):
        raise ValueError('向量结果数量或顺序不正确。')
    vectors = [row['embedding'] for row in data]
    dimension = len(vectors[0]) if vectors else 0
    if not 8 <= dimension <= 8192 or any(len(v) != dimension or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in v)
            or sum(x*x for x in v) == 0 for v in vectors):
        raise ValueError('向量格式或维度不正确。')
    return vectors


def query_vectors(query, rows):
    if not configured():
        return {}, 'keyword', '未配置 Embedding 服务，本次使用关键词检索。'
    eligible = [(c, v) for c, v, _ in rows if c.vector and v.embedding_model == index_identity()]
    if not eligible:
        return {}, 'keyword', '资料尚未建立当前模型的语义索引，本次使用关键词检索。'
    try:
        vector = embed([query])[0]
        length = math.sqrt(sum(x*x for x in vector))
        scores = {c.id: sum(a*b for a, b in zip(c.vector, vector)) /
                  (length * math.sqrt(sum(x*x for x in c.vector)))
                  for c, _ in eligible if len(c.vector) == len(vector)}
        if not scores:
            raise ValueError('向量维度已变化，请重建索引。')
        return scores, 'hybrid', '关键词与语义向量混合检索。'
    except Exception:
        return {}, 'keyword', '语义服务暂不可用或维度变化，已回退关键词检索。'

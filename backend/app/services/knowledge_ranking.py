"""Bounded lexical ranking and transparent match evidence for published chunks."""
from collections import Counter
import math
import re

RANKING_REVISION = 'lexical-v2'
QUESTION_PHRASES = ('能不能', '为什么', '有什么', '有没有', '有多少', '告诉我', '请问', '如何', '怎么',
                    '怎样', '什么', '哪些', '是否', '能否', '可以', '需要', '应该', '目前', '现在', '附近', '推荐')
CONCEPTS = {
    '老人': '老年人 重点人员 护送', '残障': '行动不便 重点人员',
    '堵了': '堵塞 疏散通道 消防车道 封锁道路 重新规划',
    '改道': '封锁道路 重新规划 路线 调整', '充电棚': '电动自行车 充电',
    '烟雾': '烟气 躲火避烟', '关门': '房门 防火门 控烟',
    '煤气': '燃气 阀门', '机器人': '广播 到位 任务', '没到': '集合清点 失联',
}
OPERATIONS = ('改道', '封路', '核验', '任务', '预演', '批准', '语音', '得分', '计划', '接续', '广播')
LEXICAL_ALIASES = {'煤气': '燃气', '烟雾': '烟气', '电动车': '电动自行车', '残障': '行动不便'}


def terms(text):
    text = text.lower()
    tokens = re.findall(r'[a-z0-9_]+', text)
    for phrase in re.findall(r'[\u4e00-\u9fff]+', text):
        tokens.extend(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return Counter(tokens)


def canonical_query(query):
    for phrase, replacement in LEXICAL_ALIASES.items():
        query = query.replace(phrase, replacement)
    return query


def query_terms(query):
    normalized = canonical_query(query)
    for phrase in QUESTION_PHRASES:
        normalized = normalized.replace(phrase, ' ')
    return terms(normalized)


def matching_phrases(text, matched):
    """Join adjacent matching bigrams for people reading the evidence."""
    phrases = []
    for part in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9_]+', text.lower()):
        if re.fullmatch(r'[a-z0-9_]+', part):
            if part in matched:
                phrases.append(part)
            continue
        start = None
        for index in range(len(part)):
            if part[index:index + 2] in matched:
                if start is None:
                    start = index
            elif start is not None:
                phrases.append(part[start:index + 1])
                start = None
    return list(dict.fromkeys(phrases))


def rank_chunks(rows, query, vectors):
    original = query_terms(query)
    expansion = ' '.join(value for key, value in CONCEPTS.items() if key in query)
    expanded = terms(expansion)
    documents = [terms(document.title + ' ' + chunk.content) for chunk, _, document in rows]
    frequency = Counter(term for document in documents for term in document)
    average = sum(sum(document.values()) for document in documents) / max(1, len(documents))
    operational = any(word in query for word in OPERATIONS)
    ranked = []
    for (chunk, version, document), words in zip(rows, documents):
        direct = sorted(set(original) & words.keys())
        aliases = sorted((set(expanded) - set(original)) & words.keys())
        # One incidental bigram in a longer question is insufficient evidence.
        # A short exact term or a recognized concept alias remains searchable.
        enough = bool(direct) and (len(original) == 1 or len(direct) >= 2 or bool(aliases))
        enough = enough or (not direct and bool(aliases) and any(key in query and len(query.strip('？?。 ')) <= len(key) + 2 for key in CONCEPTS))
        score = 0.
        if enough:
            for term in set(original) | set(expanded):
                tf = words.get(term, 0)
                if not tf:
                    continue
                weight = 1. if term in original else .2
                idf = math.log(1 + (len(documents) - frequency[term] + .5) / (frequency[term] + .5))
                score += weight * idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(words.values()) / max(1, average)))
                if term in document.title:
                    score += weight * .6
            if operational and document.category == 'platform_guide':
                score *= 1.35
        vector_score = vectors.get(chunk.id, 0)
        if score > 0 or vector_score > .5:
            match = {'method': 'hybrid' if score > 0 and vector_score > .5 else 'semantic' if vector_score > .5 else 'keyword',
                     'terms': matching_phrases(canonical_query(query), set(direct))[:8],
                     'expanded_terms': matching_phrases(expansion, set(aliases))[:6], 'ranking_revision': RANKING_REVISION}
            ranked.append((score, vector_score, chunk, version, document, match))
    keyword_rank = {item[2].id: index + 1 for index, item in enumerate(sorted(ranked, key=lambda item: -item[0])) if item[0] > 0}
    vector_rank = {item[2].id: index + 1 for index, item in enumerate(sorted(ranked, key=lambda item: -item[1])) if item[1] > .5}
    ranked.sort(key=lambda item: -(1 / (60 + keyword_rank[item[2].id]) if item[2].id in keyword_rank else 0)
                - (1 / (60 + vector_rank[item[2].id]) if item[2].id in vector_rank else 0))
    return ranked

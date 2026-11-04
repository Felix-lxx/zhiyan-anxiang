"""Evaluate retrieval against the shipped corpus using a fresh in-memory store."""
import argparse
import json
import hashlib
from pathlib import Path
from statistics import median
from time import perf_counter

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models.domain  # noqa: F401
import app.models.knowledge  # noqa: F401
import app.models.operations  # noqa: F401
import app.models.agent  # noqa: F401
import app.models.auth  # noqa: F401
import app.models.account  # noqa: F401
import app.models.tasks  # noqa: F401
from app.core.database import Base
from app.services.knowledge import retrieve, seed_knowledge


def evaluate():
    cases_path = Path(__file__).parents[2] / 'evaluation' / 'knowledge_cases.json'
    cases = json.loads(cases_path.read_text(encoding='utf-8'))
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    results = []
    try:
        with Session(engine) as session:
            seed_knowledge(session)
            for case in cases:
                start = perf_counter()
                response = retrieve(session, 'retrieval-evaluation', case['query'], scenario=case['scenario'])
                elapsed = (perf_counter() - start) * 1000
                ids = [hit['document_id'] for hit in response['hits']]
                rank = next((index + 1 for index, identifier in enumerate(ids) if identifier in case['expected']), None)
                results.append({**case, 'retrieved': ids, 'rank': rank, 'latency_ms': round(elapsed, 3)})
        positive = [item for item in results if item['expected']]
        negative = [item for item in results if not item['expected']]
        catalog = Path(__file__).parents[1] / 'data' / 'fire_knowledge.json'
        return {'corpus': 'shipped builtins only', 'corpus_hash': hashlib.sha256(catalog.read_bytes()).hexdigest(),
                'case_hash': hashlib.sha256(cases_path.read_bytes()).hexdigest(),
                'semantic_service': False, 'case_count': len(cases),
                'positive_count': len(positive), 'negative_count': len(negative),
                'hit_at_3': round(sum(item['rank'] is not None and item['rank'] <= 3 for item in positive) / len(positive), 4),
                'mrr_at_5': round(sum(1 / item['rank'] if item['rank'] else 0 for item in positive) / len(positive), 4),
                'negative_empty_rate': round(sum(not item['retrieved'] for item in negative) / len(negative), 4),
                'median_local_ms': round(median(item['latency_ms'] for item in results), 3), 'cases': results}
    finally:
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'cases'}, ensure_ascii=False))

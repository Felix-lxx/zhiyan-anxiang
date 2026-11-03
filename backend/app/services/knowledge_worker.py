"""Short-lived file extraction process. No imported documents are executed."""
import json
import sys
from app.services.knowledge_ingestion import extract


if __name__ == '__main__':
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        data = json.loads(sys.stdin.read(4_200_000))
        pages, extraction = extract(data['filename'], data['data'])
        print(json.dumps({'pages': pages, 'extraction': extraction}, ensure_ascii=True))
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=True))
    except Exception:
        print(json.dumps({'error': '文档无法提取，请转换为 UTF-8 文本或重新导出。'}))

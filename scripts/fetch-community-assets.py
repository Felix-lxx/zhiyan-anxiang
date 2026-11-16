"""Fetch selected Poly Haven CC0 assets; verify sizes and hashes before publishing files."""
from hashlib import md5, sha256
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1] / 'frontend/public/assets'
TEXTURES = ('leafy_grass', 'brick_wall_001', 'floor_tiles_02', 'wood_floor')
MODELS = ('painted_wooden_bench', 'shrub_02')
HTTP = build_opener()
DIRECT = build_opener(ProxyHandler({}))


def read(url, limit=12_000_000):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'api.polyhaven.com', 'dl.polyhaven.org'}:
        raise ValueError('Unexpected resource host')
    for opener in (HTTP, DIRECT):
        try:
            with opener.open(Request(url, headers={'User-Agent': 'ZhiyanAssetPreparation/1.0'}), timeout=25) as response:
                data = response.read(limit + 1)
            break
        except (URLError, TimeoutError):
            if opener is DIRECT:
                raise
    if len(data) > limit:
        raise ValueError('Resource exceeds the selected web asset budget')
    return data


def save(folder, relative, spec):
    target = (folder / relative).resolve()
    if not target.is_relative_to(folder.resolve()):
        raise ValueError('Resource path escapes its asset directory')
    data = target.read_bytes() if target.exists() else read(spec['url'])
    if len(data) != spec['size'] or md5(data).hexdigest() != spec['md5']:
        raise ValueError(f'Official checksum mismatch: {relative}')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.download')
    temporary.write_bytes(data)
    temporary.replace(target)
    return {'file': target.relative_to(ROOT).as_posix(), 'url': spec['url'],
            'bytes': len(data), 'md5': spec['md5'], 'sha256': sha256(data).hexdigest()}


def main():
    records = []
    for asset in TEXTURES + MODELS:
        metadata = json.loads(read('https://api.polyhaven.com/files/' + asset))
        if asset in TEXTURES:
            for channel, suffix in (('Diffuse', 'diff'), ('nor_gl', 'nor_gl'), ('Rough', 'rough')):
                records.append(save(ROOT / 'surfaces', f'{asset}_{suffix}_1k.jpg', metadata[channel]['1k']['jpg']))
        else:
            spec = metadata['gltf']['1k']['gltf']
            folder = ROOT / 'community-real' / asset
            records.append(save(folder, asset + '.gltf', spec))
            for name, dependency in spec['include'].items():
                records.append(save(folder, name, dependency))
        print(f'{asset}: verified', flush=True)
    manifest = ROOT / 'community-real' / 'asset-manifest.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({'source': 'Poly Haven', 'license': 'CC0-1.0', 'files': records}, indent=2) + '\n', encoding='utf-8')
    print(f'{len(records)} verified files, {sum(r["bytes"] for r in records)} bytes')


if __name__ == '__main__':
    main()

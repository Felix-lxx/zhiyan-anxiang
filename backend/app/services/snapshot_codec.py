"""Lossless storage codec for disposable snapshots, including legacy JSON."""
import base64
import binascii
from copy import deepcopy
import json
import zlib

ENCODING = 'zlib-json-v1'
MAX_DECODED_BYTES = 64 * 1024 * 1024


def encode_snapshot(payload):
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except ValueError:
        return deepcopy(payload)
    if len(raw) > MAX_DECODED_BYTES:
        # Preserve compatibility for unusually large snapshots; never truncate.
        return deepcopy(payload)
    compressed = zlib.compress(raw, level=4)
    if len(compressed) * 4 // 3 + 100 >= len(raw):
        return deepcopy(payload)
    return {'_snapshot_encoding': ENCODING, 'decoded_bytes': len(raw),
            'data': base64.b64encode(compressed).decode('ascii')}


def decode_snapshot(payload):
    if not isinstance(payload, dict):
        return None
    if '_snapshot_encoding' not in payload:
        return deepcopy(payload)
    if payload.get('_snapshot_encoding') != ENCODING:
        return None
    expected = payload.get('decoded_bytes')
    if type(expected) is not int or not 0 < expected <= MAX_DECODED_BYTES:
        return None
    try:
        packed = base64.b64decode(payload['data'], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, expected + 1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (KeyError, TypeError, ValueError, binascii.Error, zlib.error):
        # The caller rebuilds from authoritative events rather than trusting a
        # corrupt cache or leaking a partially decoded state.
        return None

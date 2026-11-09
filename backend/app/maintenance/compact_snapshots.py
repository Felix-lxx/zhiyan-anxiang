"""Compact legacy snapshot JSON in bounded transactions; dry-run by default."""
import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.operations import DrillStateSnapshot
from app.services.snapshot_codec import encode_snapshot, decode_snapshot, ENCODING


def compact_snapshots(session, *, apply=False, batch_size=50, restore_json=False):
    cursor = ''
    result = {'scanned': 0, 'changed': 0, 'before_bytes': 0, 'after_bytes': 0, 'invalid': 0, 'applied': apply, 'restore_json': restore_json}
    while True:
        rows = session.scalars(select(DrillStateSnapshot).where(DrillStateSnapshot.id > cursor)
            .order_by(DrillStateSnapshot.id).limit(batch_size)).all()
        if not rows:
            break
        for row in rows:
            cursor = row.id
            result['scanned'] += 1
            original = row.payload
            if not isinstance(original, dict):
                result['invalid'] += 1
                continue
            encoded = original.get('_snapshot_encoding') == ENCODING
            if encoded != restore_json:
                continue
            decoded = decode_snapshot(original)
            if decoded is None:
                result['invalid'] += 1
                continue
            packed = decoded if restore_json else encode_snapshot(decoded)
            before = len(json.dumps(original).encode())
            after = len(json.dumps(packed).encode())
            result['before_bytes'] += before
            result['after_bytes'] += after if restore_json else min(before, after)
            if restore_json or after < before:
                result['changed'] += 1
                if apply:
                    row.payload = packed
        if apply:
            session.commit()
        else:
            session.expunge_all()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Write compacted derived snapshots; events and scores are unchanged.')
    parser.add_argument('--restore-json', action='store_true', help='Restore legacy JSON before rolling back to a pre-codec server.')
    parser.add_argument('--batch-size', type=int, choices=range(1, 201), default=50, metavar='1..200')
    options = parser.parse_args()
    with SessionLocal() as session:
        print(json.dumps(compact_snapshots(session, apply=options.apply, batch_size=options.batch_size, restore_json=options.restore_json)))

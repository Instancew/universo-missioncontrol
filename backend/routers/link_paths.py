"""Read-only local controller status. Browser state never controls routing."""
import json
import math
import os
from pathlib import Path
import time
from fastapi import APIRouter

router = APIRouter()


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite controller status value')
    return result


def reject_constant(value):
    raise ValueError('Invalid JSON constant in controller status')


@router.get('/api/link-paths')
async def link_paths():
    path = os.getenv('FAILOVER_STATUS_FILE', '/run/irc-failover/status.json')
    try:
        data = json.loads(Path(path).read_text(), parse_float=finite_float, parse_constant=reject_constant)
        if not isinstance(data, dict) or not isinstance(data.get('bands', {}), dict):
            raise ValueError('Invalid controller status object')
        if any(not isinstance(sample, dict) for sample in data.get('bands', {}).values()):
            raise ValueError('Invalid band status object')
        if isinstance(data['updated_at'], bool):
            raise ValueError('Invalid controller status timestamp')
        age = time.time() - finite_float(data['updated_at'])
        return {**data, 'stale': age < 0 or age > 5, 'age_seconds': age}
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return {'stale': True, 'bands': {}, 'reason': 'Local path controller status unavailable'}

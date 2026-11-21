import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
AVAILABLE = all(importlib.util.find_spec(name) for name in ('fastapi','pydantic','httpx'))


@unittest.skipUnless(AVAILABLE, 'Run with the approved backend virtual environment')
class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_radio_and_existing_routes_remain(self):
        import httpx
        from main import app
        from services.telemetry_service import telemetry_service
        # ASGITransport does not start lifespan, UDP sockets or live radio polling.
        transport = httpx.ASGITransport(app=app)
        with patch.object(telemetry_service, '_custom_data', {'radio_link': {'routers': {'mantbox': {'api_status':'online'}}}}):
            async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
                self.assertEqual((await client.get('/health')).status_code, 200)
                self.assertEqual((await client.get('/api/telemetry')).status_code, 200)
                self.assertEqual((await client.get('/api/radio-link')).json()['routers']['mantbox']['api_status'], 'online')
        self.assertIn('/ws/telemetry', [route.path for route in app.routes])

    async def test_path_status_fresh_stale_missing_and_malformed(self):
        from routers.link_paths import link_paths
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            with patch.dict(os.environ, {'FAILOVER_STATUS_FILE': str(path)}):
                self.assertTrue((await link_paths())['stale'])
                path.write_text(json.dumps({'updated_at':time.time(),'bands':{},'dry_run':True}))
                self.assertFalse((await link_paths())['stale'])
                path.write_text(json.dumps({'updated_at':time.time()-10,'bands':{}}))
                self.assertTrue((await link_paths())['stale'])
                path.write_text('not json')
                self.assertTrue((await link_paths())['stale'])

    async def test_radio_update_preserves_rover_snapshot_fields(self):
        from services.telemetry_service import TelemetryService
        from models.telemetry import TelemetrySnapshot
        store = TelemetryService()
        # Construct an existing snapshot for store semantics; schema validation is independent.
        snapshot = TelemetrySnapshot.model_construct(speed=1.25, heading=123, custom={'mission':'demo'})
        store.update_telemetry(snapshot)
        store.update_custom({'radio_link': {'routers': {}}})
        self.assertEqual(store.get_telemetry().speed, 1.25)
        self.assertEqual(store.get_telemetry().heading, 123)
        self.assertEqual(store.get_telemetry().custom['mission'], 'demo')
        store.update_telemetry(TelemetrySnapshot.model_construct(speed=2, heading=124, custom={}))
        self.assertIn('radio_link', store.get_telemetry().custom)


if __name__ == '__main__': unittest.main()

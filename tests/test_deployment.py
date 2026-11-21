"""Offline tests: no router, camera, network calls, or package installs."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


f = module('failover', 'deploy/network/failover.py')
p = module('publisher', 'deploy/jetson/publish.py')
GOOD = f.Sample(0, 10, True, True, '-55', '200Mbps', '200Mbps')
WEAK = f.Sample(60, 180, True, True, '-85', '6Mbps', '6Mbps')
DOWN = f.Sample(100, float('inf'), True, False)


class PolicyTests(unittest.TestCase):
    def drive(self, policy, start, stop, primary=GOOD, backup=GOOD, video=True):
        events = []
        for now in range(start, stop):
            target, reason = policy.decide(primary, backup, now, video)
            if target != policy.active:
                events.append((now, target, reason))
                policy.active = target
        return events

    def test_healthy(self):
        policy = f.Policy()
        self.assertEqual(self.drive(policy, 0, 50), [])

    def test_weak_but_associated(self):
        events = self.drive(f.Policy(), 0, 8, WEAK)
        self.assertEqual(events[0][:2], (5, '24'))
        self.assertIn('degradation', events[0][2])

    def test_hard_outage(self):
        events = self.drive(f.Policy(), 0, 6, DOWN)
        self.assertEqual(events[0][:2], (2, '24'))

    def test_unhealthy_backup_holds(self):
        self.assertEqual(self.drive(f.Policy(), 0, 40, DOWN, DOWN), [])

    def test_video_only_freeze_does_not_switch(self):
        policy = f.Policy()
        self.assertEqual(self.drive(policy, 0, 40, video=False), [])
        self.assertIn('video problem', policy.decide(GOOD, GOOD, 40, False)[1])

    def test_two_cycles_and_backup_stays_ready(self):
        policy = f.Policy()
        events = self.drive(policy, 0, 4, DOWN)
        events += self.drive(policy, 4, 26)
        self.assertEqual(policy.active, '5')
        self.assertIn('backup', policy.since)
        events += self.drive(policy, 26, 30, DOWN)
        events += self.drive(policy, 30, 52)
        self.assertEqual([(n, b) for n, b, _ in events], [(2, '24'), (24, '5'), (28, '24'), (50, '5')])

    def test_recovery_requires_continuous_health(self):
        policy = f.Policy('24')
        self.drive(policy, 0, 19)
        self.drive(policy, 19, 20, WEAK)
        self.assertEqual(self.drive(policy, 20, 40), [])
        self.assertEqual(self.drive(policy, 40, 41)[0][1], '5')

    def test_api_failure_is_unknown_not_rf_outage(self):
        self.assertEqual(self.drive(f.Policy(), 0, 40, f.Sample()), [])

    def test_measurement_gap_resets_hold(self):
        policy = f.Policy('24')
        self.drive(policy, 0, 10)
        self.assertEqual(self.drive(policy, 30, 50), [])

    def test_unhealthy_backup_emergency_return(self):
        policy = f.Policy('24')
        events = self.drive(policy, 0, 4, GOOD, DOWN)
        self.assertEqual(events[0][:2], (2, '5'))


class RouterTests(unittest.TestCase):
    def config(self):
        return json.loads((ROOT / 'deploy/network/base.json.example').read_text())

    def test_examples_safe_and_separate(self):
        for role in ('base', 'rover'):
            config = json.loads((ROOT / f'deploy/network/{role}.json.example').read_text())
            f.validate(config)
            self.assertFalse(config['auto_apply'])
            self.assertFalse(config['hardware_acceptance_passed'])
            config['auto_apply'] = True
            with self.assertRaises(ValueError): f.validate(config)

    def test_apply_guards_require_real_booleans_and_default_disabled(self):
        for flag in ('auto_apply', 'hardware_acceptance_passed'):
            for value in ('false', 'true', 0, 1, None):
                config = self.config()
                config[flag] = value
                with self.subTest(flag=flag, value=value), self.assertRaises(ValueError):
                    f.validate(config)
        config = self.config()
        del config['auto_apply']
        del config['hardware_acceptance_passed']
        f.validate(config)
        self.assertFalse(config.get('auto_apply', False))

    def test_ping_parsing_loss_and_rtt(self):
        rows = [{'sent':'5','received':'4','host':'10.44.50.2','avg-rtt':'10ms453us','time':'11ms'}]
        sample = f.parse_ping(rows, '10.44.50.2', 5)
        self.assertEqual(sample.loss, 20)
        self.assertAlmostEqual(sample.latency_ms, 10.453)
        self.assertFalse(f.parse_ping(rows, '10.44.24.2', 5).valid)
        self.assertFalse(f.parse_ping(rows, '10.44.50.2', 10).valid)
        self.assertTrue(f.parse_ping([{'sent':'5','received':'0'}], '10.44.50.2', 5).valid)

    def test_probes_pin_both_request_and_reply_addresses(self):
        router = object.__new__(f.Router)
        router.config = self.config()
        calls = []
        router.request = lambda path, body: calls.append((path, body)) or [{'sent':'5','received':'0'}]
        for band in ('5','24'): router.probe(band)
        self.assertEqual(len(calls), 2)
        for band, (_, body) in zip(('5','24'), calls):
            config = router.config['bands'][band]
            for field, key in [('src-address','source'),('address','peer'),('interface','interface')]:
                self.assertEqual(body[field], config[key])
            self.assertNotIn('routing-table', body)
            self.assertNotIn('vrf', body)  # A policy table is not a VRF.
        # Live packet captures remain required; mocks cannot prove router forwarding.

    def fake_router(self):
        router = object.__new__(f.Router)
        router.config = self.config()
        rows = [{'.id':'*'+band, 'distance':str(distance), 'comment':b['route_comment'],
                 'dst-address':router.config['remote_lan'], 'gateway':b['peer']+'%'+b['interface']}
                for (band,b),distance in zip(router.config['bands'].items(),(1,20))]
        def request(path, body=None, method=None):
            if method == 'PATCH':
                next(row for row in rows if row['.id'] == path.split('/')[-1]).update(body)
                return {}
            preferred = min(rows, key=lambda row: int(row['distance']))['.id']
            return [{**row, 'active': 'true' if row['.id'] == preferred else 'false'} for row in rows]
        router.request = request
        return router, rows

    def test_route_switch_twice_without_disabling_radios(self):
        router, rows = self.fake_router()
        for target in ('24','5','24','5'):
            router.switch(target)
            self.assertEqual(router.active(), target)
            self.assertTrue(all(row.get('disabled', 'false') == 'false' for row in rows))

    def test_failed_write_rolls_back(self):
        router, rows = self.fake_router()
        original = router.request
        failed = False
        def request(path, body=None, method=None):
            nonlocal failed
            if method == 'PATCH' and body == {'distance':'20'} and not failed:
                failed = True
                raise OSError('mock disconnect')
            return original(path, body, method)
        router.request = request
        with self.assertRaises(OSError): router.switch('24')
        self.assertEqual([row['distance'] for row in rows], ['1','20'])

    def test_inactive_target_readback_rolls_back(self):
        router, rows = self.fake_router()
        original = router.request
        def request(path, body=None, method=None):
            response = original(path, body, method)
            if method is None:
                for row in response:
                    row['active'] = 'true' if row['.id'] == '*5' else 'false'
            return response
        router.request = request
        with self.assertRaisesRegex(RuntimeError, 'Route readback failed'):
            router.switch('24')
        self.assertEqual([row['distance'] for row in rows], ['1','20'])

    def test_preference_is_not_forwarding_state(self):
        router, rows = self.fake_router()
        router.routes = lambda: {'5': {**rows[0], 'active':'false'},
                                 '24': {**rows[1], 'active':'true'}}
        self.assertEqual(router.preferred(), '5')
        self.assertEqual(router.active(), '24')
        router.routes = lambda: {'5': rows[0], '24': rows[1]}
        self.assertIsNone(router.active())  # Absent active flags are unknown.

    def test_unowned_competing_route_blocks_writes(self):
        router, rows = self.fake_router()
        original = router.request
        calls = []
        def request(path, body=None, method=None):
            calls.append(method)
            response = original(path, body, method)
            if method is None:
                response.append({**rows[0], '.id':'*99', 'comment':'unrelated', 'distance':'1'})
            return response
        router.request = request
        with self.assertRaisesRegex(RuntimeError, 'Unowned route'):
            router.switch('24')
        self.assertNotIn('PATCH', calls)


class PublisherTests(unittest.TestCase):
    def test_software_low_latency_and_restart_watchdog(self):
        args = p.pipeline({'ENCODER':'software'}, lambda _: True)
        for value in ('x264enc','bframes=0','tune=zerolatency','bitrate=700','key-int-max=15','watchdog','timeout=5000','max-size-buffers=2'):
            self.assertIn(value, args)

    def test_hardware_and_orin_nano_fallback(self):
        self.assertIn('nvv4l2h264enc', p.pipeline({}, lambda _: True))
        self.assertIn('x264enc', p.pipeline({'JETSON_MODEL':'NVIDIA Jetson Orin Nano'}, lambda _: True))

    def test_missing_plugins_fail_visibly(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing GStreamer'):
            p.pipeline({'ENCODER':'software'}, lambda plugin: plugin != 'rtspclientsink')
        with self.assertRaisesRegex(RuntimeError, 'Hardware encoder'):
            p.pipeline({'ENCODER':'hardware'}, lambda _: False)

    def test_generated_source_and_bounds(self):
        args = p.pipeline({'SOURCE':'test','ENCODER':'software'}, lambda _: True)
        self.assertIn('videotestsrc', args)
        self.assertNotIn('v4l2src', args)
        with self.assertRaises(ValueError): p.pipeline({'FPS':'0'}, lambda _: True)


if __name__ == '__main__': unittest.main()

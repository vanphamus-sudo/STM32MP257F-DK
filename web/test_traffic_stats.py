import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import mqtt_metrics as metrics
from traffic_stats import Accounting, atomic


def sample(tx, rx, device='wwan0', ifindex=7):
    return dict(tx=tx, rx=rx, device=device, ifindex=ifindex)


class TrafficTests(unittest.TestCase):
    def test_initial_boot_counts_and_independent_roles_not_summed(self):
        stats = Accounting()
        stats.sample(dict(wan=sample(100, 200), sim1=sample(100, 200)), 'boot1', 10, 100)
        self.assertEqual(stats.data['roles']['wan']['total_rx_bytes'], 200)
        self.assertEqual(stats.data['roles']['sim1']['total_rx_bytes'], 200)
        stats.sample(dict(wan=sample(150, 400), sim1=sample(150, 400)), 'boot1', 15, 105)
        self.assertEqual(stats.data['roles']['wan']['total_rx_bytes'], 400)
        self.assertEqual(stats.data['roles']['wan']['rx_bytes_per_second'], 40)
        self.assertNotIn('last', stats.public()['roles']['wan'])

    def test_persist_restart_and_reboot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            stats = Accounting()
            stats.sample(dict(wan=sample(100, 200)), 'boot1', 10, 100)
            atomic(path, stats.data)
            restored = Accounting(json.loads(path.read_text()))
            restored.sample(dict(wan=sample(150, 300)), 'boot1', 20, 110)
            self.assertEqual(restored.data['roles']['wan']['total_rx_bytes'], 300)
            restored.sample(dict(wan=sample(20, 30)), 'boot2', 5, 120)
            self.assertEqual(restored.data['roles']['wan']['total_rx_bytes'], 330)

    def test_reset_disconnect_and_device_reassignment(self):
        stats = Accounting()
        stats.sample(dict(wan=sample(100, 200)), 'boot1', 10, 100)
        stats.sample({}, 'boot1', 15, 105)
        self.assertFalse(stats.data['roles']['wan']['available'])
        stats.sample(dict(wan=sample(10, 20)), 'boot1', 20, 110)
        self.assertEqual(stats.data['roles']['wan']['total_rx_bytes'], 220)
        stats.sample(dict(wan=sample(5000, 6000, 'eth0', 2)), 'boot1', 25, 115)
        self.assertEqual(stats.data['roles']['wan']['total_rx_bytes'], 220)
        stats.sample(dict(wan=sample(5100, 6100, 'eth0', 2)), 'boot1', 30, 120)
        self.assertEqual(stats.data['roles']['wan']['total_rx_bytes'], 320)


class MetricTests(unittest.TestCase):
    def test_real_quectel_lte_and_csq(self):
        backend = Mock()
        backend.send_at.side_effect = [dict(ok=True, response='+CSQ: 27,99'),
            dict(ok=True, response='+QENG: "servingcell","NOCONN","LTE","FDD",505,01,8322A01,417,1275,3,4,4,309F,-88,-8,-60,18,-,-')]
        data = metrics.radio(backend)
        self.assertEqual(data, dict(csq='27', nettype='4G', ci=str(int('8322A01', 16)), lac=str(int('309F', 16)), netband='band3', rsrp='-88', rsrq='-8', rssi='-60', sinr='18'))

    def test_unknown_signal_does_not_become_a_number(self):
        backend = Mock()
        backend.send_at.side_effect = [dict(ok=True, response='+CSQ: 99,99'), dict(ok=False)]
        self.assertEqual(metrics.radio(backend), {})

    def test_latency_loss_and_jitter_from_actual_rtts(self):
        with patch.object(metrics.subprocess, 'run', return_value=Mock(stdout='time=10.0 ms\ntime=20.0 ms\ntime=15.0 ms\n0% packet loss')):
            self.assertEqual(metrics.quality('wwan0'), dict(delay='15.000ms', loss_rate='0%', jitter='7.500ms'))
        with patch.object(metrics.subprocess, 'run', return_value=Mock(stdout='100% packet loss')):
            self.assertEqual(metrics.quality('wwan0'), dict(loss_rate='100%'))

    def test_gps_never_invents_a_fix(self):
        self.assertEqual(metrics.gps({'gps': {'latitude': '--', 'longitude': '--'}}), {})
        self.assertEqual(metrics.gps({'gps': {'latitude': 'nan', 'longitude': '1'}}), {})
        self.assertEqual(metrics.gps({'gps': {'latitude': '-34', 'longitude': '151', 'utc': '12:00'}}), dict(fix='12:00', lat=-34.0, lng=151.0))


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import Mock
import cellular_settings as cellular

VALID = dict(apn='telstra.internet', username='', password='', clear_password=False,
             auth='none', iptype='ipv4v6')


class CellularTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.values.return_value = {'wan': {'apn': 'old', 'password': 'private-secret'}}

    def test_read_never_returns_password(self):
        value = cellular.status(self.backend)
        self.assertTrue(value['password_saved'])
        self.assertNotIn('password', value)
        self.assertNotIn('private-secret', str(value))

    def test_blank_password_is_preserved_and_only_wan_connection_changes(self):
        cellular.save(VALID, self.backend, Mock())
        edits = self.backend.transaction.call_args.args[1]
        self.assertFalse(any(key.endswith('.password') for _, key, _ in edits))
        self.assertTrue(all(key.startswith('network.wan.') for _, key, _ in edits))
        self.assertIn(('set', 'network.wan.iptype', 'ipv4v6'), edits)
        self.backend.transaction.call_args.args[2]()
        self.assertEqual(self.backend.run.call_args_list[0].args, ('ifdown', 'wan'))
        self.assertEqual(self.backend.run.call_args_list[1].args, ('ifup', 'wan'))

    def test_password_clear_and_replace(self):
        cellular.save(VALID | dict(clear_password=True), self.backend, Mock())
        self.assertIn(('delete', 'network.wan.password', None), self.backend.transaction.call_args.args[1])
        secret = 'a;$(unchanged)'
        cellular.save(VALID | dict(password=secret), self.backend, Mock())
        self.assertIn(('set', 'network.wan.password', secret), self.backend.transaction.call_args.args[1])

    def test_invalid_input_does_not_change_network(self):
        for changes in (dict(apn='x\nreboot'), dict(apn=''), dict(username='x\ny'),
                        dict(password='x\r'), dict(username='a,apn=other'), dict(password='"quoted"'), dict(iptype='any'), dict(auth='auto'),
                        dict(clear_password='yes'), dict(clear_password=True, password='secret')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                cellular.save(VALID | changes, self.backend, Mock())
        self.backend.transaction.assert_not_called()

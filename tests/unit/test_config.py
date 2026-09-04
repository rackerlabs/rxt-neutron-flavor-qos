import unittest

from neutron_flavor_qos import config


class ConfigTestCase(unittest.TestCase):

    def test_list_opts_exposes_runtime_and_keystoneauth_options(self):
        group, opts = config.list_opts()[0]
        opt_names = [opt.name for opt in opts]

        self.assertEqual("flavor_qos", group)
        self.assertIn("managed_device_owner_prefixes", opt_names)
        self.assertIn("auth_type", opt_names)
        self.assertIn("region-name", opt_names)
        self.assertIn("valid-interfaces", opt_names)

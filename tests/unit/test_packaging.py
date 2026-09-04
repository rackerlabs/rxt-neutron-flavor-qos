import configparser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PackagingTestCase(unittest.TestCase):

    def _setup_cfg(self):
        parser = configparser.ConfigParser()
        parser.read(ROOT / "setup.cfg")
        return parser

    def test_neutron_service_plugin_entry_point_is_registered(self):
        entry_points = self._setup_cfg()["entry_points"]

        self.assertIn("neutron.service_plugins", entry_points)
        self.assertIn(
            "flavor_qos = neutron_flavor_qos.plugin:FlavorQosServicePlugin",
            entry_points["neutron.service_plugins"])

    def test_oslo_config_opts_entry_point_is_registered(self):
        entry_points = self._setup_cfg()["entry_points"]

        self.assertIn("oslo.config.opts", entry_points)
        self.assertIn(
            "neutron_flavor_qos = neutron_flavor_qos.config:list_opts",
            entry_points["oslo.config.opts"])

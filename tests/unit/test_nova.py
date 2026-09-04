from unittest import mock
import unittest

from neutron_flavor_qos import config
from neutron_flavor_qos import nova


class NovaFlavorClientTestCase(unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.client = nova.NovaFlavorClient(mock.Mock())
        self.adapter = mock.Mock()
        self.client._adapter = self.adapter

    def _response(self, payload):
        response = mock.Mock()
        response.json.return_value = payload
        return response

    def test_get_server_flavor_extra_specs_reads_server_then_flavor(self):
        self.adapter.get.side_effect = [
            self._response({
                "server": {
                    "flavor": {
                        "id": "m1.large",
                    },
                },
            }),
            self._response({
                "extra_specs": {
                    "flavor_qos_policy_id": (
                        "75c29b54-721d-4387-8f66-0057c8c5ed28"),
                },
            }),
        ]

        extra_specs = self.client.get_server_flavor_extra_specs(
            "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2")

        self.assertEqual(
            {
                "flavor_qos_policy_id": (
                    "75c29b54-721d-4387-8f66-0057c8c5ed28"),
            },
            extra_specs)
        self.adapter.get.assert_has_calls([
            mock.call("/servers/4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"),
            mock.call("/flavors/m1.large/os-extra_specs"),
        ])

    def test_get_server_flavor_extra_specs_accepts_string_flavor(self):
        self.adapter.get.side_effect = [
            self._response({"server": {"flavor": "m1.large"}}),
            self._response({"extra_specs": {"other": "value"}}),
        ]

        extra_specs = self.client.get_server_flavor_extra_specs("server-id")

        self.assertEqual({"other": "value"}, extra_specs)
        self.adapter.get.assert_has_calls([
            mock.call("/servers/server-id"),
            mock.call("/flavors/m1.large/os-extra_specs"),
        ])

    def test_get_server_flavor_extra_specs_quotes_api_path_ids(self):
        self.adapter.get.side_effect = [
            self._response({"server": {"flavor": {"id": "m1/large"}}}),
            self._response({"extra_specs": {"other": "value"}}),
        ]

        extra_specs = self.client.get_server_flavor_extra_specs(
            "server/with/slash")

        self.assertEqual({"other": "value"}, extra_specs)
        self.adapter.get.assert_has_calls([
            mock.call("/servers/server%2Fwith%2Fslash"),
            mock.call("/flavors/m1%2Flarge/os-extra_specs"),
        ])

    def test_get_server_flavor_extra_specs_returns_empty_without_flavor_id(
            self):
        self.adapter.get.return_value = self._response({
            "server": {
                "flavor": {},
            },
        })

        with mock.patch("neutron_flavor_qos.nova.LOG") as log:
            extra_specs = self.client.get_server_flavor_extra_specs(
                "server-id")

        self.assertEqual({}, extra_specs)
        self.adapter.get.assert_called_once_with("/servers/server-id")
        log.warning.assert_called_once()

    def test_get_server_flavor_extra_specs_returns_empty_for_bad_server_shape(
            self):
        self.adapter.get.return_value = self._response({
            "server": ["not", "a", "dict"],
        })

        with mock.patch("neutron_flavor_qos.nova.LOG") as log:
            extra_specs = self.client.get_server_flavor_extra_specs(
                "server-id")

        self.assertEqual({}, extra_specs)
        self.adapter.get.assert_called_once_with("/servers/server-id")
        log.warning.assert_called_once()

    def test_get_server_flavor_extra_specs_returns_empty_for_bad_json_body(
            self):
        self.adapter.get.return_value = self._response(["not", "a", "dict"])

        with mock.patch("neutron_flavor_qos.nova.LOG") as log:
            extra_specs = self.client.get_server_flavor_extra_specs(
                "server-id")

        self.assertEqual({}, extra_specs)
        self.adapter.get.assert_called_once_with("/servers/server-id")
        log.warning.assert_called_once()

    def test_get_server_flavor_extra_specs_reads_fresh_flavor_extra_specs(
            self):
        self.adapter.get.side_effect = [
            self._response({"server": {"flavor": {"id": "m1.large"}}}),
            self._response({
                "extra_specs": {
                    "flavor_qos_policy_id": (
                        "75c29b54-721d-4387-8f66-0057c8c5ed28"),
                },
            }),
            self._response({"server": {"flavor": {"id": "m1.large"}}}),
            self._response({"extra_specs": {"other": "updated"}}),
        ]

        first = self.client.get_server_flavor_extra_specs("server-a")
        second = self.client.get_server_flavor_extra_specs("server-b")

        self.assertEqual(
            {
                "flavor_qos_policy_id": (
                    "75c29b54-721d-4387-8f66-0057c8c5ed28"),
            },
            first)
        self.assertEqual({"other": "updated"}, second)
        self.adapter.get.assert_has_calls([
            mock.call("/servers/server-a"),
            mock.call("/flavors/m1.large/os-extra_specs"),
            mock.call("/servers/server-b"),
            mock.call("/flavors/m1.large/os-extra_specs"),
        ])
        self.assertEqual(4, self.adapter.get.call_count)

    def test_get_flavor_extra_specs_returns_empty_for_non_dict_payload(self):
        self.adapter.get.return_value = self._response({
            "extra_specs": ["not", "a", "dict"],
        })

        extra_specs = self.client._get_flavor_extra_specs("m1.large")

        self.assertEqual({}, extra_specs)

    def test_get_flavor_extra_specs_returns_empty_for_bad_json_body(self):
        self.adapter.get.return_value = self._response(["not", "a", "dict"])

        extra_specs = self.client._get_flavor_extra_specs("m1.large")

        self.assertEqual({}, extra_specs)

    @mock.patch("neutron_flavor_qos.nova.ks_loading")
    @mock.patch("neutron_flavor_qos.nova.config.register_opts")
    def test_get_adapter_uses_flavor_qos_keystoneauth_group(
            self, register_opts, ks_loading):
        client = nova.NovaFlavorClient("conf")
        ks_loading.load_auth_from_conf_options.return_value = "auth"
        ks_loading.load_session_from_conf_options.return_value = "session"
        ks_loading.load_adapter_from_conf_options.return_value = "adapter"

        adapter = client._get_adapter()

        self.assertEqual("adapter", adapter)
        register_opts.assert_called_once_with("conf")
        ks_loading.load_auth_from_conf_options.assert_called_once_with(
            "conf", config.GROUP)
        ks_loading.load_session_from_conf_options.assert_called_once_with(
            "conf", config.GROUP, auth="auth")
        ks_loading.load_adapter_from_conf_options.assert_called_once_with(
            "conf", config.GROUP, session="session")

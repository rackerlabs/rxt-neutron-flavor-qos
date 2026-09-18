from unittest import mock
import unittest

from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.exceptions import qos as qos_exc
from neutron_lib.services import base as service_base

from neutron_flavor_qos import exceptions
from neutron_flavor_qos import plugin


class FlavorQosServicePluginTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.plugin = plugin.FlavorQosServicePlugin.__new__(
            plugin.FlavorQosServicePlugin)

    def _port(self, **overrides):
        port = {
            "id": "port-id",
            "project_id": "project-id",
            "network_id": "network-id",
            "device_id": "",
            "device_owner": "",
            "binding:host_id": None,
            "binding:vnic_type": "normal",
            "qos_policy_id": None,
        }
        port.update(overrides)
        return port

    def _payload(self, original_port, updated_port, context=None):
        return mock.Mock(
            states=[original_port],
            latest_state=updated_port,
            context=context,
        )

    def test_service_plugin_contract_matches_neutron_wiring(self):
        self.assertTrue(
            issubclass(plugin.FlavorQosServicePlugin,
                       service_base.ServicePluginBase))
        self.assertEqual(
            [plugin_constants.QOS],
            plugin.FlavorQosServicePlugin.required_service_plugins)
        self.assertEqual(
            [], plugin.FlavorQosServicePlugin.supported_extension_aliases)
        self.assertEqual("", plugin.FlavorQosServicePlugin.path_prefix)
        self.assertTrue(self.plugin.filter_validation_support)

    def test_service_plugin_type_matches_entry_point_alias(self):
        self.assertEqual(
            "flavor_qos", plugin.FlavorQosServicePlugin.get_plugin_type())

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_applies_flavor_metadata_policy(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")
        ctxt = mock.Mock()
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            return_value="policy-id")
        self.plugin._flavor_qos_policy_exists = mock.Mock(return_value=True)
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated, ctxt))

        self.plugin._resolve_flavor_qos_policy_id.assert_called_once_with(
            updated)
        self.plugin._flavor_qos_policy_exists.assert_called_once_with(
            ctxt, updated, "policy-id")
        self.plugin._apply_flavor_qos_policy.assert_called_once_with(
            ctxt, updated, "policy-id")

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_noops_when_flavor_metadata_missing(
            self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            return_value=None)
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated))

        self.plugin._apply_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_noops_when_qos_policy_missing(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            return_value="policy-id")
        self.plugin._flavor_qos_policy_exists = mock.Mock(return_value=False)
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated))

        self.plugin._apply_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_ignores_non_binding_update(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(device_owner="")
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated))

        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()
        self.plugin._apply_flavor_qos_policy.assert_not_called()

    def test_after_port_update_noops_without_payload(self):
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()

        self.plugin._after_port_update(None, None, None, None)

        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()

    def test_after_port_update_noops_without_original_state(self):
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()
        payload = mock.Mock(states=[], latest_state=self._port())

        self.plugin._after_port_update(None, None, None, payload)

        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()

    def test_after_port_update_noops_with_malformed_original_state(self):
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()
        payload = mock.Mock(states=[None], latest_state=self._port())

        self.plugin._after_port_update(None, None, None, payload)

        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()

    def test_after_port_update_noops_with_malformed_latest_state(self):
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()
        payload = mock.Mock(states=[self._port()], latest_state=None)

        self.plugin._after_port_update(None, None, None, payload)

        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_logs_enforcement_error(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            side_effect=RuntimeError("nova is unavailable"))
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._after_port_update(
                None, None, None, self._payload(original, updated))

        self.plugin._apply_flavor_qos_policy.assert_not_called()
        log.exception.assert_called_once()

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_matches_compute_owner(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")

        self.assertTrue(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_matches_host_binding_with_device_id(
            self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": None})
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             **{"binding:host_id": "compute-01"})

        self.assertTrue(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_matches_compute_owner_change(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id)
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova")

        self.assertTrue(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_already_bound_compute_port_update_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": "compute-01"})
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             **{"binding:host_id": "compute-01"})

        self.assertFalse(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_unbound_user_port_update_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(device_owner="")

        self.assertFalse(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_non_server_device_id_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(device_id="not-a-server-uuid",
                             device_owner="compute:nova")

        self.assertFalse(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_empty_managed_device_owner_prefix_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = [""]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="network:router_interface")

        self.assertFalse(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_internal_qos_update_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova")
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             qos_policy_id="policy-id")

        self.assertFalse(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_clears_policy_on_managed_port(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        port = self._port(device_id=server_id,
                          device_owner="compute:nova",
                          **{"binding:host_id": "compute-01",
                             "qos_policy_id": "policy-id"})
        ctxt = mock.Mock()
        payload = mock.Mock(states=[port], context=ctxt)
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_called_once_with(
            ctxt, port)

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_port_without_policy(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        port = self._port(device_id=server_id, device_owner="compute:nova")
        payload = mock.Mock(states=[port], context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_unmanaged_owner(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        port = self._port(device_id="router-id",
                          device_owner="network:router_interface",
                          **{"qos_policy_id": "policy-id"})
        payload = mock.Mock(states=[port], context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_unbound_device_id(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        port = self._port(**{"qos_policy_id": "policy-id"})
        payload = mock.Mock(states=[port], context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    def test_before_port_delete_noops_without_payload(self):
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, None)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    def test_before_port_delete_noops_with_malformed_state(self):
        payload = mock.Mock(states=[None], context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_logs_cleanup_error(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        port = self._port(device_id=server_id,
                          device_owner="compute:nova",
                          **{"qos_policy_id": "policy-id"})
        payload = mock.Mock(states=[port], context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock(
            side_effect=RuntimeError("db is unavailable"))

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._before_port_delete(None, None, None, payload)

        log.exception.assert_called_once()

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_matches_host_change_migration(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": "compute-01"})
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             **{"binding:host_id": "compute-02"})

        self.assertTrue(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_ignores_repeated_identical_bind(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        port = self._port(device_id=server_id,
                          device_owner="compute:nova",
                          **{"binding:host_id": "compute-01",
                             "binding:vnic_type": "normal"})

        self.assertFalse(
            self.plugin._is_binding_transition(port, port))

    def test_resolve_flavor_qos_policy_id_from_extra_spec(self):
        self.plugin._nova_client = mock.Mock()
        self.plugin._nova_client.get_server_flavor_extra_specs.return_value = {
            "flavor_qos_policy_id": (
                "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"),
            "other": "value",
        }

        policy_id = self.plugin._resolve_flavor_qos_policy_id(
            self._port(device_id="server-id"))

        self.assertEqual("4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2", policy_id)
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.assert_called_once_with("server-id")

    def test_resolve_flavor_qos_policy_id_strips_extra_spec_value(self):
        self.plugin._nova_client = mock.Mock()
        self.plugin._nova_client.get_server_flavor_extra_specs.return_value = {
            "flavor_qos_policy_id": (
                " 4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2 "),
        }

        policy_id = self.plugin._resolve_flavor_qos_policy_id(
            self._port(device_id="server-id"))

        self.assertEqual("4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2", policy_id)

    def test_resolve_flavor_qos_policy_id_noops_for_blank_extra_spec(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {"flavor_qos_policy_id": "   "}

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.assertIsNone(self.plugin._resolve_flavor_qos_policy_id(
                self._port(device_id="server-id")))

        log.warning.assert_called_once()

    def test_resolve_flavor_qos_policy_id_noops_without_extra_spec(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {}

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.assertIsNone(self.plugin._resolve_flavor_qos_policy_id(
                self._port(device_id="server-id")))

        log.warning.assert_called_once()

    def test_resolve_flavor_qos_policy_id_ignores_qos_policy_id(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {
            "qos_policy_id": "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
        }

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.assertIsNone(self.plugin._resolve_flavor_qos_policy_id(
                self._port(device_id="server-id")))

        log.warning.assert_called_once()

    def test_resolve_flavor_qos_policy_id_requires_uuid_extra_spec_value(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {"flavor_qos_policy_id": "not-a-uuid"}

        self.assertRaises(
            exceptions.FlavorQosMetadataInvalid,
            self.plugin._resolve_flavor_qos_policy_id,
            self._port(device_id="server-id"),
        )

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_warns_for_invalid_extra_spec_value(
            self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(
            device_id="4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2",
            device_owner="compute:nova")
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            side_effect=exceptions.FlavorQosMetadataInvalid(
                key="flavor_qos_policy_id", value="not-a-uuid"))
        self.plugin._flavor_qos_policy_exists = mock.Mock()
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._after_port_update(
                None, None, None, self._payload(original, updated))

        log.warning.assert_called_once()
        self.plugin._flavor_qos_policy_exists.assert_not_called()
        self.plugin._apply_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_clears_policy_on_unbind(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": "compute-01",
                                 "qos_policy_id": "policy-id"})
        updated = self._port(**{"qos_policy_id": "policy-id"})
        ctxt = mock.Mock()
        self.plugin._clear_flavor_qos_policy = mock.Mock()
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated, ctxt))

        self.plugin._clear_flavor_qos_policy.assert_called_once_with(
            ctxt, updated)
        self.plugin._resolve_flavor_qos_policy_id.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_noops_when_unbind_clears_no_policy(self,
                                                                 conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova")
        updated = self._port()
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated))

        # _clear_flavor_qos_policy still runs the no-policy noop internally
        self.plugin._clear_flavor_qos_policy.assert_called_once_with(
            None, updated)

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_logs_unbind_clear_error(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova")
        updated = self._port()
        self.plugin._clear_flavor_qos_policy = mock.Mock(
            side_effect=RuntimeError("db is unavailable"))

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._after_port_update(
                None, None, None, self._payload(original, updated))

        log.exception.assert_called_once()

    @mock.patch("oslo_config.cfg.CONF")
    def test_unbinding_transition_matches_managed_to_unmanaged(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": "compute-01"})
        updated = self._port(**{"binding:host_id": None})

        self.assertTrue(
            self.plugin._is_unbinding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_unbinding_transition_ignores_still_bound_update(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"binding:host_id": "compute-01"})
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             **{"binding:host_id": "compute-02"})

        self.assertFalse(
            self.plugin._is_unbinding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_unbinding_transition_ignores_user_port_update(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port()
        updated = self._port(device_owner="")

        self.assertFalse(
            self.plugin._is_unbinding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_unbinding_transition_ignores_non_managed_owner(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        original = self._port(device_id="router-id",
                              device_owner="network:router_interface",
                              **{"binding:host_id": "compute-01"})
        updated = self._port(device_owner="")

        self.assertFalse(
            self.plugin._is_unbinding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_internal_unbind_qos_update_is_ignored(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id,
                              device_owner="compute:nova",
                              **{"qos_policy_id": "policy-id"})
        updated = self._port(device_id=server_id,
                             device_owner="compute:nova",
                             **{"qos_policy_id": None})

        self.assertFalse(
            self.plugin._is_unbinding_transition(original, updated))

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_clear_flavor_qos_policy_updates_port(self, get_plugin):
        core_plugin = mock.Mock()
        get_plugin.return_value = core_plugin
        ctxt = mock.Mock()
        ctxt.elevated.return_value = "admin-context"

        self.plugin._clear_flavor_qos_policy(
            ctxt, self._port(qos_policy_id="policy-id"))

        core_plugin.update_port.assert_called_once_with(
            "admin-context",
            "port-id",
            {"port": {"qos_policy_id": None}},
        )

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_clear_flavor_qos_policy_noops_when_policy_already_none(
            self, get_plugin):
        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._clear_flavor_qos_policy(mock.Mock(), self._port())

        get_plugin.assert_not_called()
        log.debug.assert_called_once()

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_clear_flavor_qos_policy_noops_when_core_plugin_missing(
            self, get_plugin):
        get_plugin.return_value = None

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._clear_flavor_qos_policy(
                mock.Mock(), self._port(qos_policy_id="policy-id"))

        log.warning.assert_called_once()

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_flavor_qos_policy_exists_uses_qos_service_plugin(
            self, get_plugin):
        qos_plugin = mock.Mock()
        get_plugin.return_value = qos_plugin
        ctxt = mock.Mock()
        ctxt.elevated.return_value = "admin-context"

        exists = self.plugin._flavor_qos_policy_exists(
            ctxt, self._port(device_id="server-id"), "policy-id")

        self.assertTrue(exists)
        get_plugin.assert_called_once_with(plugin_constants.QOS)
        qos_plugin.get_policy.assert_called_once_with(
            "admin-context", "policy-id")

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_flavor_qos_policy_exists_noops_when_policy_is_missing(
            self, get_plugin):
        qos_plugin = mock.Mock()
        qos_plugin.get_policy.side_effect = qos_exc.QosPolicyNotFound(
            policy_id="policy-id")
        get_plugin.return_value = qos_plugin
        ctxt = mock.Mock()
        ctxt.elevated.return_value = "admin-context"

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            exists = self.plugin._flavor_qos_policy_exists(
                ctxt, self._port(device_id="server-id"), "policy-id")

        self.assertFalse(exists)
        log.warning.assert_called_once()

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_flavor_qos_policy_exists_noops_when_qos_plugin_missing(
            self, get_plugin):
        get_plugin.return_value = None

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            exists = self.plugin._flavor_qos_policy_exists(
                mock.Mock(), self._port(device_id="server-id"), "policy-id")

        self.assertFalse(exists)
        log.warning.assert_called_once()

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_apply_flavor_qos_policy_updates_port(self, get_plugin):
        core_plugin = mock.Mock()
        get_plugin.return_value = core_plugin
        ctxt = mock.Mock()
        ctxt.elevated.return_value = "admin-context"

        self.plugin._apply_flavor_qos_policy(ctxt, self._port(), "policy-id")

        core_plugin.update_port.assert_called_once_with(
            "admin-context",
            "port-id",
            {"port": {"qos_policy_id": "policy-id"}},
        )

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_apply_flavor_qos_policy_noops_when_policy_already_matches(
            self, get_plugin):
        self.plugin._apply_flavor_qos_policy(
            mock.Mock(), self._port(qos_policy_id="policy-id"), "policy-id")

        get_plugin.assert_not_called()

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_apply_flavor_qos_policy_noops_when_core_plugin_missing(
            self, get_plugin):
        get_plugin.return_value = None

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._apply_flavor_qos_policy(
                mock.Mock(), self._port(), "policy-id")

        log.warning.assert_called_once()

import unittest
from unittest import mock

from neutron_lib.api.definitions import qos as qos_apidef
from neutron_lib.exceptions import qos as qos_exc
from neutron_lib.plugins import constants as plugin_constants
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
            "binding:profile": {},
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
            [qos_apidef.ALIAS],
            plugin.FlavorQosServicePlugin.required_service_plugins)
        self.assertNotEqual(
            plugin_constants.QOS,
            plugin.FlavorQosServicePlugin.required_service_plugins[0])
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
            updated, None)
        self.plugin._flavor_qos_policy_exists.assert_called_once_with(
            ctxt, updated, "policy-id")
        self.plugin._apply_flavor_qos_policy.assert_called_once_with(
            ctxt, updated, "policy-id")

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_uses_new_resize_generation(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        target_flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        old_migration_uuid = "dfd89f21-8f52-45f6-9ff0-71cde33482ab"
        new_migration_uuid = "5a8473d1-6ad6-4422-a075-04f342c329c9"
        original = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": target_flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": old_migration_uuid,
                },
            })
        updated = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": target_flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": new_migration_uuid,
                },
            })
        ctxt = mock.Mock()
        self.plugin._resolve_flavor_qos_policy_id = mock.Mock(
            return_value="policy-id")
        self.plugin._flavor_qos_policy_exists = mock.Mock(return_value=True)
        self.plugin._apply_flavor_qos_policy = mock.Mock()

        self.plugin._after_port_update(
            None, None, None, self._payload(original, updated, ctxt))

        self.plugin._resolve_flavor_qos_policy_id.assert_called_once_with(
            updated, target_flavor_id)
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

    def test_after_port_update_fails_open_on_transition_error(self):
        original = self._port()
        updated = self._port()
        self.plugin._is_unbinding_transition = mock.Mock(
            side_effect=RuntimeError("malformed callback data"))

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._after_port_update(
                None, None, None, self._payload(original, updated))

        log.exception.assert_called_once()

    @mock.patch("oslo_config.cfg.CONF")
    def test_after_port_update_fails_open_on_direct_flavor_lookup_error(
            self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        original = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": (
                        "dfd89f21-8f52-45f6-9ff0-71cde33482ab"),
                },
            })
        updated = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": (
                        "5a8473d1-6ad6-4422-a075-04f342c329c9"),
                },
            })
        self.plugin._nova_client = mock.Mock()
        self.plugin._nova_client.get_flavor_extra_specs.side_effect = (
            RuntimeError("nova is unavailable"))

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._after_port_update(
                None, None, None, self._payload(original, updated))

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
        payload = mock.Mock(metadata={"port": port}, context=ctxt)
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_called_once_with(
            ctxt, port)

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_port_without_policy(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        port = self._port(device_id=server_id, device_owner="compute:nova")
        payload = mock.Mock(metadata={"port": port}, context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_unmanaged_owner(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        port = self._port(device_id="router-id",
                          device_owner="network:router_interface",
                          **{"qos_policy_id": "policy-id"})
        payload = mock.Mock(metadata={"port": port}, context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    @mock.patch("oslo_config.cfg.CONF")
    def test_before_port_delete_ignores_unbound_device_id(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        port = self._port(**{"qos_policy_id": "policy-id"})
        payload = mock.Mock(metadata={"port": port}, context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, payload)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    def test_before_port_delete_noops_without_payload(self):
        self.plugin._clear_flavor_qos_policy = mock.Mock()

        self.plugin._before_port_delete(None, None, None, None)

        self.plugin._clear_flavor_qos_policy.assert_not_called()

    def test_before_port_delete_noops_with_malformed_state(self):
        payload = mock.Mock(metadata={"port": None}, context=mock.Mock())
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
        payload = mock.Mock(metadata={"port": port}, context=mock.Mock())
        self.plugin._clear_flavor_qos_policy = mock.Mock(
            side_effect=RuntimeError("db is unavailable"))

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.plugin._before_port_delete(None, None, None, payload)

        log.exception.assert_called_once()

    def test_before_port_delete_fails_open_on_candidate_check_error(self):
        port = self._port(qos_policy_id="policy-id")
        payload = mock.Mock(metadata={"port": port}, context=mock.Mock())
        self.plugin._is_delete_cleanup_candidate = mock.Mock(
            side_effect=RuntimeError("malformed callback data"))

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
    def test_binding_transition_matches_target_flavor_change(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": (
                        "a9f1fa9f-c4a4-43f1-a1c6-b1fca3cf9e42")},
            })
        updated = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": (
                        "d99ebe55-988d-41d5-a387-4fce42aadb68"),
                    "nova_flavor_instance_uuid": server_id},
            })

        self.assertTrue(
            self.plugin._is_binding_transition(original, updated))

    @mock.patch("oslo_config.cfg.CONF")
    def test_binding_transition_matches_new_resize_generation(self, conf):
        conf.flavor_qos.managed_device_owner_prefixes = ["compute:"]
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        original = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": (
                        "dfd89f21-8f52-45f6-9ff0-71cde33482ab"),
                },
            })
        updated = self._port(
            device_id=server_id,
            device_owner="compute:nova",
            **{
                "binding:host_id": "compute-01",
                "binding:profile": {
                    "nova_flavor_id": flavor_id,
                    "nova_flavor_instance_uuid": server_id,
                    "nova_flavor_migration_uuid": (
                        "5a8473d1-6ad6-4422-a075-04f342c329c9"),
                },
            })

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
            "flavor_qos:policy_id": (
                "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"),
            "other": "value",
        }

        policy_id = self.plugin._resolve_flavor_qos_policy_id(
            self._port(device_id="server-id"))

        self.assertEqual("4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2", policy_id)
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.assert_called_once_with("server-id")

    def test_resolve_flavor_qos_policy_id_from_bound_flavor(self):
        flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        policy_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        self.plugin._nova_client = mock.Mock()
        self.plugin._nova_client.get_flavor_extra_specs.return_value = {
            "flavor_qos:policy_id": policy_id,
        }
        port = self._port(**{
            "binding:profile": {"nova_flavor_id": flavor_id},
            "device_id": "server-id",
        })

        self.assertEqual(
            policy_id,
            self.plugin._resolve_flavor_qos_policy_id(port, flavor_id))

        get_flavor_specs = self.plugin._nova_client.get_flavor_extra_specs
        get_flavor_specs.assert_called_once_with(flavor_id)
        get_server_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_server_specs.assert_not_called()

    def test_changed_flavor_marker_is_trusted_for_bound_instance(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        old_flavor_id = "a9f1fa9f-c4a4-43f1-a1c6-b1fca3cf9e42"
        new_flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        original = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": old_flavor_id,
                "nova_flavor_instance_uuid": server_id,
                "nova_flavor_migration_uuid": (
                    "dfd89f21-8f52-45f6-9ff0-71cde33482ab"),
            }})
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": new_flavor_id,
                "nova_flavor_instance_uuid": server_id,
                "nova_flavor_migration_uuid": (
                    "5a8473d1-6ad6-4422-a075-04f342c329c9"),
            }})

        self.assertEqual(
            new_flavor_id,
            self.plugin._get_changed_nova_flavor_id(original, updated),
        )

    def test_unchanged_flavor_marker_falls_back_to_server_lookup(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        profile = {
            "nova_flavor_id": "d99ebe55-988d-41d5-a387-4fce42aadb68",
            "nova_flavor_instance_uuid": server_id,
            "nova_flavor_migration_uuid": (
                "5a8473d1-6ad6-4422-a075-04f342c329c9"),
        }
        original = self._port(
            device_id=server_id,
            **{"binding:profile": profile})
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": profile})

        self.assertIsNone(
            self.plugin._get_changed_nova_flavor_id(original, updated))

    def test_changed_flavor_marker_for_another_instance_is_not_trusted(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id)
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": (
                    "d99ebe55-988d-41d5-a387-4fce42aadb68"),
                "nova_flavor_instance_uuid": (
                    "1ed81c40-1493-4373-960f-7dd06e7fdb26"),
                "nova_flavor_migration_uuid": (
                    "5a8473d1-6ad6-4422-a075-04f342c329c9"),
            }})

        self.assertIsNone(
            self.plugin._get_changed_nova_flavor_id(original, updated))

    def test_repeated_target_flavor_with_new_generation_is_trusted(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        flavor_id = "d99ebe55-988d-41d5-a387-4fce42aadb68"
        original = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": flavor_id,
                "nova_flavor_instance_uuid": server_id,
                "nova_flavor_migration_uuid": (
                    "dfd89f21-8f52-45f6-9ff0-71cde33482ab"),
            }})
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": flavor_id,
                "nova_flavor_instance_uuid": server_id,
                "nova_flavor_migration_uuid": (
                    "5a8473d1-6ad6-4422-a075-04f342c329c9"),
            }})

        self.assertEqual(
            flavor_id,
            self.plugin._get_changed_nova_flavor_id(original, updated),
        )

    def test_flavor_marker_without_migration_uuid_is_not_trusted(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id)
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": (
                    "d99ebe55-988d-41d5-a387-4fce42aadb68"),
                "nova_flavor_instance_uuid": server_id,
            }})

        self.assertIsNone(
            self.plugin._get_changed_nova_flavor_id(original, updated))

    def test_malformed_migration_uuid_is_not_trusted(self):
        server_id = "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"
        original = self._port(device_id=server_id)
        updated = self._port(
            device_id=server_id,
            **{"binding:profile": {
                "nova_flavor_id": (
                    "d99ebe55-988d-41d5-a387-4fce42aadb68"),
                "nova_flavor_instance_uuid": server_id,
                "nova_flavor_migration_uuid": "not-a-uuid",
            }})

        self.assertIsNone(
            self.plugin._get_changed_nova_flavor_id(original, updated))

    def test_get_bound_nova_flavor_id_ignores_malformed_profile(self):
        self.assertIsNone(self.plugin._get_bound_nova_flavor_id(
            self._port(**{"binding:profile": "not-a-dict"})))

    def test_resolve_flavor_qos_policy_id_strips_extra_spec_value(self):
        self.plugin._nova_client = mock.Mock()
        self.plugin._nova_client.get_server_flavor_extra_specs.return_value = {
            "flavor_qos:policy_id": (
                " 4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2 "),
        }

        policy_id = self.plugin._resolve_flavor_qos_policy_id(
            self._port(device_id="server-id"))

        self.assertEqual("4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2", policy_id)

    def test_resolve_flavor_qos_policy_id_noops_for_blank_extra_spec(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {"flavor_qos:policy_id": "   "}

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

    def test_resolve_flavor_qos_policy_id_ignores_legacy_unnamespaced_key(
            self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {
            "flavor_qos_policy_id": (
                "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"),
        }

        with mock.patch("neutron_flavor_qos.plugin.LOG") as log:
            self.assertIsNone(self.plugin._resolve_flavor_qos_policy_id(
                self._port(device_id="server-id")))

        log.warning.assert_called_once()

    def test_resolve_flavor_qos_policy_id_requires_uuid_extra_spec_value(self):
        self.plugin._nova_client = mock.Mock()
        get_extra_specs = (
            self.plugin._nova_client.get_server_flavor_extra_specs)
        get_extra_specs.return_value = {"flavor_qos:policy_id": "not-a-uuid"}

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
                key="flavor_qos:policy_id", value="not-a-uuid"))
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
    def test_after_port_update_noops_when_unbind_clears_no_policy(
            self, conf):
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
    def test_clear_flavor_qos_policy_removes_markers_and_preserves_profile(
            self, get_plugin):
        core_plugin = mock.Mock()
        get_plugin.return_value = core_plugin
        ctxt = mock.Mock()
        ctxt.elevated.return_value = "admin-context"
        port = self._port(**{
            "binding:profile": {
                "allocation": "rp-uuid",
                "nova_flavor_id": (
                    "d99ebe55-988d-41d5-a387-4fce42aadb68"),
                "nova_flavor_instance_uuid": (
                    "4e7d2eaa-4f42-44b0-bf2b-97e0521a89b2"),
                "nova_flavor_migration_uuid": (
                    "5a8473d1-6ad6-4422-a075-04f342c329c9"),
            },
        })

        self.plugin._clear_flavor_qos_policy(ctxt, port)

        core_plugin.update_port.assert_called_once_with(
            "admin-context",
            "port-id",
            {"port": {"binding:profile": {"allocation": "rp-uuid"}}},
        )
        self.assertIn("nova_flavor_id", port["binding:profile"])

    @mock.patch("neutron_flavor_qos.plugin.directory.get_plugin")
    def test_clear_flavor_qos_policy_noops_when_state_already_clear(
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

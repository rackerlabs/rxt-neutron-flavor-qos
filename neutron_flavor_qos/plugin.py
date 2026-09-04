#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib.exceptions import qos as qos_exc
from neutron_lib import context as n_context
from neutron_lib.plugins import directory
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.services import base as service_base
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils

from neutron_flavor_qos import config
from neutron_flavor_qos import constants
from neutron_flavor_qos import exceptions
from neutron_flavor_qos import nova


LOG = logging.getLogger(__name__)


@registry.has_registry_receivers
class FlavorQosServicePlugin(service_base.ServicePluginBase):
    """Reconcile bound compute ports to flavor-selected QoS policies."""

    required_service_plugins = [plugin_constants.QOS]
    supported_extension_aliases = []
    _filter_validation_support = True
    path_prefix = ""

    def __init__(self):
        super().__init__()
        config.register_opts(cfg.CONF)
        self._nova_client = nova.NovaFlavorClient(cfg.CONF)
        LOG.info("Flavor QoS service plugin initialized")

    @classmethod
    def get_plugin_type(cls):
        return constants.PLUGIN_TYPE

    def get_plugin_description(self):
        return "Nova flavor based port QoS enforcement service plugin"

    @registry.receives(resources.PORT, [events.AFTER_UPDATE])
    def _after_port_update(self, resource, event, trigger, payload=None):
        if not payload or not payload.states:
            return

        original_port = payload.states[0]
        updated_port = payload.latest_state
        if not isinstance(original_port, dict) or not isinstance(
                updated_port, dict):
            return

        if not self._is_binding_transition(original_port, updated_port):
            return

        try:
            qos_policy_id = self._resolve_flavor_qos_policy_id(updated_port)
            if not qos_policy_id:
                return
            if not self._flavor_qos_policy_exists(payload.context,
                                                  updated_port,
                                                  qos_policy_id):
                return
            self._apply_flavor_qos_policy(payload.context, updated_port,
                                          qos_policy_id)
        except exceptions.FlavorQosMetadataInvalid as exc:
            LOG.warning(
                "%(error)s; leaving port %(port_id)s QoS unchanged",
                {"error": exc, "port_id": updated_port.get("id")},
            )
        except Exception:
            LOG.exception("Failed to enforce QoS for port %s",
                          updated_port.get("id"))

    def _is_binding_transition(self, original_port, updated_port):
        if self._is_internal_enforcement_update(original_port, updated_port):
            return False

        old_device_id = original_port.get("device_id")
        new_device_id = updated_port.get("device_id")
        if not new_device_id:
            return False

        if not uuidutils.is_uuid_like(new_device_id):
            return False

        device_owner = updated_port.get("device_owner") or ""
        if not self._is_managed_device_owner(device_owner):
            return False

        old_device_owner = original_port.get("device_owner") or ""
        old_host = original_port.get("binding:host_id")
        new_host = updated_port.get("binding:host_id")
        return (
            old_device_id != new_device_id
            or not self._is_managed_device_owner(old_device_owner)
            or (not old_host and bool(new_host))
        )

    def _is_managed_device_owner(self, device_owner):
        return any(
            prefix and device_owner.startswith(prefix)
            for prefix in cfg.CONF.flavor_qos.managed_device_owner_prefixes
        )

    def _is_internal_enforcement_update(self, original_port, updated_port):
        return (
            original_port.get("qos_policy_id") !=
            updated_port.get("qos_policy_id")
            and original_port.get("device_id") == updated_port.get("device_id")
            and original_port.get("device_owner") ==
            updated_port.get("device_owner")
        )

    def _resolve_flavor_qos_policy_id(self, port):
        extra_specs = self._nova_client.get_server_flavor_extra_specs(
            port["device_id"])
        extra_spec_key = constants.NOVA_FLAVOR_QOS_POLICY_EXTRA_SPEC
        qos_policy_id = extra_specs.get(extra_spec_key)
        if qos_policy_id:
            qos_policy_id = qos_policy_id.strip()
        if not qos_policy_id:
            LOG.warning(
                "Nova flavor for server %(server_id)s does not define "
                "%(key)s; leaving port %(port_id)s QoS unchanged",
                {
                    "server_id": port["device_id"],
                    "key": extra_spec_key,
                    "port_id": port["id"],
                },
            )
            return None
        if not uuidutils.is_uuid_like(qos_policy_id):
            raise exceptions.FlavorQosMetadataInvalid(
                key=extra_spec_key, value=qos_policy_id)
        return qos_policy_id

    def _flavor_qos_policy_exists(self, request_context, port, qos_policy_id):
        qos_plugin = directory.get_plugin(plugin_constants.QOS)
        if qos_plugin is None:
            LOG.warning(
                "QoS service plugin is not loaded; leaving port %(port_id)s "
                "QoS unchanged",
                {"port_id": port["id"]},
            )
            return False

        admin_context = self._admin_context(request_context)
        try:
            qos_plugin.get_policy(admin_context, qos_policy_id)
        except qos_exc.QosPolicyNotFound:
            LOG.warning(
                "Nova flavor for server %(server_id)s defines "
                "%(policy_id)s in %(key)s, but that Neutron QoS policy does "
                "not exist; leaving port %(port_id)s QoS unchanged",
                {
                    "server_id": port["device_id"],
                    "policy_id": qos_policy_id,
                    "key": constants.NOVA_FLAVOR_QOS_POLICY_EXTRA_SPEC,
                    "port_id": port["id"],
                },
            )
            return False
        return True

    def _apply_flavor_qos_policy(self, request_context, port, qos_policy_id):
        if port.get("qos_policy_id") == qos_policy_id:
            LOG.debug("Port %s already has expected flavor QoS policy",
                      port["id"])
            return

        core_plugin = directory.get_plugin()
        if core_plugin is None:
            LOG.warning(
                "Core plugin is not available; leaving port %(port_id)s "
                "QoS unchanged",
                {"port_id": port["id"]},
            )
            return

        admin_context = self._admin_context(request_context)
        core_plugin.update_port(
            admin_context,
            port["id"],
            {"port": {"qos_policy_id": qos_policy_id}},
        )
        LOG.info("Applied flavor QoS policy %(policy_id)s to port %(port_id)s",
                 {"policy_id": qos_policy_id, "port_id": port["id"]})

    def _admin_context(self, request_context):
        if request_context:
            return request_context.elevated()
        return n_context.get_admin_context()

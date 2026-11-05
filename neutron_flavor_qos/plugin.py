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

import copy

from neutron_lib.api.definitions import qos as qos_apidef
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib import context as n_context
from neutron_lib.exceptions import qos as qos_exc
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.plugins import directory
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

    # Neutron treats these values as providers in the
    # ``neutron.service_plugins`` entry-point namespace.  The provider alias
    # is lower-case ``qos``; plugin_constants.QOS (``QOS``) is instead the
    # type used to look up the already-loaded plugin in the directory.
    required_service_plugins = [qos_apidef.ALIAS]
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

    @registry.receives(resources.PORT, [events.BEFORE_DELETE])
    def _before_port_delete(self, resource, event, trigger, payload=None):
        port = None
        try:
            if not payload:
                return

            # ML2 publishes BEFORE_DELETE with the port in payload.metadata
            # (states is empty for this event). The full port dict, including
            # qos_policy_id, device_id, and device_owner, lives there.
            port = (payload.metadata or {}).get("port")
            if not isinstance(port, dict):
                return

            if not self._is_delete_cleanup_candidate(port):
                return

            self._clear_flavor_qos_policy(payload.context, port)
        except Exception:
            LOG.exception("Failed to clear QoS for deleted port %s",
                          port.get("id") if isinstance(port, dict) else None)

    def _is_delete_cleanup_candidate(self, port):
        if not port.get("qos_policy_id"):
            return False

        device_id = port.get("device_id")
        if not device_id or not uuidutils.is_uuid_like(device_id):
            return False

        device_owner = port.get("device_owner") or ""
        return self._is_managed_device_owner(device_owner)

    @registry.receives(resources.PORT, [events.AFTER_UPDATE])
    def _after_port_update(self, resource, event, trigger, payload=None):
        updated_port = None
        try:
            if not payload or not payload.states:
                return

            original_port = payload.states[0]
            updated_port = payload.latest_state
            if not isinstance(original_port, dict) or not isinstance(
                    updated_port, dict):
                return

            if self._is_unbinding_transition(original_port, updated_port):
                self._clear_flavor_qos_policy(payload.context, updated_port)
                return

            if not self._is_binding_transition(original_port, updated_port):
                return

            changed_flavor_id = self._get_changed_nova_flavor_id(
                original_port, updated_port)
            qos_policy_id = self._resolve_flavor_qos_policy_id(
                updated_port, changed_flavor_id)
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
                {
                    "error": exc,
                    "port_id": (updated_port.get("id") if isinstance(
                        updated_port, dict) else None),
                },
            )
        except Exception:
            LOG.exception(
                "Failed to process flavor QoS for port %s; continuing",
                updated_port.get("id") if isinstance(
                    updated_port, dict) else None)

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

        # A managed compute binding already on a host is only re-evaluated if
        # Nova rebinds the port to a different host (migration), a different
        # server (re-attach), or records a new resize generation. Repeated
        # PUTs that repeat the same binding generation are ignored.
        old_device_owner = original_port.get("device_owner") or ""
        old_host = original_port.get("binding:host_id")
        new_host = updated_port.get("binding:host_id")
        old_flavor_id = self._get_bound_nova_flavor_id(original_port)
        new_flavor_id = self._get_bound_nova_flavor_id(updated_port)
        old_migration_uuid = self._get_bound_nova_flavor_migration_uuid(
            original_port)
        new_migration_uuid = self._get_bound_nova_flavor_migration_uuid(
            updated_port)
        return (
            old_device_id != new_device_id
            or not self._is_managed_device_owner(old_device_owner)
            or (old_host != new_host and bool(new_host))
            or (old_flavor_id != new_flavor_id and bool(new_flavor_id))
            or (old_migration_uuid != new_migration_uuid
                and bool(new_migration_uuid))
        )

    def _is_unbinding_transition(self, original_port, updated_port):
        if self._is_internal_enforcement_update(original_port, updated_port):
            return False

        new_device_id = updated_port.get("device_id")
        if new_device_id:
            return False

        device_owner = updated_port.get("device_owner") or ""
        if self._is_managed_device_owner(device_owner):
            return False

        old_device_owner = original_port.get("device_owner") or ""
        old_device_id = original_port.get("device_id")
        return (
            self._is_managed_device_owner(old_device_owner) and
            bool(old_device_id)
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

    def _get_bound_nova_flavor_id(self, port):
        binding_profile = port.get("binding:profile") or {}
        if not isinstance(binding_profile, dict):
            return None
        flavor_id = binding_profile.get(
            constants.NOVA_FLAVOR_ID_BINDING_PROFILE_KEY)
        if flavor_id is None:
            return None
        flavor_id = str(flavor_id).strip()
        return flavor_id or None

    def _get_bound_nova_flavor_instance_uuid(self, port):
        binding_profile = port.get("binding:profile") or {}
        if not isinstance(binding_profile, dict):
            return None
        instance_uuid = binding_profile.get(
            constants.NOVA_FLAVOR_INSTANCE_UUID_BINDING_PROFILE_KEY)
        if instance_uuid is None:
            return None
        instance_uuid = str(instance_uuid).strip()
        return instance_uuid or None

    def _get_bound_nova_flavor_migration_uuid(self, port):
        binding_profile = port.get("binding:profile") or {}
        if not isinstance(binding_profile, dict):
            return None
        migration_uuid = binding_profile.get(
            constants.NOVA_FLAVOR_MIGRATION_UUID_BINDING_PROFILE_KEY)
        if migration_uuid is None:
            return None
        migration_uuid = str(migration_uuid).strip()
        return migration_uuid or None

    def _get_changed_nova_flavor_id(self, original_port, updated_port):
        """Return a direct flavor marker for a new resize generation.

        The migration UUID makes each publication unique even when a stale
        marker already contains the target flavor. The instance UUID prevents
        a marker retained across detach/reattach from being trusted for
        another server. Incomplete, malformed, or repeated marker sets fall
        back to the normal Nova server lookup.
        """
        new_flavor_id = self._get_bound_nova_flavor_id(updated_port)
        if not new_flavor_id:
            return None

        marker_instance_uuid = self._get_bound_nova_flavor_instance_uuid(
            updated_port)
        if marker_instance_uuid != updated_port.get("device_id"):
            return None

        old_migration_uuid = self._get_bound_nova_flavor_migration_uuid(
            original_port)
        new_migration_uuid = self._get_bound_nova_flavor_migration_uuid(
            updated_port)
        old_flavor_id = self._get_bound_nova_flavor_id(original_port)
        if not uuidutils.is_uuid_like(new_migration_uuid):
            return None
        if (old_migration_uuid == new_migration_uuid
                and old_flavor_id == new_flavor_id):
            return None
        return new_flavor_id

    def _resolve_flavor_qos_policy_id(self, port, flavor_id=None):
        if flavor_id:
            extra_specs = self._nova_client.get_flavor_extra_specs(flavor_id)
            flavor_description = "Nova flavor %s" % flavor_id
        else:
            extra_specs = self._nova_client.get_server_flavor_extra_specs(
                port["device_id"])
            flavor_description = "Nova flavor for server %s" % port[
                "device_id"]
        extra_spec_key = constants.NOVA_FLAVOR_QOS_POLICY_EXTRA_SPEC
        qos_policy_id = extra_specs.get(extra_spec_key)
        if qos_policy_id:
            qos_policy_id = qos_policy_id.strip()
        if not qos_policy_id:
            LOG.warning(
                "%(flavor)s does not define "
                "%(key)s; leaving port %(port_id)s QoS unchanged",
                {
                    "flavor": flavor_description,
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

    def _clear_flavor_qos_policy(self, request_context, port):
        updates = {}
        if port.get("qos_policy_id"):
            updates["qos_policy_id"] = None

        binding_profile = port.get("binding:profile") or {}
        if isinstance(binding_profile, dict):
            cleaned_profile = copy.deepcopy(binding_profile)
            removed_marker = False
            for key in (
                constants.NOVA_FLAVOR_ID_BINDING_PROFILE_KEY,
                constants.NOVA_FLAVOR_INSTANCE_UUID_BINDING_PROFILE_KEY,
                constants.NOVA_FLAVOR_MIGRATION_UUID_BINDING_PROFILE_KEY,
            ):
                if key in cleaned_profile:
                    del cleaned_profile[key]
                    removed_marker = True
            if removed_marker:
                updates["binding:profile"] = cleaned_profile

        if not updates:
            LOG.debug("Port %s has no flavor QoS state to clear on unbind",
                      port["id"])
            return

        core_plugin = directory.get_plugin()
        if core_plugin is None:
            LOG.warning(
                "Core plugin is not available; leaving port %(port_id)s "
                "QoS policy on unbind",
                {"port_id": port["id"]},
            )
            return

        admin_context = self._admin_context(request_context)
        core_plugin.update_port(
            admin_context,
            port["id"],
            {"port": updates},
        )
        LOG.info("Cleared flavor QoS state from unbound port %(port_id)s",
                 {"port_id": port["id"]})

    def _admin_context(self, request_context):
        if request_context:
            return request_context.elevated()
        return n_context.get_admin_context()

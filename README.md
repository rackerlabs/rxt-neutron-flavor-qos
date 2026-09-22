# Flavor QoS Service Plugin

Out-of-tree Neutron service plugin that enforces port-level QoS after a port
is bound to a Nova server. The QoS policy is selected from Nova flavor extra
specs managed by the operator.

The plugin observes Neutron `PORT` `AFTER_UPDATE` callbacks. It ignores
ordinary port updates and evaluates compute binding transitions, including
ports that already have a server `device_id` before their first
`binding:host_id` assignment. Once Nova binds the port to an instance, the
plugin asks Nova for the server's flavor, reads that flavor's extra specs, and
applies the declared QoS policy ID to the port with an elevated Neutron
context.

## Why AFTER_UPDATE

The plugin intentionally does not mutate Neutron's in-flight callback payload.
Neutron completes the port update naturally, including Nova's binding update,
then this plugin reconciles the bound port to the correct QoS policy.

All Nova server-create network request forms converge on that same Neutron port
lifecycle. Existing ports are updated in place. Network requests, fixed-IP
requests, and auto-allocated networks cause Nova to create a Neutron port first,
then update it with the server identity and binding details.

```text
openstack port create
  -> no device_id, ignored

openstack server create --port <port>
openstack server create --nic port-id=<port>
openstack server create --nic net-id=<network>
openstack server create --nic net-id=<network>,v4-fixed-ip=<ipv4>
openstack server create --nic net-id=<network>,v6-fixed-ip=<ipv6>
openstack server create --auto-network
  -> Nova resolves the requested networks
  -> Nova creates or updates Neutron ports
  -> Nova binds the ports
  -> AFTER_UPDATE fires
  -> plugin reads the server's Nova flavor through Nova's API
  -> plugin applies the flavor-selected QoS policy to each bound port
```

## Flavor Metadata

Set the Neutron QoS policy ID directly on the Nova flavor:

```bash
openstack flavor set m1.large \
  --property flavor_qos_policy_id=<qos-policy-uuid>
```

The plugin reads only the `flavor_qos_policy_id` extra spec. The value must be
the UUID of an existing Neutron QoS policy.

## Neutron Configuration

Install this package into the same Python environment as `neutron-server`, then
enable the service plugin:

```ini
[DEFAULT]
service_plugins = router,qos,flavor_qos

[flavor_qos]
auth_type = password
auth_url = https://keystone.example.org/v3
project_name = service
project_domain_name = Default
username = neutron
user_domain_name = Default
password = secret
service_type = compute
valid_interfaces = internal,public
managed_device_owner_prefixes = compute:
```

The plugin uses these Keystone service credentials to make Nova API calls. It
first reads the server to find its flavor ID, then reads that flavor's extra
specs. The Neutron server process applies the port update with an elevated
Neutron context, so it must also be able to update port `qos_policy_id`
bindings. Before applying the policy, the plugin verifies that the referenced
Neutron QoS policy exists through the enabled QoS service plugin.

Required policy hardening when `flavor_qos` is enabled:

```yaml
"create_port:qos_policy_id": "rule:admin_only"
"update_port:qos_policy_id": "rule:admin_only"
```

With `flavor_qos` enabled, tenant-managed per-port QoS assignment is not
supported for compute workloads. Operators should treat the Nova flavor extra
spec as the source of truth and prevent tenants from attaching, replacing, or
removing port QoS policies through `qos_policy_id`.

## Unbinding and Deletion Cleanup

The plugin clears a port's `qos_policy_id` back to `None` on two transitions,
so a flavor-selected policy never carries over to a later, unrelated attach of
the same port.

**Unbind (AFTER_UPDATE).** When a port's device identity is cleared
(`device_id` / `device_owner` stripped, port no longer owned by a managed
prefix), the plugin clears the policy. This covers manual detach and the
tenant-supplied-port deletion path.

**Delete (BEFORE_DELETE).** When a port that is still bound to a managed server
and still carries a policy is deleted, the plugin clears the policy before the
row is removed. This covers the Nova-auto-created port path: during instance
deletion, Nova deletes ports it created for the server (the `--nic net-id=...`
and `--auto-network` forms) directly, without first unbinding them, so the
unbind transition never fires for those ports.

The two paths are complementary. Nova's `deallocate_for_instance` unbinds
tenant-supplied / preexisting ports (cleared by the AFTER_UPDATE path) and
deletes auto-created ports in place (cleared by the BEFORE_DELETE path).

Both handlers are exception-guarded: a failure to clear the policy is logged
and never blocks the underlying port update or deletion.

## Manual Enablement Task

Enabling `flavor_qos` only affects future binding transitions. Ports that were
already bound to servers before the plugin was enabled are not retrofitted
automatically. To reconcile them, for each bound compute port apply the QoS
policy declared on the server's flavor:

```bash
# List bound compute ports missing the flavor-selected policy
openstack port list --device-owner "compute:*" --long \
  | awk '{print $2, $NF}'

# For each port, set the policy from the server flavor's extra spec
openstack flavor show <flavor> --column flavor_qos_policy_id
openstack port set <port-id> --qos-policy <qos-policy-uuid>
```

## Per-Port QoS Semantics

The flavor's `flavor_qos_policy_id` is applied **per attached port**, not per
server. A multi-NIC instance receives the policy on every NIC, so the
flavor-declared limit is the per-interface ceiling: a 1 Gbps policy on a
three-NIC server allows up to 3 Gbps aggregate throughput. To express a
per-server total, the operator must choose the flavor policy value
accordingly (for example, the per-NIC share of the intended total) or accept
per-interface enforcement.

## Missing Flavor Metadata

If the bound server's flavor does not define `flavor_qos_policy_id`, the plugin
logs a warning and leaves the port QoS unchanged. If the referenced Neutron QoS
policy UUID does not exist, the plugin also logs a warning and leaves the port
QoS unchanged. Nova lookup failures, invalid UUID values, and Neutron port
update failures are logged and leave the original port update in place.

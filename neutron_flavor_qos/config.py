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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg


GROUP = "flavor_qos"

OPTS = [
    cfg.ListOpt(
        "managed_device_owner_prefixes",
        default=["compute:"],
        help="Device owner prefixes that should trigger QoS enforcement.",
    ),
]


def register_opts(conf=cfg.CONF):
    for opt in OPTS:
        try:
            conf.register_opt(opt, group=GROUP)
        except cfg.DuplicateOptError:
            pass
    ks_loading.register_auth_conf_options(conf, GROUP)
    ks_loading.register_session_conf_options(conf, GROUP)
    ks_loading.register_adapter_conf_options(conf, GROUP)
    conf.set_default("service_type", "compute", group=GROUP)
    conf.set_default("valid_interfaces", ["internal", "public"], group=GROUP)


def list_opts():
    return [(
        GROUP,
        OPTS +
        ks_loading.get_auth_common_conf_options() +
        ks_loading.get_session_conf_options() +
        ks_loading.get_adapter_conf_options(),
    )]

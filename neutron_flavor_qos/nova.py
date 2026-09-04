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

from urllib import parse

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
from oslo_log import log as logging

from neutron_flavor_qos import config


LOG = logging.getLogger(__name__)


class NovaFlavorClient:
    """Resolve Nova flavor extra specs through Nova's public API."""

    def __init__(self, conf=cfg.CONF):
        self.conf = conf
        self._adapter = None

    def get_server_flavor_extra_specs(self, server_id):
        flavor_id = self._get_server_flavor_id(server_id)
        if not flavor_id:
            LOG.warning("Nova server %s did not include a flavor ID",
                        server_id)
            return {}

        return self._get_flavor_extra_specs(flavor_id)

    def _get_server_flavor_id(self, server_id):
        server_path_id = parse.quote(str(server_id), safe="")
        response = self._get_adapter().get("/servers/%s" % server_path_id)
        server = self._json_body(response).get("server", {})
        if not isinstance(server, dict):
            return None
        flavor = server.get("flavor")
        if isinstance(flavor, dict):
            return flavor.get("id")
        if isinstance(flavor, str):
            return flavor
        return None

    def _get_flavor_extra_specs(self, flavor_id):
        flavor_path_id = parse.quote(str(flavor_id), safe="")
        response = self._get_adapter().get(
            "/flavors/%s/os-extra_specs" % flavor_path_id)
        extra_specs = self._json_body(response).get("extra_specs", {})
        if not isinstance(extra_specs, dict):
            extra_specs = {}
        return extra_specs

    def _json_body(self, response):
        body = response.json()
        if isinstance(body, dict):
            return body
        return {}

    def _get_adapter(self):
        if self._adapter is None:
            config.register_opts(self.conf)
            auth = ks_loading.load_auth_from_conf_options(
                self.conf, config.GROUP)
            session = ks_loading.load_session_from_conf_options(
                self.conf, config.GROUP, auth=auth)
            self._adapter = ks_loading.load_adapter_from_conf_options(
                self.conf, config.GROUP, session=session)
        return self._adapter

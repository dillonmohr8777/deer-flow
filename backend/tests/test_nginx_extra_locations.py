"""A deployment can mount extra nginx locations next to DeerFlow.

The main server block includes ``/etc/nginx/momentum-extra/*.conf``. A glob that
matches nothing is an empty include (``nginx -t`` and a real start both pass), so
a stack with nothing mounted behaves exactly as it did before the include. This
pins where the include sits: a ``location`` file is only valid inside a server
block, so moving it out would break the first deployment that mounts one.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "docker/nginx/nginx.conf"
EXTRA_LOCATIONS_INCLUDE = "include /etc/nginx/momentum-extra/*.conf;"


def test_main_server_block_includes_the_extra_location_files() -> None:
    config = NGINX_CONF.read_text(encoding="utf-8")

    assert config.count(EXTRA_LOCATIONS_INCLUDE) == 1

    # Between the main server's listen line and its first location directive, so
    # the mounted files sit inside that block, next to the locations it serves.
    after_listen = config.split("listen 2026 default_server;", 1)[1]
    server_preamble = re.split(r"^\s*location\s", after_listen, maxsplit=1, flags=re.MULTILINE)[0]
    assert EXTRA_LOCATIONS_INCLUDE in server_preamble

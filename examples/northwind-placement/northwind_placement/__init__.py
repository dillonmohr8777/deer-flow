"""Northwind uses the public extension contract and the host's authenticated identity."""

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionRegistry, extension

from northwind_placement.api import Service, build_router


@extension(api="0.2.2", name="northwind")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    service = Service(config)
    registry.service(service)
    registry.routers((build_router(service),))

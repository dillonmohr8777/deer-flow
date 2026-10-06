"""Report Studio: build a client weekly report page and deploy only that page after approval."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_report_studio.render import CLIENT_ID_RE, WEEK_RE, Settings, configure

__all__ = ["install"]


def validate_deploy(target: str, payload: dict[str, Any]) -> None:
    from deerflow.approvals import InvalidPayloadError

    if not CLIENT_ID_RE.fullmatch(target):
        raise InvalidPayloadError("deploy_report needs the client id as the target")
    if not WEEK_RE.fullmatch(str(payload.get("week", ""))):
        raise InvalidPayloadError("deploy_report needs payload.week as YYYY-MM-DD")
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("bundle_sha256", ""))):
        raise InvalidPayloadError("deploy_report needs payload.bundle_sha256 from build_report_page")


@extension(api="0.2.0", name="report-studio")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Add the ``deploy_report`` approval type and its adapter. The ``build_report_page`` tool is listed under ``tools:`` in config.yaml."""
    if config.get("enabled", True) is False:
        return
    from app.gateway.approval_adapters import register_adapter
    from deerflow.approvals import register_action_type

    from deerflow_report_studio.deploy import DeployReportAdapter

    settings = Settings.from_config(config)
    configure(settings)
    register_action_type("deploy_report", validate_deploy)
    register_adapter("deploy_report", DeployReportAdapter(settings))


_entry_point: ExtensionInstall = install

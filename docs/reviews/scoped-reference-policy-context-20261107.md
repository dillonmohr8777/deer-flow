# Scoped reference policy: immutable dependency context

This artifact supplies unchanged dependencies to the changed-file-only native review transport. It is code and provenance, not a verdict. The new projection, exact route admission, registration, documentation and tests are supplied separately in the ordinary packet.

Source commit: `5e0c026d2f4dda1ab67196da81e80594da2208a7`. Every module below is included in full, byte-for-byte, with SHA-256. Coverage: AppConfig extra-section retention and hot config lookup; backend request dependencies; project/document ownership and organization filtering; filesystem confinement; original-byte metadata; server-stamped session identity and membership; storage context; existing project permission enforcement. The new projection has its own default-off explicit actor/org/project/document/hash capability; it does not change that existing project policy. Imports remain visible; not every transitive framework dependency is repeated.

| Source path | Bytes | SHA-256 |
| --- | ---: | --- |
| `backend/packages/harness/deerflow/config/app_config.py` | 41860 | `abb0fa1364a8b1bbbbab650d59e72494f31d67f2feeb39c335c8bd7ddb5eb1bc` |
| `backend/packages/harness/deerflow/config/paths.py` | 26290 | `0279ebf532daca86b90a5a5bf3259fca9417f5b86d7f9d7e7109944bedab142d` |
| `backend/app/gateway/deps.py` | 48909 | `5e0572a0f64a0cbc14d2c3982a985b3a3b2d423eeef5608fc08261cd69487724` |
| `backend/packages/harness/deerflow/persistence/projects/sql.py` | 47370 | `c6a23d7eece8ec827cb68810c0590aae886860d3f1409c309662d96e87b67117` |
| `backend/packages/harness/deerflow/projects/documents.py` | 25970 | `6d8151480bea1f7118ac29c7c5a0c0ca9ba3b72c64705007dbeffc26829dd27e` |
| `backend/app/gateway/authz.py` | 37761 | `ad89dcdc3e6791b1acd12c89cba02b3d897ee2e14c97be4534db0fb036130c3d` |
| `backend/app/gateway/auth_middleware.py` | 21186 | `acd84dafe0e091f363d38d4a6c4c5fed0a7fb0f37a5df419621e77d24bda0e40` |
| `backend/packages/harness/deerflow/runtime/user_context.py` | 17769 | `5e028b444ea292160e8543497c7f399d9822ded43c420de8e41d94acedc5db72` |
| `backend/packages/harness/deerflow/persistence/organizations/resolution.py` | 6237 | `985102a553d338c6b05d65576297c0c15c55a7ddd8c608d951e03f3849571288` |
| `backend/packages/harness/deerflow/persistence/projects/model.py` | 3912 | `10a7d418091b62c804945e4862f38fd21505306e4a2b7cc2d2f21bcd9a1c7f6c` |

## backend/packages/harness/deerflow/config/app_config.py

````python
import logging
import os
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from deerflow.config.acp_config import ACPAgentConfig, load_acp_config_from_dict
from deerflow.config.agent_storage_config import AgentStorageConfig
from deerflow.config.agents_api_config import AgentsApiConfig, load_agents_api_config_from_dict
from deerflow.config.auth_config import AuthAppConfig
from deerflow.config.authorization_config import AuthorizationConfig, load_authorization_config_from_dict
from deerflow.config.channel_connections_config import ChannelConnectionsConfig
from deerflow.config.checkpointer_config import CheckpointerConfig, load_checkpointer_config_from_dict
from deerflow.config.cost_router_config import CostRouterConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.dedupe_storage_config import DedupeStorageConfig
from deerflow.config.entitlement_config import EntitlementConfig, load_entitlement_config_from_dict
from deerflow.config.exec_seats_config import ExecSeatsConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.file_signature import ConfigSignature as _ConfigSignature
from deerflow.config.file_signature import get_config_signature as _get_config_signature
from deerflow.config.guardrails_config import GuardrailsConfig, load_guardrails_config_from_dict
from deerflow.config.hiring_config import HiringConfig
from deerflow.config.input_polish_config import InputPolishConfig
from deerflow.config.knowledge_base_config import KnowledgeBaseConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.mcp_tasks_config import McpTasksConfig
from deerflow.config.memory_config import MemoryConfig, load_memory_config_from_dict
from deerflow.config.model_config import ModelConfig
from deerflow.config.momobot_brand_config import MomobotBrandConfig
from deerflow.config.momobot_max_config import MomobotMaxConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.config.projects_config import ProjectsConfig
from deerflow.config.read_before_write_config import ReadBeforeWriteConfig
from deerflow.config.reload_boundary import format_field_description
from deerflow.config.roster_config import RosterConfig
from deerflow.config.run_config import RunConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.config.runtime_paths import existing_project_file
from deerflow.config.safety_finish_reason_config import SafetyFinishReasonConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.config.skill_evolution_config import SkillEvolutionConfig
from deerflow.config.skill_scan_config import SkillScanConfig
from deerflow.config.skills_config import SkillsConfig
from deerflow.config.stream_bridge_config import StreamBridgeConfig, load_stream_bridge_config_from_dict
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.config.subagents_config import SubagentsAppConfig, load_subagents_config_from_dict
from deerflow.config.suggestions_config import SuggestionsConfig
from deerflow.config.summarization_config import SummarizationConfig, load_summarization_config_from_dict
from deerflow.config.task_continuity_config import TaskContinuityConfig
from deerflow.config.title_config import TitleConfig, load_title_config_from_dict
from deerflow.config.token_budget_config import TokenBudgetConfig
from deerflow.config.token_usage_config import TokenUsageConfig
from deerflow.config.tool_config import ToolConfig, ToolGroupConfig
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.config.tool_progress_config import ToolProgressConfig
from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict
from deerflow.config.verification_config import VerificationConfig
from deerflow.extensions.loader import ExtensionSpec

load_dotenv()

logger = logging.getLogger(__name__)


CONFIG_FILE_DATABASE_DEFAULTS = {
    "backend": "sqlite",
    "sqlite_dir": ".deer-flow/data",
}


class CircuitBreakerConfig(BaseModel):
    """Configuration for the LLM Circuit Breaker."""

    failure_threshold: int = Field(default=5, description="Number of consecutive failures before tripping the circuit")
    recovery_timeout_sec: int = Field(default=60, description="Time in seconds before attempting to recover the circuit")


class PrivateWorkspaceConfig(BaseModel):
    """Switches that belong only to the owner's private instance."""

    enabled: bool = Field(
        default=False,
        description="Marks this instance as the owner's private workspace and turns on the Desk home. Leave false on every client-facing MomoBot.",
    )


class MomentumInternalConfig(BaseModel):
    """Staff-only surfaces (Team channels, AI Academy) for the agency's own workspace."""

    enabled: bool = Field(
        default=False,
        description="Turns on Team channels and the AI Academy for the workspaces listed in organization_slugs. Off by default.",
    )
    organization_slugs: list[str] = Field(
        default_factory=list,
        description="Slugs of the agency's own workspaces (organizations). Only owners, admins and members of these see Team and AI Academy. Never list a client workspace.",
    )


class LlmCallConfig(BaseModel):
    """Configuration for LLM call execution (concurrency / rate shaping).

    Distinct from :class:`CircuitBreakerConfig` (which handles a *failing*
    provider) and from :class:`ModelConfig` (which describes model endpoints):
    these knobs shape how many LLM calls run at once and how the retry/backoff
    loop behaves. Capping concurrency caps the *slope* of the request rate,
    which is what a provider burst-rate (``limit_burst_rate``) limit fires on.
    """

    max_concurrent_calls: int = Field(
        default=0,
        ge=0,
        description=(
            "Process-wide cap on concurrently in-flight LLM calls. 0 disables "
            "the cap (default, preserving existing behavior). Set to a positive "
            "int to smooth provider burst-rate (limit_burst_rate) spikes by "
            "bounding the request-rate slope at the morning peak. Per-process, "
            "not per-cluster: with GATEWAY_WORKERS > 1 the aggregate cap is "
            "effectively max_concurrent_calls * GATEWAY_WORKERS (and a "
            "multi-node rollout multiplies it further), so size the per-process "
            "value accordingly and pair it with an nginx limit_req at the ingress "
            "for a true cluster-wide slope cap. Startup-only: the cap is captured "
            "at the first LLM run and frozen for the process lifetime, so editing "
            "it in config.yaml takes effect only after a gateway restart (the "
            "other llm_call.* knobs remain hot-reloadable). Freezing avoids the "
            "downscale/config-freshness races a runtime-mutable cap would "
            "introduce on a process-wide, cross-loop limiter."
        ),
    )
    retry_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Max LLM call attempts (1 = no retry) for retriable transient errors.",
    )
    retry_base_delay_ms: int = Field(
        default=1000,
        ge=0,
        description="Base (ms) for the decorrelated-jitter retry backoff; seeds the first retry delay.",
    )
    retry_cap_delay_ms: int = Field(
        default=8000,
        ge=0,
        description="Hard cap (ms) on any single retry backoff delay.",
    )
    burst_retry_base_delay_ms: int = Field(
        default=5000,
        ge=0,
        description=(
            "Base (ms) for the backoff when the provider returns a burst-rate "
            "(limit_burst_rate) 429. Higher than retry_base_delay_ms so the "
            "single burst retry lands after the throttle window subsides. "
            "Ignored when the provider sends Retry-After (honored verbatim)."
        ),
    )


class LoggingEnhanceConfig(BaseModel):
    """Request trace logging enhancement settings.

    Trace ids are issued unconditionally (``TraceMiddleware`` for HTTP,
    ``ensure_trace_context`` elsewhere) and always returned in the
    ``X-Trace-Id`` response header. This block decides only whether log
    records carry that id, and in which format.
    """

    enabled: bool = Field(
        default=False,
        description="Print the request trace id into log records. Trace ids are always issued and always returned in the X-Trace-Id response header; this controls log output only.",
    )
    format: Literal["text", "json"] = Field(default="text", description="Enhanced log output format.")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    enhance: LoggingEnhanceConfig = Field(default_factory=LoggingEnhanceConfig, description="Request trace correlation logging settings.")


def _legacy_config_candidates() -> tuple[Path, ...]:
    """Return source-tree config.yaml locations for monorepo compatibility."""
    backend_dir = Path(__file__).resolve().parents[4]
    repo_root = backend_dir.parent
    return (backend_dir / "config.yaml", repo_root / "config.yaml")


def logging_level_from_config(name: str | None) -> int:
    """Map ``config.yaml`` ``log_level`` string to a :mod:`logging` level constant."""
    mapping = logging.getLevelNamesMapping()
    return mapping.get((name or "info").strip().upper(), logging.INFO)


def apply_logging_level(name: str | None) -> None:
    """Resolve *name* to a logging level and apply it to the ``deerflow``/``app`` logger hierarchies.

    Only the ``deerflow`` and ``app`` logger levels are changed so that
    third-party library verbosity (e.g. uvicorn, sqlalchemy) is not
    affected. Root handler levels are lowered (never raised) so that
    messages from the configured loggers can propagate through without
    being filtered, while preserving handler thresholds that may be
    intentionally restrictive for third-party log output.
    """
    level = logging_level_from_config(name)
    for logger_name in ("deerflow", "app"):
        logging.getLogger(logger_name).setLevel(level)
    for handler in logging.root.handlers:
        if level < handler.level:
            handler.setLevel(level)


class AppConfig(BaseModel):
    """Config for the DeerFlow application"""

    log_level: str = Field(
        default="info",
        description=format_field_description(
            "log_level",
            field_doc="Logging level for deerflow and app modules (debug/info/warning/error); third-party libraries are not affected.",
        ),
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description=format_field_description(
            "logging",
            field_doc="Structured logging settings: whether request trace ids appear in log records, and in which format.",
        ),
    )
    token_usage: TokenUsageConfig = Field(default_factory=TokenUsageConfig, description="Token usage tracking configuration")
    token_budget: TokenBudgetConfig = Field(default_factory=TokenBudgetConfig, description="Token Budget tracking and limits configuration.")
    cost_router: CostRouterConfig = Field(default_factory=CostRouterConfig, description="Cost router: task class routes, USD spend caps, price table and model denylist.")
    plugins: list[ExtensionSpec] = Field(
        default_factory=list,
        description=format_field_description(
            "plugins",
            field_doc=(
                "Extension packages to load at startup, in order. Each entry names an install "
                "entry point as 'module.path:install' and carries its own private config block. "
                "Distinct from the `extensions` field above, which configures MCP servers, skills "
                "and config-declared middlewares and is backed by the HTTP-writable "
                "extensions_config.json."
            ),
        ),
    )
    recursion_limit: int = Field(
        default=100,
        ge=1,
        description="Default LangGraph recursion_limit for Gateway runs when the client does not provide one. Applied per run and capped by max_recursion_limit.",
    )
    max_recursion_limit: int = Field(
        default=1000,
        ge=1,
        description="Hard server-side ceiling for configured defaults and client-supplied run recursion_limit values. Values above this are clamped; prevents runaway LangGraph super-steps (LLM cost / DoS).",
    )
    models: list[ModelConfig] = Field(default_factory=list, description="Available models")
    sandbox: SandboxConfig = Field(
        description=format_field_description(
            "sandbox",
            field_doc="Sandbox provider configuration (local filesystem or Docker-based aio sandbox).",
        ),
    )
    tools: list[ToolConfig] = Field(default_factory=list, description="Available tools")
    tool_groups: list[ToolGroupConfig] = Field(default_factory=list, description="Available tool groups")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills configuration")
    skill_scan: SkillScanConfig = Field(default_factory=SkillScanConfig, description="Native deterministic skill safety scanning configuration")
    skill_evolution: SkillEvolutionConfig = Field(default_factory=SkillEvolutionConfig, description="Agent-managed skill evolution configuration")
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig, description="Extensions configuration (MCP servers and skills state)")
    tool_output: ToolOutputConfig = Field(default_factory=ToolOutputConfig, description="Tool output budget protection configuration")
    tool_search: ToolSearchConfig = Field(default_factory=ToolSearchConfig, description="Tool search / deferred loading configuration")
    title: TitleConfig = Field(default_factory=TitleConfig, description="Automatic title generation configuration")
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig, description="Conversation summarization configuration")
    task_continuity: TaskContinuityConfig = Field(default_factory=TaskContinuityConfig, description="Thread-local notes and compacted-source recall")
    memory: MemoryConfig = Field(default_factory=MemoryConfig, description="Memory subsystem configuration")
    knowledge_base: KnowledgeBaseConfig = Field(
        default_factory=KnowledgeBaseConfig,
        description="Provider-agnostic knowledge capability and custom-agent scope-selection configuration",
    )
    agents_api: AgentsApiConfig = Field(default_factory=AgentsApiConfig, description="Custom-agent management API configuration")
    private_workspace: PrivateWorkspaceConfig = Field(default_factory=PrivateWorkspaceConfig, description="Owner-only private workspace switches (the Desk home)")
    momentum_internal: MomentumInternalConfig = Field(default_factory=MomentumInternalConfig, description="Staff-only Team channels and AI Academy for the agency's own workspace")
    momobot_max: MomobotMaxConfig = Field(default_factory=MomobotMaxConfig, description="MomoBot Max, the built-in all-in-one agent for client accounts (off by default)")
    acp_agents: dict[str, ACPAgentConfig] = Field(default_factory=dict, description="ACP-compatible agent configuration")
    subagents: SubagentsAppConfig = Field(default_factory=SubagentsAppConfig, description="Subagent runtime configuration")
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig, description="Guardrail middleware configuration")
    authorization: AuthorizationConfig = Field(default_factory=AuthorizationConfig, description="Fine-grained resource authorization configuration (RBAC and beyond)")
    entitlements: EntitlementConfig = Field(default_factory=EntitlementConfig, description="M4 entitlement gate configuration (paid-mutation allow/deny, usage limits)")
    input_polish: InputPolishConfig = Field(default_factory=InputPolishConfig, description="Pre-send input polishing configuration.")
    suggestions: SuggestionsConfig = Field(default_factory=SuggestionsConfig, description="Follow-up suggestions configuration.")
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig, description="LLM circuit breaker configuration")
    llm_call: LlmCallConfig = Field(default_factory=LlmCallConfig, description="LLM call execution configuration (concurrency / rate shaping)")
    channel_connections: ChannelConnectionsConfig = Field(
        default_factory=ChannelConnectionsConfig,
        description=format_field_description(
            "channel_connections",
            field_doc="User-facing IM channel connection configuration.",
        ),
    )
    loop_detection: LoopDetectionConfig = Field(default_factory=LoopDetectionConfig, description="Loop detection middleware configuration")
    tool_progress: ToolProgressConfig = Field(default_factory=ToolProgressConfig, description="Tool progress state machine middleware configuration")
    verification: VerificationConfig = Field(default_factory=VerificationConfig, description="Subagent result verification (receipts, checklist, judge)")
    read_before_write: ReadBeforeWriteConfig = Field(default_factory=ReadBeforeWriteConfig, description="Read-before-write file gate middleware configuration")
    projects: ProjectsConfig = Field(default_factory=ProjectsConfig, description="User projects configuration (instructions injection, shelf index, trash retention)")
    pii_redaction: PiiRedactionConfig = Field(default_factory=PiiRedactionConfig, description="PII redaction middleware configuration (issue #3190)")
    safety_finish_reason: SafetyFinishReasonConfig = Field(default_factory=SafetyFinishReasonConfig, description="Provider safety-filter finish_reason interception middleware configuration")
    auth: AuthAppConfig = Field(default_factory=AuthAppConfig, description="Authentication configuration (local + OIDC SSO)")
    model_config = ConfigDict(extra="allow")
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig,
        description=format_field_description(
            "database",
            field_doc="Unified database backend for run/feedback metadata (memory, sqlite, or postgres).",
        ),
    )
    run_events: RunEventsConfig = Field(
        default_factory=RunEventsConfig,
        description=format_field_description(
            "run_events",
            field_doc="Run-event store backend (memory for dev, db for production queries, jsonl for lightweight single-node persistence).",
        ),
    )
    agent_storage: AgentStorageConfig = Field(
        default_factory=AgentStorageConfig,
        description=format_field_description(
            "agent_storage",
            field_doc="Custom-agent and managed-subagent definition storage backend ('file' for on-disk layouts, 'db' to share definitions across nodes via SQL).",
        ),
    )
    exec_seats: ExecSeatsConfig = Field(
        default_factory=ExecSeatsConfig,
        description="Background weekly token-budget enforcement for Momentum agent seats (queue item f95)",
    )
    hiring: HiringConfig = Field(
        default_factory=HiringConfig,
        description="Owner-set headcount and org-depth caps for EXECUTIVE.md's autonomous hiring (queue item e12)",
    )
    scheduler: SchedulerConfig = Field(
        default_factory=SchedulerConfig,
        description=format_field_description(
            "scheduler",
            field_doc="Scheduled task runtime configuration (background poller for one-time, cron, and interval agent runs).",
        ),
    )
    mcp_tasks: McpTasksConfig = Field(
        default_factory=McpTasksConfig,
        description=format_field_description(
            "mcp_tasks",
            field_doc="Long-running MCP task persistence and background polling runtime.",
        ),
    )
    subagent_runtime: SubagentRuntimeConfig = Field(
        default_factory=SubagentRuntimeConfig,
        description=format_field_description(
            "subagent_runtime",
            field_doc="Process-local admission and execution capacity shared by ordinary and batch subagents.",
        ),
    )
    subagent_batches: SubagentBatchesConfig = Field(
        default_factory=SubagentBatchesConfig,
        description=format_field_description(
            "subagent_batches",
            field_doc="Durable native-subagent batch scheduling, lease, and recovery configuration.",
        ),
    )
    momobot_brand: MomobotBrandConfig = Field(
        default_factory=MomobotBrandConfig,
        description="Server-side folder holding the private MomoBot About copy and Agents lineup kit (never committed).",
    )
    roster: RosterConfig = Field(
        default_factory=RosterConfig,
        description=format_field_description(
            "roster",
            field_doc="Slack account-manager roster (user -> role -> clients) and the repo allow/deny lists the MomoBot desktop bridge honors.",
        ),
    )
    checkpointer: CheckpointerConfig | None = Field(
        default=None,
        description=format_field_description(
            "checkpointer",
            field_doc="LangGraph state-persistence checkpointer configuration.",
        ),
    )
    stream_bridge: StreamBridgeConfig | None = Field(
        default=None,
        description=format_field_description(
            "stream_bridge",
            field_doc="Stream bridge connecting agent workers to SSE endpoints.",
        ),
    )
    run: RunConfig = Field(default_factory=RunConfig, description=format_field_description("run"))
    run_ownership: RunOwnershipConfig = Field(
        default_factory=RunOwnershipConfig,
        description=format_field_description(
            "run_ownership",
            field_doc="Run ownership and lease configuration for multi-worker deployments.",
        ),
    )
    dedupe_storage: DedupeStorageConfig = Field(
        default_factory=DedupeStorageConfig,
        description=format_field_description(
            "dedupe_storage",
            field_doc="Inbound webhook dedupe storage backend (memory / postgres / auto) for cross-pod redelivery dedup. See issue #4120.",
        ),
    )

    # Name -> config lookup tables, (re)built after validation by
    # ``_build_name_indexes``. They make ``get_model_config`` / ``get_tool_config``
    # / ``get_tool_group_config`` O(1) instead of an O(n) ``next(...)`` scan per
    # call. Private attrs are excluded from serialization.
    _managed_model_names: set[str] = PrivateAttr(default_factory=set)
    _models_by_name: dict[str, ModelConfig] = PrivateAttr(default_factory=dict)
    _tools_by_name: dict[str, ToolConfig] = PrivateAttr(default_factory=dict)
    _tool_groups_by_name: dict[str, ToolGroupConfig] = PrivateAttr(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _drop_null_config_sections(cls, data: Any) -> Any:
        """Treat a present-but-null config section as absent so its default applies.

        Commenting out every entry under a top-level YAML key — e.g. ``models:``
        (a list) or ``memory:`` (an object), with only comments beneath it as
        shipped throughout ``config.example.yaml`` — makes PyYAML parse the value
        as ``None``. Without this, the documented ``cp config.example.yaml
        config.yaml`` first-run flow crashes with an opaque ``Input should be a
        valid list`` / ``valid dictionary`` pydantic error for that section.

        Dropping the ``None`` lets each field fall back to its default: list
        sections become ``[]`` via ``default_factory=list`` and object sections
        get their default config. This generalizes the earlier list-only
        handling to every section that defines a default. The ``database``
        section is independent and still owned by ``_apply_database_defaults``
        (in ``from_file``), which applies concrete defaults beyond null-coercion.
        Required sections without a default (``sandbox``) intentionally still
        error when null — there is nothing to fall back to.
        """
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path:
        """Resolve the config file path.

        Priority:
        1. If provided `config_path` argument, use it.
        2. If provided `DEER_FLOW_CONFIG_PATH` environment variable, use it.
        3. Otherwise, search the caller project root.
        4. Finally, search legacy backend/repository-root defaults for monorepo compatibility.
        """
        if config_path:
            path = Path(config_path)
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by param `config_path` not found at {path}")
            return path
        elif os.getenv("DEER_FLOW_CONFIG_PATH"):
            path = Path(os.getenv("DEER_FLOW_CONFIG_PATH"))
            if not Path.exists(path):
                raise FileNotFoundError(f"Config file specified by environment variable `DEER_FLOW_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("config.yaml",))
            if project_config is not None:
                return project_config

            for path in _legacy_config_candidates():
                if path.exists():
                    return path
            raise FileNotFoundError("`config.yaml` file not found in the project root or legacy backend/repository root locations")

    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load config from YAML file.

        See `resolve_config_path` for more details.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        resolved_path = cls.resolve_config_path(config_path)
        with open(resolved_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # Check config version before processing
        cls._check_config_version(config_data, resolved_path)

        config_data = cls.resolve_env_variables(config_data)
        cls._apply_database_defaults(config_data)

        # Load circuit_breaker config if present
        if "circuit_breaker" in config_data:
            config_data["circuit_breaker"] = config_data["circuit_breaker"]

        # Load extensions config separately (it's in a different file), while
        # preserving any config.yaml-backed extension fields. config.yaml wins
        # when it explicitly declares a field because those values are part of
        # the main AppConfig hot-reload contract.
        yaml_extensions = config_data.get("extensions")
        extensions_config = ExtensionsConfig.from_file()
        extensions_data = extensions_config.model_dump(by_alias=True)
        if isinstance(yaml_extensions, Mapping):
            yaml_extensions_config = ExtensionsConfig.model_validate(yaml_extensions)
            extensions_data.update(yaml_extensions_config.model_dump(by_alias=True, exclude_unset=True))
        config_data["extensions"] = extensions_data

        result = cls.model_validate(config_data)
        if not result.models:
            logger.warning(
                "No models are configured in %s. Add at least one entry under `models:` (see the commented examples in config.example.yaml) or run `make setup`.",
                resolved_path,
            )
        acp_agents = cls._validate_acp_agents(config_data.get("acp_agents", {}))
        cls._apply_singleton_configs(result, acp_agents)
        return result

    @classmethod
    def _validate_acp_agents(
        cls,
        config_data: Mapping[str, Mapping[str, object]] | None,
    ) -> dict[str, ACPAgentConfig]:
        if config_data is None:
            config_data = {}
        return {name: ACPAgentConfig(**cfg) for name, cfg in config_data.items()}

    @classmethod
    def _apply_singleton_configs(cls, config: Self, acp_agents: dict[str, ACPAgentConfig]) -> None:
        from deerflow.config.checkpointer_config import get_checkpointer_config

        previous_checkpointer_config = get_checkpointer_config()

        load_title_config_from_dict(config.title.model_dump())
        load_summarization_config_from_dict(config.summarization.model_dump())
        load_memory_config_from_dict(config.memory.model_dump())
        load_agents_api_config_from_dict(config.agents_api.model_dump())
        load_subagents_config_from_dict(config.subagents.model_dump())
        load_tool_search_config_from_dict(config.tool_search.model_dump())
        load_guardrails_config_from_dict(config.guardrails.model_dump())
        load_authorization_config_from_dict(config.authorization.model_dump())
        load_entitlement_config_from_dict(config.entitlements.model_dump())
        load_checkpointer_config_from_dict(config.checkpointer.model_dump() if config.checkpointer is not None else None)
        load_stream_bridge_config_from_dict(config.stream_bridge.model_dump() if config.stream_bridge is not None else None)
        load_acp_config_from_dict({name: agent.model_dump() for name, agent in acp_agents.items()})

        if previous_checkpointer_config != config.checkpointer:
            # These runtime singletons derive their backend from checkpointer config.
            # Keep imports local to avoid cycles: both providers import get_app_config.
            #
            # The unified ``database`` section is intentionally NOT handled here.
            # ``database`` is a restart-required field (reload_boundary.STARTUP_ONLY_FIELDS):
            # ``init_engine_from_config()`` builds the ORM engine once at startup and
            # never rebuilds it on a config.yaml edit. Resetting only the sync
            # checkpointer/store singletons on a live ``database``/``postgres_schema``
            # change would half-migrate the deployment -- new checkpoint/store tables
            # would land in the new schema while ORM rows keep landing in the old one,
            # with no error surfaced. Requiring the documented restart keeps the
            # deployment self-consistent.
            from deerflow.runtime.checkpointer import reset_checkpointer
            from deerflow.runtime.store import reset_store

            reset_checkpointer()
            reset_store()

    @classmethod
    def _apply_database_defaults(cls, config_data: dict[str, Any]) -> None:
        """Apply config.yaml defaults for persistence when the section is absent."""
        database_config = config_data.get("database")
        if database_config is None:
            database_config = {}
            config_data["database"] = database_config
        if not isinstance(database_config, dict):
            return
        for key, value in CONFIG_FILE_DATABASE_DEFAULTS.items():
            database_config.setdefault(key, value)

    @classmethod
    def _check_config_version(cls, config_data: dict, config_path: Path) -> None:
        """Check if the user's config.yaml is outdated compared to config.example.yaml.

        Emits a warning if the user's config_version is lower than the example's.
        Missing config_version is treated as version 0 (pre-versioning).
        """
        try:
            user_version = int(config_data.get("config_version", 0))
        except (TypeError, ValueError):
            user_version = 0

        # Find config.example.yaml by searching config.yaml's directory and its parents
        example_path = None
        search_dir = config_path.parent
        for _ in range(5):  # search up to 5 levels
            candidate = search_dir / "config.example.yaml"
            if candidate.exists():
                example_path = candidate
                break
            parent = search_dir.parent
            if parent == search_dir:
                break
            search_dir = parent
        if example_path is None:
            return

        try:
            with open(example_path, encoding="utf-8") as f:
                example_data = yaml.safe_load(f)
            raw = example_data.get("config_version", 0) if example_data else 0
            try:
                example_version = int(raw)
            except (TypeError, ValueError):
                example_version = 0
        except Exception:
            return

        if user_version < example_version:
            logger.warning(
                "Your config.yaml (version %d) is outdated — the latest version is %d. Run `make config-upgrade` to merge new fields into your config.",
                user_version,
                example_version,
            )

    @classmethod
    def resolve_env_variables(cls, config: Any) -> Any:
        """Recursively resolve environment variables in the config.

        Environment variables are resolved using the `os.getenv` function. Example: $OPENAI_API_KEY

        Args:
            config: The config to resolve environment variables in.

        Returns:
            The config with environment variables resolved.
        """
        if isinstance(config, str):
            if config.startswith("$"):
                env_value = os.getenv(config[1:])
                if env_value is None:
                    raise ValueError(f"Environment variable {config[1:]} not found for config value {config}")
                return env_value
            return config
        elif isinstance(config, dict):
            return {k: cls.resolve_env_variables(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls.resolve_env_variables(item) for item in config]
        return config

    @model_validator(mode="after")
    def _build_name_indexes(self) -> "AppConfig":
        """Build name -> config lookup tables for O(1) ``get_*_config``.

        ``get_tool_config`` runs 2-3x per community-tool invocation (e.g.
        web_search) and ``get_model_config`` several times per agent build, so
        the previous O(n) ``next(...)`` scans sat on hot paths. Rebuilt here so a
        config reload (which constructs a fresh ``AppConfig``) refreshes them.
        ``setdefault`` keeps the first entry on duplicate names, preserving the
        prior ``next(...)`` first-match semantics.
        """
        models_by_name: dict[str, ModelConfig] = {}
        for model in self.models:
            models_by_name.setdefault(model.name, model)
        tools_by_name: dict[str, ToolConfig] = {}
        for tool in self.tools:
            tools_by_name.setdefault(tool.name, tool)
        tool_groups_by_name: dict[str, ToolGroupConfig] = {}
        for group in self.tool_groups:
            tool_groups_by_name.setdefault(group.name, group)
        self._models_by_name = models_by_name
        self._tools_by_name = tools_by_name
        self._tool_groups_by_name = tool_groups_by_name
        return self

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        return self._models_by_name.get(name)

    def get_tool_config(self, name: str) -> ToolConfig | None:
        """Get the tool config by name.

        Args:
            name: The name of the tool to get the config for.

        Returns:
            The tool config if found, otherwise None.
        """
        return self._tools_by_name.get(name)

    def get_tool_group_config(self, name: str) -> ToolGroupConfig | None:
        """Get the tool group config by name.

        Args:
            name: The name of the tool group to get the config for.

        Returns:
            The tool group config if found, otherwise None.
        """
        return self._tool_groups_by_name.get(name)


# Compatibility singleton layer for code paths that have not yet been
# migrated to explicit ``AppConfig`` threading. New composition roots should
# prefer constructing ``AppConfig`` once and passing it down directly.
_app_config: AppConfig | None = None
_app_config_path: Path | None = None
_app_config_mtime: float | None = None
_app_config_signature: _ConfigSignature | None = None
_app_config_is_custom = False
_current_app_config: ContextVar[AppConfig | None] = ContextVar("deerflow_current_app_config", default=None)
_current_app_config_stack: ContextVar[tuple[AppConfig | None, ...]] = ContextVar("deerflow_current_app_config_stack", default=())


def _get_config_mtime(config_path: Path) -> float | None:
    """Get the modification time of a config file if it exists."""
    try:
        return config_path.stat().st_mtime
    except OSError:
        return None


def _load_and_cache_app_config(config_path: str | None = None) -> AppConfig:
    """Load config from disk and refresh cache metadata."""
    global _app_config, _app_config_path, _app_config_mtime, _app_config_signature, _app_config_is_custom

    resolved_path = AppConfig.resolve_config_path(config_path)
    _app_config = AppConfig.from_file(str(resolved_path))
    _app_config_path = resolved_path
    _app_config_mtime = _get_config_mtime(resolved_path)
    _app_config_signature = _get_config_signature(resolved_path)
    _app_config_is_custom = False
    return _app_config


def get_app_config() -> AppConfig:
    """Get the DeerFlow config instance.

    Returns a cached singleton instance and automatically reloads it when the
    underlying config file path or content signature changes. Use
    `reload_app_config()` to force a reload, or `reset_app_config()` to clear
    the cache.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_signature

    runtime_override = _current_app_config.get()
    if runtime_override is not None:
        return runtime_override

    if _app_config is not None and _app_config_is_custom:
        return _app_config

    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)
    current_signature = _get_config_signature(resolved_path)

    should_reload = _app_config is None or _app_config_path != resolved_path or _app_config_signature != current_signature
    if should_reload:
        if _app_config_path == resolved_path and _app_config_mtime is not None and current_mtime is not None and _app_config_mtime != current_mtime:
            logger.info(
                "Config file has been modified (mtime: %s -> %s), reloading AppConfig",
                _app_config_mtime,
                current_mtime,
            )
        elif _app_config_path == resolved_path and _app_config_signature != current_signature:
            logger.info("Config file content signature changed, reloading AppConfig")
        _load_and_cache_app_config(str(resolved_path))
    from deerflow.config.managed_models import merge_managed_models

    return merge_managed_models(_app_config)


def reload_app_config(config_path: str | None = None) -> AppConfig:
    """Reload the config from file and update the cached instance.

    This is useful when the config file has been modified and you want
    to pick up the changes without restarting the application.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses the default resolution strategy.

    Returns:
        The newly loaded AppConfig instance.
    """
    from deerflow.config.managed_models import merge_managed_models

    return merge_managed_models(_load_and_cache_app_config(config_path))


def reset_app_config() -> None:
    """Reset the cached config instance.

    This clears the singleton cache, causing the next call to
    `get_app_config()` to reload from file. Useful for testing
    or when switching between different configurations.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_signature, _app_config_is_custom
    _app_config = None
    _app_config_path = None
    _app_config_mtime = None
    _app_config_signature = None
    _app_config_is_custom = False


def set_app_config(config: AppConfig) -> None:
    """Set a custom config instance.

    This allows injecting a custom or mock config for testing purposes.

    Args:
        config: The AppConfig instance to use.
    """
    global _app_config, _app_config_path, _app_config_mtime, _app_config_signature, _app_config_is_custom
    _app_config = config
    _app_config_path = None
    _app_config_mtime = None
    _app_config_signature = None
    _app_config_is_custom = True


def peek_current_app_config() -> AppConfig | None:
    """Return the runtime-scoped AppConfig override, if one is active."""
    return _current_app_config.get()


def push_current_app_config(config: AppConfig) -> None:
    """Push a runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    _current_app_config_stack.set(stack + (_current_app_config.get(),))
    _current_app_config.set(config)


def pop_current_app_config() -> None:
    """Pop the latest runtime-scoped AppConfig override for the current execution context."""
    stack = _current_app_config_stack.get()
    if not stack:
        _current_app_config.set(None)
        return
    previous = stack[-1]
    _current_app_config_stack.set(stack[:-1])
    _current_app_config.set(previous)
````

## backend/packages/harness/deerflow/config/paths.py

````python
import hashlib
import logging
import os
import re
import shutil
from pathlib import Path, PureWindowsPath

from deerflow.config.runtime_paths import runtime_home
from deerflow.utils.thread_id import validate_thread_id

# Virtual path prefix seen by agents inside the sandbox
VIRTUAL_PATH_PREFIX = "/mnt/user-data"

_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_SAFE_INTEGRATION_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_UNSAFE_USER_ID_CHAR_RE = re.compile(r"[^A-Za-z0-9_\-]")
_SAFE_USER_ID_DIGEST_HEX_LEN = 16

logger = logging.getLogger(__name__)


def _default_local_base_dir() -> Path:
    """Return the caller project's writable DeerFlow state directory."""
    return runtime_home()


def _validate_thread_id(thread_id: str) -> str:
    """Validate a thread ID before using it in filesystem paths."""
    return validate_thread_id(thread_id)


def _validate_user_id(user_id: str) -> str:
    """Validate a user ID before using it in filesystem paths."""
    if not _SAFE_USER_ID_RE.match(user_id):
        raise ValueError(f"Invalid user_id {user_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return user_id


def _validate_integration_id(integration_id: str) -> str:
    """Validate an integration ID before using it in filesystem paths."""
    if not _SAFE_INTEGRATION_ID_RE.match(integration_id):
        raise ValueError(f"Invalid integration_id {integration_id!r}: only alphanumeric characters, dots, hyphens, and underscores are allowed.")
    # The charset allows dots for names like ``some.integration``; reject the
    # bare ``.``/``..`` path components so a future caller cannot escape the
    # per-integration namespace via ``_join_host_path(..., integration_id, ...)``.
    if integration_id in {".", ".."}:
        raise ValueError(f"Invalid integration_id {integration_id!r}: '.' and '..' are not allowed.")
    return integration_id


def _validate_project_id(project_id: str) -> str:
    """Validate a project ID before using it in filesystem paths."""
    if not _SAFE_USER_ID_RE.match(project_id):
        raise ValueError(f"Invalid project_id {project_id!r}: only alphanumeric characters, hyphens, and underscores are allowed.")
    return project_id


def make_safe_user_id(raw: str) -> str:
    """Normalize an external identity into the user-id charset (``[A-Za-z0-9_-]``).

    IM channel ids (Feishu/Slack/Telegram) may contain characters that
    :func:`_validate_user_id` rejects. Already-safe ids pass through unchanged;
    lossy ones get a short digest suffix so two distinct inputs never share a
    storage bucket.
    """
    if not raw:
        raise ValueError("user_id must be a non-empty string.")
    sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw)
    if sanitized == raw:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _legacy_safe_user_id(raw: str, sanitized: str) -> str:
    """Bucket name produced by the previous (SHA-1) digest revision for ``raw``."""
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:_SAFE_USER_ID_DIGEST_HEX_LEN]
    return f"{sanitized}-{digest}"


def _join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style.

    Docker Desktop on Windows expects bind mount sources to stay in Windows
    path form (for example ``C:\\repo\\backend\\.deer-flow``).  Using
    ``Path(base) / ...`` on a POSIX host can accidentally rewrite those paths
    with mixed separators, so this helper preserves the original style.
    """
    if not parts:
        return base

    if re.match(r"^[A-Za-z]:[\\/]", base) or base.startswith("\\\\") or "\\" in base:
        result = PureWindowsPath(base)
        for part in parts:
            result /= part
        return str(result)

    result = Path(base)
    for part in parts:
        result /= part
    return str(result)


def join_host_path(base: str, *parts: str) -> str:
    """Join host filesystem path segments while preserving native style."""
    return _join_host_path(base, *parts)


class Paths:
    """
    Centralized path configuration for DeerFlow application data.

    Directory layout (host side):
        {base_dir}/
        ├── memory.json
        ├── USER.md          <-- legacy root profile (not used by the profile API)
        ├── users/
        │   └── {user_id}/
        │       ├── USER.md  <-- workspace-scoped profile
        │       └── agents/
        │           └── {agent_name}/
        │               ├── config.yaml
        │               ├── SOUL.md
        │               └── memory.json
        ├── agents/
        │   └── {agent_name}/
        │       ├── config.yaml
        │       ├── SOUL.md  <-- agent personality/identity (injected alongside lead prompt)
        │       └── memory.json
        └── threads/
            └── {thread_id}/
                └── user-data/         <-- mounted as /mnt/user-data/ inside sandbox
                    ├── workspace/     <-- /mnt/user-data/workspace/
                    ├── uploads/       <-- /mnt/user-data/uploads/
                    └── outputs/       <-- /mnt/user-data/outputs/

    BaseDir resolution (in priority order):
        1. Constructor argument `base_dir`
        2. DEER_FLOW_HOME environment variable
        3. Caller project fallback: `{project_root}/.deer-flow`
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    @property
    def host_base_dir(self) -> Path:
        """Host-visible base dir for Docker volume mount sources.

        When running inside Docker with a mounted Docker socket (DooD), the Docker
        daemon runs on the host and resolves mount paths against the host filesystem.
        Set DEER_FLOW_HOST_BASE_DIR to the host-side path that corresponds to this
        container's base_dir so that sandbox container volume mounts work correctly.

        Falls back to base_dir when the env var is not set (native/local execution).
        """
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return Path(env)
        return self.base_dir

    def _host_base_dir_str(self) -> str:
        """Return the host base dir as a raw string for bind mounts."""
        if env := os.getenv("DEER_FLOW_HOST_BASE_DIR"):
            return env
        return str(self.base_dir)

    @property
    def base_dir(self) -> Path:
        """Root directory for all application data."""
        if self._base_dir is not None:
            return self._base_dir

        if env_home := os.getenv("DEER_FLOW_HOME"):
            return Path(env_home).resolve()

        return _default_local_base_dir()

    @property
    def memory_file(self) -> Path:
        """Legacy shared memory file: `{base_dir}/memory.json`.

        New code should use :meth:`user_memory_file`. This path is
        process-global — every user and every workspace resolves to the same
        file — so a write through it is visible to all of them. It remains only
        as a read-side fallback for installations that predate per-user
        memory, mirroring :attr:`agents_dir`.
        """
        return self.base_dir / "memory.json"

    @property
    def user_md_file(self) -> Path:
        """Legacy shared user profile file: `{base_dir}/USER.md`.

        New code should use :meth:`user_md_file_for`. This path is
        process-global — every user and every workspace resolves to the same
        file — so a write through it is visible to all of them. It remains for
        explicit legacy tooling; scoped profile reads must not fall back to it.
        """
        return self.base_dir / "USER.md"

    def user_md_file_for(self, user_id: str) -> Path:
        """Per-user profile file: `{base_dir}/users/{user_id}/USER.md`.

        USER.md is injected into every custom agent, so a shared file lets any
        caller who reaches the agents API rewrite the persona of every other
        user's agents. Isolating it per user applies the same bucket strategy
        :meth:`user_dir` already uses for agents and memory.
        """
        return self.user_dir(user_id) / "USER.md"

    @property
    def agents_dir(self) -> Path:
        """Legacy root for shared (pre user-isolation) custom agents: `{base_dir}/agents/`.

        New code should use :meth:`user_agents_dir` instead. This property remains
        only as a read-side fallback for installations that have not yet run the
        ``migrate_user_isolation.py`` script.
        """
        return self.base_dir / "agents"

    @property
    def managed_subagents_dir(self) -> Path:
        """Deployment-level managed subagent definitions.

        Each definition is stored as its own JSON file so an atomic replace
        never targets a mounted directory or a single shared manifest file.
        """
        return self.base_dir / "managed-subagents"

    def managed_subagent_file(self, name: str) -> Path:
        """Path to one managed subagent definition."""
        return self.managed_subagents_dir / f"{name.lower()}.json"

    def agent_dir(self, name: str) -> Path:
        """Legacy per-agent directory (no user isolation): `{base_dir}/agents/{name}/`."""
        return self.agents_dir / name.lower()

    def agent_memory_file(self, name: str) -> Path:
        """Legacy per-agent memory file: `{base_dir}/agents/{name}/memory.json`.

        New code should use :meth:`user_agent_memory_file`. This path is
        process-global — every user resolves to the same file for a given
        agent name — so a write through it is visible to all of them. It
        remains only as a read-side fallback for installations that predate
        per-user memory, mirroring :attr:`agents_dir`.
        """
        return self.agent_dir(name) / "memory.json"

    def user_dir(self, user_id: str) -> Path:
        """Directory for a specific user: `{base_dir}/users/{user_id}/`."""
        return self.base_dir / "users" / _validate_user_id(user_id)

    def prepare_user_dir_for_raw_id(self, raw_user_id: str) -> str:
        """Return the safe user ID and migrate this ID's legacy unsafe-id bucket.

        A previous branch revision used SHA-1 for unsafe external user IDs.
        New IDs use SHA-256; the legacy bucket name is recomputed from the same
        raw ID, so only this user's own old bucket can ever be moved — a
        different raw ID sharing the sanitized prefix produces a different
        legacy digest and is never touched.
        """
        safe_user_id = make_safe_user_id(raw_user_id)
        sanitized = _UNSAFE_USER_ID_CHAR_RE.sub("-", raw_user_id)
        if safe_user_id == raw_user_id:
            return safe_user_id

        users_dir = self.base_dir / "users"
        target_dir = users_dir / safe_user_id
        legacy_dir = users_dir / _legacy_safe_user_id(raw_user_id, sanitized)
        try:
            if target_dir.exists() or not legacy_dir.is_dir():
                return safe_user_id
            legacy_dir.rename(target_dir)
            logger.info("Migrated legacy unsafe-id user directory to the current digest format")
        except OSError:
            logger.exception("Failed to migrate legacy unsafe-id user directory")
        return safe_user_id

    def user_memory_file(self, user_id: str) -> Path:
        """Per-user memory file: `{base_dir}/users/{user_id}/memory.json`."""
        return self.user_dir(user_id) / "memory.json"

    def user_agents_dir(self, user_id: str) -> Path:
        """Per-user root for that user's custom agents: `{base_dir}/users/{user_id}/agents/`."""
        return self.user_dir(user_id) / "agents"

    def user_agent_dir(self, user_id: str, agent_name: str) -> Path:
        """Per-user per-agent directory: `{base_dir}/users/{user_id}/agents/{name}/`."""
        return self.user_agents_dir(user_id) / agent_name.lower()

    def user_agent_memory_file(self, user_id: str, agent_name: str) -> Path:
        """Per-user per-agent memory: `{base_dir}/users/{user_id}/agents/{name}/memory.json`."""
        return self.user_agent_dir(user_id, agent_name) / "memory.json"

    def user_skills_dir(self, user_id: str) -> Path:
        """Per-user root for that user's custom skills: `{base_dir}/users/{user_id}/skills/`."""
        return self.user_dir(user_id) / "skills"

    def user_custom_skills_dir(self, user_id: str) -> Path:
        """Per-user custom skills directory: `{base_dir}/users/{user_id}/skills/custom/`.

        This is the user-scoped replacement for the global ``{base_dir}/skills/custom/``
        directory. Custom skills are written here; public skills remain under the
        global ``{base_dir}/skills/public/`` (read-only).
        """
        return self.user_skills_dir(user_id) / "custom"

    def integration_skills_dir(self) -> Path:
        """Globally installed managed integration skills.

        Layout: ``{base_dir}/integrations/skills/{provider}/{skill}/``. The
        package contents are shared and read-only; credentials and enabled
        state remain user-scoped elsewhere under ``users/{user_id}``.
        """
        return self.base_dir / "integrations" / "skills"

    @property
    def skills_view_dir(self) -> Path:
        """Global sandbox-visible skills projection: ``{base_dir}/skills_view/``."""
        return self.base_dir / "skills_view"

    @property
    def public_skills_view_dir(self) -> Path:
        """Enabled public skills exposed to sandboxes."""
        return self.skills_view_dir / "public"

    def user_skills_view_dir(self, user_id: str) -> Path:
        """Per-user sandbox-visible skills projection root."""
        return self.user_dir(user_id) / "skills_view"

    def user_custom_skills_view_dir(self, user_id: str) -> Path:
        """Enabled custom skills exposed to one user's sandboxes."""
        return self.user_skills_view_dir(user_id) / "custom"

    def user_legacy_skills_view_dir(self, user_id: str) -> Path:
        """Enabled legacy skills exposed to one user's sandboxes."""
        return self.user_skills_view_dir(user_id) / "legacy"

    def user_integration_skills_view_dir(self, user_id: str) -> Path:
        """Enabled managed integration skills exposed to one user's sandboxes."""
        return self.user_skills_view_dir(user_id) / "integrations"

    def thread_skills_view_dir(self, thread_id: str, *, user_id: str) -> Path:
        """Sandbox-visible skill projection scoped to one user/thread.

        The directory lives below the thread root so ordinary thread deletion
        also removes its policy projection.
        """
        return self.thread_dir(thread_id, user_id=user_id) / "skills_view"

    def host_thread_skills_view_dir(self, thread_id: str, *, user_id: str) -> str:
        """Host path for a thread-scoped skill projection."""
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "skills_view")

    def thread_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for a thread's data.

        When *user_id* is provided:
            `{base_dir}/users/{user_id}/threads/{thread_id}/`
        Otherwise (legacy layout):
            `{base_dir}/threads/{thread_id}/`

        This directory contains a `user-data/` subdirectory that is mounted
        as `/mnt/user-data/` inside the sandbox.

        Raises:
            ValueError: If `thread_id` or `user_id` contains unsafe characters (path
                        separators or `..`) that could cause directory traversal.
        """
        if user_id is not None:
            return self.user_dir(user_id) / "threads" / _validate_thread_id(thread_id)
        return self.base_dir / "threads" / _validate_thread_id(thread_id)

    def sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for the agent's workspace directory.
        Host: `{base_dir}/threads/{thread_id}/user-data/workspace/`
        Sandbox: `/mnt/user-data/workspace/`
        """
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "workspace"

    def sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for user-uploaded files.
        Host: `{base_dir}/threads/{thread_id}/user-data/uploads/`
        Sandbox: `/mnt/user-data/uploads/`
        """
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "uploads"

    def sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for agent-generated artifacts.
        Host: `{base_dir}/threads/{thread_id}/user-data/outputs/`
        Sandbox: `/mnt/user-data/outputs/`
        """
        return self.thread_dir(thread_id, user_id=user_id) / "user-data" / "outputs"

    def user_projects_dir(self, user_id: str) -> Path:
        """Host path root for one user's project shelves: ``users/{user_id}/projects/``."""
        return self.user_dir(user_id) / "projects"

    def user_project_dir(self, user_id: str, project_id: str) -> Path:
        """Host path for one project: ``users/{user_id}/projects/{project_id}/``."""
        return self.user_projects_dir(user_id) / _validate_project_id(project_id)

    def project_documents_dir(self, user_id: str, project_id: str) -> Path:
        """Host path for a project's document shelf.

        Layout (Phase-2 spec §6.2): ``.staging/{uuid}`` for in-flight bytes,
        then one exclusive namespace per row at
        ``{sha256[:2]}/{sha256}/{document_id}/original/{name}`` with an
        optional ``derived/converted.md`` companion.
        """
        return self.user_project_dir(user_id, project_id) / "documents"

    def project_document_path(self, user_id: str, relpath: str) -> Path:
        """Resolve a shelf ``stored_relpath`` to its absolute host path.

        ``stored_relpath`` is stored relative to ``users/{user_id}/projects/``
        (it begins with ``{project_id}/documents/``) so a restore can re-point
        a row without moving bytes. Resolution mirrors
        :meth:`resolve_virtual_path`: join under the user projects root,
        resolve, then re-check confinement — a relpath that escapes the root
        is rejected. Relpaths only ever come from server-generated content
        addresses, never from request text (§12).
        """
        base = self.user_projects_dir(user_id).resolve()
        actual = (base / relpath).resolve()
        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected") from None
        return actual

    def acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for the ACP workspace of a specific thread.
        Host: `{base_dir}/threads/{thread_id}/acp-workspace/`
        Sandbox: `/mnt/acp-workspace/`

        Each thread gets its own isolated ACP workspace so that concurrent
        sessions cannot read each other's ACP agent outputs.
        """
        return self.thread_dir(thread_id, user_id=user_id) / "acp-workspace"

    def sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> Path:
        """
        Host path for the user-data root.
        Host: `{base_dir}/threads/{thread_id}/user-data/`
        Sandbox: `/mnt/user-data/`
        """
        return self.thread_dir(thread_id, user_id=user_id) / "user-data"

    def host_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for a thread directory, preserving Windows path syntax."""
        if user_id is not None:
            return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "threads", _validate_thread_id(thread_id))
        return _join_host_path(self._host_base_dir_str(), "threads", _validate_thread_id(thread_id))

    def host_sandbox_user_data_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for a thread's user-data root."""
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "user-data")

    def host_sandbox_work_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for the workspace mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "workspace")

    def host_sandbox_uploads_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for the uploads mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "uploads")

    def host_sandbox_outputs_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for the outputs mount source."""
        return _join_host_path(self.host_sandbox_user_data_dir(thread_id, user_id=user_id), "outputs")

    def host_acp_workspace_dir(self, thread_id: str, *, user_id: str | None = None) -> str:
        """Host path for the ACP workspace mount source."""
        return _join_host_path(self.host_thread_dir(thread_id, user_id=user_id), "acp-workspace")

    def host_user_custom_skills_dir(self, user_id: str) -> str:
        """Host path for a user's custom skills directory, preserving Windows path syntax."""
        return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "skills", "custom")

    def host_integration_skills_dir(self) -> str:
        """Host path for globally installed managed integration skills."""
        return _join_host_path(self._host_base_dir_str(), "integrations", "skills")

    def host_user_integration_config_dir(self, user_id: str, integration_id: str) -> str:
        """Host path for a user's managed integration runtime config directory."""
        return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "integrations", _validate_integration_id(integration_id), "config")

    def host_user_integration_data_dir(self, user_id: str, integration_id: str) -> str:
        """Host path for a user's managed integration runtime data directory."""
        return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "integrations", _validate_integration_id(integration_id), "data")

    def ensure_thread_dirs(self, thread_id: str, *, user_id: str | None = None) -> None:
        """Create all standard sandbox directories for a thread.

        Directories are created with mode 0o777 so that sandbox containers
        (which may run as a different UID than the host backend process) can
        write to the volume-mounted paths without "Permission denied" errors.
        The explicit chmod() call is necessary because Path.mkdir(mode=...) is
        subject to the process umask and may not yield the intended permissions.

        Includes the ACP workspace directory so it can be volume-mounted into
        the sandbox container at ``/mnt/acp-workspace`` even before the first
        ACP agent invocation.
        """
        for d in [
            self.sandbox_work_dir(thread_id, user_id=user_id),
            self.sandbox_uploads_dir(thread_id, user_id=user_id),
            self.sandbox_outputs_dir(thread_id, user_id=user_id),
            self.acp_workspace_dir(thread_id, user_id=user_id),
        ]:
            d.mkdir(parents=True, exist_ok=True)
            d.chmod(0o777)

    def delete_thread_dir(self, thread_id: str, *, user_id: str | None = None) -> None:
        """Delete all persisted data for a thread.

        The operation is idempotent: missing thread directories are ignored.
        """
        thread_dir = self.thread_dir(thread_id, user_id=user_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)

    def resolve_virtual_path(self, thread_id: str, virtual_path: str, *, user_id: str | None = None) -> Path:
        """Resolve a sandbox virtual path to the actual host filesystem path.

        Args:
            thread_id: The thread ID.
            virtual_path: Virtual path as seen inside the sandbox, e.g.
                          ``/mnt/user-data/outputs/report.pdf``.
                          Leading slashes are stripped before matching.
            user_id: Optional user ID for user-scoped path resolution.

        Returns:
            The resolved absolute host filesystem path.

        Raises:
            ValueError: If the path does not start with the expected virtual
                        prefix or a path-traversal attempt is detected.
        """
        stripped = virtual_path.lstrip("/")
        prefix = VIRTUAL_PATH_PREFIX.lstrip("/")

        # Require an exact segment-boundary match to avoid prefix confusion
        # (e.g. reject paths like "mnt/user-dataX/...").
        if stripped != prefix and not stripped.startswith(prefix + "/"):
            raise ValueError(f"Path must start with /{prefix}")

        relative = stripped[len(prefix) :].lstrip("/")
        base = self.sandbox_user_data_dir(thread_id, user_id=user_id).resolve()
        actual = (base / relative).resolve()

        try:
            actual.relative_to(base)
        except ValueError:
            raise ValueError("Access denied: path traversal detected")

        return actual


# ── Singleton ────────────────────────────────────────────────────────────

_paths: Paths | None = None


def get_paths() -> Paths:
    """Return the global Paths singleton (lazy-initialized)."""
    global _paths
    if _paths is None:
        _paths = Paths()
    return _paths


def resolve_path(path: str) -> Path:
    """Resolve *path* to an absolute ``Path``.

    Relative paths are resolved relative to the application base directory.
    Absolute paths are returned as-is (after normalisation).
    """
    p = Path(path)
    if not p.is_absolute():
        p = get_paths().base_dir / path
    return p.resolve()
````

## backend/app/gateway/deps.py

````python
"""Centralized accessors for singleton objects stored on ``app.state``.

**Getters** (used by routers): raise 503 when a required dependency is
missing, except ``get_store`` which returns ``None``.

``AppConfig`` is intentionally *not* cached on ``app.state``. Routers and the
run path resolve it through :func:`deerflow.config.app_config.get_app_config`,
which performs mtime-based hot reload, so edits to ``config.yaml`` take
effect on the next request without a process restart. The engines created in
:func:`langgraph_runtime` (stream bridge, persistence, checkpointer, store,
run-event store) accept a ``startup_config`` snapshot — they are
restart-required by design and stay bound to that snapshot to keep the live
process consistent with itself.

Initialization is handled directly in ``app.py`` via :class:`AsyncExitStack`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar, cast

from fastapi import FastAPI, HTTPException, Request
from langgraph.types import Checkpointer

from deerflow.community.browser_automation.session import browser_multi_worker_error
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.feedback import FeedbackRepository
from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON, STARTUP_ORPHAN_RECOVERY_ERROR, RunContext, RunManager, StreamBridge
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.runs.store.base import RunStore
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)

# Upper bound (seconds) for draining in-flight runs during shutdown, before the
# AsyncExitStack tears down the checkpointer (and its connection pool). Kept
# local to avoid an app -> deps -> app import cycle. This is a *separate* budget
# from ``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS`` (currently also 5.0s,
# which bounds channel-service stop): the two govern independent teardown steps
# and may diverge, but both count toward the lifespan shutdown window — revisit
# them together if their sum must stay within the server's graceful-shutdown
# timeout.
_RUN_DRAIN_TIMEOUT_SECONDS = 5.0


def _browser_tools_enabled_in_config(config: AppConfig) -> bool:
    """Return whether process-local agentic browser sessions are configured."""
    get_tool_config = getattr(config, "get_tool_config", None)
    if callable(get_tool_config):
        return get_tool_config("browser_navigate") is not None
    return any(getattr(tool, "name", None) == "browser_navigate" for tool in (getattr(config, "tools", None) or []))


def _enforce_postgres_for_multi_worker(config: AppConfig) -> None:
    """Refuse unsafe multi-process configurations before persistence starts.

    Multi-instance scheduler recovery also needs the durable run ownership
    contract even when each Pod runs a single Gateway worker.

    1. The background scheduler must be disabled for ordinary multi-worker
       mode. ``scheduler.multi_instance`` opts into the lease-aware path.
    2. Process-local browser sessions must be disabled. Browser tools keep
       Chromium and Playwright objects in one worker's memory, while ordinary
       uvicorn dispatch provides no thread-id affinity.
    3. The DB backend must be Postgres — SQLite write-locks cannot support
       concurrent multi-process access.
    4. ``run_events.backend`` must be ``db``. Memory and JSONL stores are
       process-local, so workers cannot enforce a shared singleton receipt.
    5. ``run_ownership.heartbeat_enabled`` must be True — without heartbeat,
       every run has a NULL lease, so reconciliation treats all inflight
       runs as orphans and Worker B would kill Worker A's live runs on
       every rolling update or scale-up.

    This gate runs once at startup before any persistence engine is
    initialised so the error message is clear and the process exits
    immediately.
    """
    try:
        workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
    except (TypeError, ValueError):
        workers = 1

    scheduler = getattr(config, "scheduler", None)
    multi_instance_requested = bool(getattr(scheduler, "multi_instance", False))
    multi_instance_scheduler = bool(getattr(scheduler, "enabled", False) and multi_instance_requested)

    backend = getattr(config.database, "backend", None)
    run_events_backend = getattr(getattr(config, "run_events", None), "backend", None)
    run_ownership = getattr(config, "run_ownership", None)

    if multi_instance_requested and backend != "postgres":
        raise SystemExit(f"scheduler.multi_instance=true requires database.backend='postgres'. database.backend is '{backend}'. Set scheduler.multi_instance=false or configure Postgres.")
    if multi_instance_requested and run_events_backend != "db":
        raise SystemExit(f"scheduler.multi_instance=true requires run_events.backend='db'. run_events.backend is '{run_events_backend}'. Set scheduler.multi_instance=false or configure run_events.backend: db.")
    if multi_instance_requested and (run_ownership is None or not run_ownership.heartbeat_enabled):
        raise SystemExit("scheduler.multi_instance=true requires run_ownership.heartbeat_enabled=true so peer runs retain a valid lease. Set scheduler.multi_instance=false or enable run ownership heartbeats.")

    if workers <= 1:
        return

    if config.scheduler.enabled and not multi_instance_scheduler:
        raise SystemExit(f"GATEWAY_WORKERS={workers} cannot run with scheduler.enabled=true because each worker starts its own scheduler. Set GATEWAY_WORKERS=1, scheduler.multi_instance=true, or scheduler.enabled=false.")

    if _browser_tools_enabled_in_config(config):
        raise SystemExit(browser_multi_worker_error(workers))

    if backend != "postgres":
        raise SystemExit(f"GATEWAY_WORKERS={workers} requires database.backend='postgres', but database.backend is '{backend}'. SQLite cannot support concurrent multi-process access. Set GATEWAY_WORKERS=1 or switch to Postgres.")

    if run_events_backend != "db":
        raise SystemExit(
            f"GATEWAY_WORKERS={workers} requires run_events.backend='db', but run_events.backend is '{run_events_backend}'. "
            "Memory and JSONL event stores are process-local, so delivery receipt singleton guarantees cannot hold across workers. "
            "Set GATEWAY_WORKERS=1 or configure run_events.backend: db."
        )

    if run_ownership is None or not run_ownership.heartbeat_enabled:
        raise SystemExit(
            f"GATEWAY_WORKERS={workers} requires run_ownership.heartbeat_enabled=true. "
            "Without heartbeat, every run has a NULL lease, so reconciliation "
            "treats all inflight runs as orphans — Worker B would kill Worker A's "
            "live runs on every rolling update or scale-up. "
            "Set run_ownership.heartbeat_enabled=true in config.yaml."
        )


def _validate_agent_storage(config: AppConfig) -> None:
    """Fail fast on an agent-storage backend the database cannot support.

    ``agent_storage.backend: db`` needs a durable, shared SQL database — a
    ``memory`` database is per-process, so custom-agent and managed-subagent
    definitions would silently diverge across nodes (and there is no SQL URL
    to open). Mirrors deermem's create_storage fail-fast and the multi-worker
    gate above.

    Also warns when a multi-worker Postgres deployment leaves agent storage on
    ``file``: custom agents created on one node's local disk are invisible to
    the others, exactly the divergence the db backend exists to fix.
    """
    agent_storage = getattr(config, "agent_storage", None)
    backend = getattr(agent_storage, "backend", "file")
    db_backend = getattr(getattr(config, "database", None), "backend", None)
    if backend == "db" and db_backend not in ("sqlite", "postgres"):
        raise SystemExit(
            f"agent_storage.backend='db' requires database.backend to be 'sqlite' or 'postgres', "
            f"but database.backend is '{db_backend}'. A 'memory' database is per-process and cannot "
            "share agent definitions across nodes. Set database.backend, or use agent_storage.backend='file'."
        )
    try:
        workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
    except (TypeError, ValueError):
        workers = 1
    if workers > 1 and db_backend == "postgres" and backend == "file":
        logger.warning(
            "GATEWAY_WORKERS=%s with database.backend='postgres' but agent_storage.backend='file': "
            "custom agents and managed subagents are stored per-node on local disk and are not visible "
            "across workers/nodes. Set agent_storage.backend='db' to share them.",
            workers,
        )


async def _drain_inflight_runs(run_manager: RunManager) -> None:
    """Drain in-flight runs before the checkpointer is torn down (issue #3373).

    Shields the (internally-bounded) drain so that even if the lifespan
    coroutine is repeatedly cancelled mid-shutdown — e.g. signal escalation or
    the server's graceful-shutdown timeout — the checkpointer pool is not closed
    while run tasks are still writing checkpoints. Cancellation is remembered
    and propagated only after the already-running drain reaches a safe terminal
    point.
    """
    drain = asyncio.create_task(run_manager.shutdown(timeout=_RUN_DRAIN_TIMEOUT_SECONDS))
    cancellation: asyncio.CancelledError | None = None

    while not drain.done():
        try:
            await asyncio.shield(drain)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except Exception:
            if cancellation is not None:
                logger.exception("In-flight run drain failed after shutdown cancellation")
                raise cancellation
            logger.exception("Failed to drain in-flight runs during shutdown")
            return

    if cancellation is not None:
        try:
            drain.result()
        except Exception:
            logger.exception("In-flight run drain failed after shutdown cancellation")
        raise cancellation

    try:
        drain.result()
    except Exception:
        logger.exception("Failed to drain in-flight runs during shutdown")


async def _publish_recovered_run_stream_end(
    bridge: StreamBridge,
    recovered_runs: list[RunRecord],
    *,
    cleanup_delay: float = 60.0,
    on_cleanup_scheduled: Callable[[str, asyncio.Task[None]], None] | None = None,
) -> list[tuple[str, asyncio.Task[None]]]:
    """Terminate retained streams for runs recovered as orphaned."""
    cleanup_tasks: list[tuple[str, asyncio.Task[None]]] = []
    for record in recovered_runs:
        stream_exists = getattr(bridge, "stream_exists", None)
        if stream_exists is not None:
            try:
                if not await stream_exists(record.run_id):
                    logger.debug("Skipping recovered stream end for %s: stream already expired", record.run_id)
                    continue
            except Exception:
                logger.debug("Failed to check recovered stream existence for %s", record.run_id, exc_info=True)
        try:
            await bridge.publish_end(record.run_id)
        except Exception:
            logger.warning(
                "Failed to publish recovered run stream end for %s",
                record.run_id,
                exc_info=True,
            )
            continue
        task = asyncio.create_task(bridge.cleanup(record.run_id, delay=cleanup_delay))
        task.add_done_callback(lambda task, run_id=record.run_id: _log_recovered_stream_cleanup_result(task, run_id))
        cleanup_tasks.append((record.run_id, task))
        if on_cleanup_scheduled is not None:
            on_cleanup_scheduled(record.run_id, task)
    return cleanup_tasks


def _log_recovered_stream_cleanup_result(task: asyncio.Task[None], run_id: str) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.warning("Failed to clean up recovered run stream for %s", run_id, exc_info=True)


async def _flush_recovered_stream_cleanups(
    bridge: StreamBridge,
    cleanup_tasks: dict[asyncio.Task[None], str],
    *,
    timeout: float = 1.0,
) -> None:
    """Cancel delayed cleanups and delete their streams before bridge shutdown."""
    pending = [(task, run_id) for task, run_id in cleanup_tasks.items() if not task.done()]
    if not pending:
        return
    for task, _run_id in pending:
        task.cancel()
    await asyncio.gather(*(task for task, _run_id in pending), return_exceptions=True)

    run_ids = list(dict.fromkeys(run_id for _task, run_id in pending))
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(bridge.cleanup(run_id, delay=0) for run_id in run_ids),
                return_exceptions=True,
            ),
            timeout=max(0.0, timeout),
        )
    except TimeoutError:
        logger.warning(
            "Immediate recovered stream cleanup exceeded %.1fs for run_ids=%s; bridge TTL remains the final safety net",
            timeout,
            run_ids,
        )
    else:
        for run_id, result in zip(run_ids, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to immediately clean up recovered run stream for %s: %r",
                    run_id,
                    result,
                )


if TYPE_CHECKING:
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.thread_meta.base import ThreadMetaStore
    from deerflow.runtime import RunRecord


T = TypeVar("T")


async def _mark_latest_startup_recovered_threads_error(
    run_manager: RunManager,
    thread_store: ThreadMetaStore,
    recovered_runs: list[RunRecord],
) -> None:
    """Project startup recovery before request-serving concurrency begins.

    This helper must remain on the pre-``yield`` startup path. ``ThreadMetaStore``
    has no ``latest_run_id`` column, so it cannot express an atomic conditional
    update keyed by the recovered run. Periodic recovery deliberately skips this
    projection; moving this helper after request serving starts would reintroduce
    a read/update race with newer runs.
    """
    recovered_by_thread: dict[str, set[str]] = {}
    for record in recovered_runs:
        recovered_by_thread.setdefault(record.thread_id, set()).add(record.run_id)

    for thread_id, recovered_run_ids in recovered_by_thread.items():
        try:
            latest_runs = await run_manager.list_by_thread(thread_id, user_id=None, limit=1)
        except Exception:
            logger.warning("Failed to find latest run for thread %s during run reconciliation", thread_id, exc_info=True)
            continue
        if not latest_runs or latest_runs[0].run_id not in recovered_run_ids:
            continue
        try:
            await thread_store.update_status(thread_id, "error", user_id=None)
        except Exception:
            logger.warning("Failed to mark thread %s as error during run reconciliation", thread_id, exc_info=True)


async def _terminalize_recovered_runs(
    bridge: StreamBridge,
    recovered_runs: list[RunRecord],
    *,
    cleanup_delay: float,
    on_cleanup_scheduled: Callable[[str, asyncio.Task[None]], None] | None = None,
) -> list[tuple[str, asyncio.Task[None]]]:
    """Publish terminal markers and schedule retained-stream cleanup."""
    return await _publish_recovered_run_stream_end(
        bridge,
        recovered_runs,
        cleanup_delay=cleanup_delay,
        on_cleanup_scheduled=on_cleanup_scheduled,
    )


def get_config() -> AppConfig:
    """Return the freshest ``AppConfig`` for the current request.

    Routes through :func:`deerflow.config.app_config.get_app_config`, which
    honours runtime ``ContextVar`` overrides and reloads ``config.yaml`` from
    disk when its mtime changes. ``AppConfig`` is not cached on ``app.state``
    at all — the only startup-time snapshot lives as a local
    ``startup_config`` variable inside ``lifespan()`` and is passed
    explicitly into :func:`langgraph_runtime` for the engines that are
    restart-required by design. Routing every request through
    :func:`get_app_config` closes the bytedance/deer-flow issue #3107 BUG-001
    split-brain where the worker / lead-agent thread saw a stale startup
    snapshot.

    Hot-reload boundary: fields backed by startup-time singletons
    (engines, sandbox provider, IM channels, logging handler) require a
    process restart to change at runtime. The authoritative list lives in
    :mod:`deerflow.config.reload_boundary` and is mirrored by the
    standardised ``"startup-only:"`` prefix on the matching
    ``Field(description=...)`` in :class:`AppConfig` — IDE hover on those
    fields will surface the boundary inline. See
    ``backend/CLAUDE.md`` "Config Hot-Reload Boundary" for the operator
    summary.

    Any failure to materialise the config (missing file, permission denied,
    YAML parse error, validation error) is reported as 503 — semantically
    "the gateway cannot serve requests without a usable configuration" — and
    logged with the original exception so operators have something to debug.
    """
    try:
        return get_app_config()
    except Exception as exc:  # noqa: BLE001 - request boundary: log and degrade gracefully
        logger.exception("Failed to load AppConfig at request time")
        raise HTTPException(status_code=503, detail="Configuration not available") from exc


@asynccontextmanager
async def langgraph_runtime(app: FastAPI, startup_config: AppConfig) -> AsyncGenerator[None, None]:
    """Bootstrap and tear down all LangGraph runtime singletons.

    ``startup_config`` is the ``AppConfig`` snapshot taken once during
    ``lifespan()`` for one-shot infrastructure bootstrap. The engines and
    stores constructed here (stream bridge, persistence engine, checkpointer,
    store, run-event store) are restart-required by design — they hold live
    connections, file handles, or singleton providers — so they bind to this
    snapshot and survive across `config.yaml` edits. Request-time consumers
    must still go through :func:`get_config` for any field that should be
    hot-reloadable. See ``backend/CLAUDE.md`` "Config Hot-Reload Boundary".

    The matching ``run_events_config`` is frozen onto ``app.state`` so
    :func:`get_run_context` pairs a freshly-loaded ``AppConfig`` with the
    *startup-time* run-events configuration the underlying ``event_store``
    was built from — otherwise the runtime could end up combining a live
    new ``run_events_config`` with an event store still bound to the
    previous backend.

    Usage in ``app.py``::

        async with langgraph_runtime(app, startup_config):
            yield
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.runtime import make_store, make_stream_bridge
    from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode, freeze_checkpoint_snapshot_frequency
    from deerflow.runtime.checkpointer.async_provider import make_checkpointer
    from deerflow.runtime.events.store import make_run_event_store

    # ------------------------------------------------------------------
    # Multi-worker safety gate: reject SQLite when GATEWAY_WORKERS > 1.
    # SQLite write-locks cannot support concurrent multi-process access.
    # ------------------------------------------------------------------
    _enforce_postgres_for_multi_worker(startup_config)
    # Reject agent_storage.backend='db' on a non-durable database, and warn on
    # node-divergent file storage under multi-worker Postgres.
    _validate_agent_storage(startup_config)

    async with AsyncExitStack() as stack:
        # Lifecycle and system-model hooks can originate on isolated subagent
        # loops. Bind them to the Gateway's serving loop before any runtime
        # dependency starts, then reset the binding last through the exit
        # stack. Registering the callback synchronously here also covers every
        # startup-failure and cancellation path below.
        try:
            from deerflow.extensions.notify import (
                reset_extension_notify_loop,
                set_extension_notify_loop,
            )

            set_extension_notify_loop(asyncio.get_running_loop())
        except Exception:
            logger.exception("Failed to register the extension notify loop; sync observations will be dropped")
        else:

            def reset_notify_loop_safely() -> None:
                try:
                    reset_extension_notify_loop()
                except Exception:
                    logger.debug(
                        "Failed to reset the extension notify loop (non-fatal)",
                        exc_info=True,
                    )

            stack.callback(reset_notify_loop_safely)

        config = startup_config
        app.state.checkpoint_channel_mode = freeze_checkpoint_channel_mode(config.database.checkpoint_channel_mode)
        app.state.checkpoint_snapshot_frequency = freeze_checkpoint_snapshot_frequency(config.database.checkpoint_delta.snapshot_frequency)

        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge(config))

        # Initialize persistence engine BEFORE checkpointer so that
        # auto-create-database logic runs first (postgres backend).
        # Own cleanup before initialization so partial startup and host
        # cancellation cannot strand an engine created along the way.
        stack.push_async_callback(close_engine)
        await init_engine_from_config(config.database)

        app.state.checkpointer = await stack.enter_async_context(make_checkpointer(config))
        app.state.store = await stack.enter_async_context(make_store(config))

        # Record the checkpointer/Store backend selected from this startup
        # snapshot so GET /health/ready probes what the running process
        # actually uses. These singletons are restart-required by design and
        # are never rebuilt on config.yaml hot reload, so the probe must not
        # re-resolve process-wide configuration per request.
        from app.gateway.health import READINESS_CHECKPOINTER_CONFIG_ATTR, resolve_checkpointer_config

        setattr(app.state, READINESS_CHECKPOINTER_CONFIG_ATTR, resolve_checkpointer_config(config))

        # Initialize repositories — one get_session_factory() call for all.
        sf = get_session_factory()
        if sf is not None:
            from deerflow.persistence.audit_events import AuditEventRepository
            from deerflow.persistence.feedback import FeedbackRepository
            from deerflow.persistence.personal_access_tokens import PersonalAccessTokenRepository
            from deerflow.persistence.run import RunRepository
            from deerflow.persistence.user_mfa import UserMfaRepository

            app.state.run_store = RunRepository(sf)
            app.state.feedback_repo = FeedbackRepository(sf)
            app.state.audit_repo = AuditEventRepository(sf)
            app.state.mfa_repo = UserMfaRepository(sf)
            from app.gateway.auth.pat import PAT_LAST_USED_WRITE_INTERVAL_SECONDS

            app.state.pat_repo = PersonalAccessTokenRepository(sf, last_used_write_interval_seconds=PAT_LAST_USED_WRITE_INTERVAL_SECONDS)
        else:
            from deerflow.runtime.runs.store.memory import MemoryRunStore

            app.state.run_store = MemoryRunStore()
            app.state.feedback_repo = None
            app.state.audit_repo = None
            # Memory backend has no durable PAT / MFA store, so Bearer
            # credentials cannot be validated and MFA cannot be enrolled;
            # both are rejected explicitly rather than silently no-oping.
            app.state.pat_repo = None
            app.state.mfa_repo = None

        # Evidence readers are available to Gateway-lifetime extension services,
        # so the configured event store must exist before those services start.
        run_events_config = getattr(config, "run_events", None)
        app.state.run_events_config = run_events_config
        app.state.run_event_store = make_run_event_store(run_events_config)

        from deerflow.extensions.run_evidence import StoreRunEvidenceReader

        # Gateway-lifetime services are trusted operator extensions without a
        # request principal. None deliberately binds this app-scoped reader to
        # global, cross-user visibility; event content is not secret-redacted.
        app.state.run_evidence_reader = StoreRunEvidenceReader(
            app.state.run_store,
            app.state.run_event_store,
            user_id=None,
        )

        # Services are app-scoped. Capture this app's immutable extension set
        # once and close over the same object for teardown; the process-wide
        # singleton may be replaced by another app/test before shutdown.
        from deerflow.extensions import EMPTY_EXTENSIONS, record_runtime_diagnostics
        from deerflow.extensions.gateway import start_services, stop_services

        extensions = getattr(app.state, "extensions", EMPTY_EXTENSIONS)
        attempted_services: list[tuple[str, Any]] = []

        async def stop_extension_services() -> None:
            record_runtime_diagnostics(
                await await_drained(
                    stop_services(
                        extensions,
                        service_entries=attempted_services,
                    )
                )
            )

        # Register cleanup before starting: start() can partially acquire
        # resources and then fail or be cancelled.
        stack.push_async_callback(stop_extension_services)
        record_runtime_diagnostics(
            await start_services(
                extensions,
                config,
                sf,
                run_evidence_reader=app.state.run_evidence_reader,
                attempted_services=attempted_services,
            )
        )

        from deerflow.persistence.thread_meta import make_thread_store

        app.state.thread_store = make_thread_store(sf, app.state.store)
        if sf is not None:
            from deerflow.persistence.academy import AcademyProgressRepository
            from deerflow.persistence.agent_room import AgentRoomRepository
            from deerflow.persistence.approvals import PendingActionRepository
            from deerflow.persistence.board import BoardRepository
            from deerflow.persistence.clients import ClientRepository
            from deerflow.persistence.entitlements import EntitlementRepository
            from deerflow.persistence.fleet import FleetBindingRepository
            from deerflow.persistence.mcp_tasks import McpTaskRepository
            from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
            from deerflow.persistence.scheduled_task_runs import (
                ScheduledTaskRunRepository,
            )
            from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
            from deerflow.persistence.subagent_batches import SubagentBatchRepository
            from deerflow.persistence.team_board import TeamBoardRepository

            app.state.project_repo = ProjectRepository(sf)
            app.state.project_document_repo = ProjectDocumentRepository(sf)
            app.state.client_repo = ClientRepository(sf)
            app.state.board_repo = BoardRepository(sf)
            app.state.team_board_repo = TeamBoardRepository(sf)
            app.state.agent_room_repo = AgentRoomRepository(sf)
            app.state.entitlement_repo = EntitlementRepository(sf)
            app.state.academy_progress_repo = AcademyProgressRepository(sf)
            app.state.fleet_binding_repo = FleetBindingRepository(sf)
            app.state.pending_action_repo = PendingActionRepository(sf)
            app.state.scheduled_task_repo = ScheduledTaskRepository(
                sf,
                run_repository=app.state.run_store,
            )
            app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(
                sf,
                run_repository=app.state.run_store,
            )
            app.state.mcp_task_repo = McpTaskRepository(sf)
            app.state.subagent_batch_repo = SubagentBatchRepository(sf)
        else:
            app.state.mcp_task_repo = None
            app.state.project_repo = None
            app.state.project_document_repo = None
            app.state.client_repo = None
            app.state.board_repo = None
            app.state.team_board_repo = None
            app.state.agent_room_repo = None
            app.state.entitlement_repo = None
            app.state.academy_progress_repo = None
            app.state.pending_action_repo = None
            app.state.subagent_batch_repo = None
            app.state.scheduled_task_repo = None
            app.state.scheduled_task_run_repo = None

        # RunManager with store backing for persistence
        run_ownership_config = getattr(config, "run_ownership", None)
        sb_config = getattr(config, "stream_bridge", None)
        cleanup_delay = getattr(sb_config, "recovered_stream_cleanup_delay_seconds", 60.0) if sb_config else 60.0
        recovered_stream_cleanup_tasks: dict[asyncio.Task[None], str] = {}

        def track_recovered_stream_cleanup(
            run_id: str,
            task: asyncio.Task[None],
        ) -> None:
            recovered_stream_cleanup_tasks[task] = run_id
            task.add_done_callback(lambda completed: recovered_stream_cleanup_tasks.pop(completed, None))

        async def terminalize_recovered_runs(recovered_runs: list[RunRecord]) -> None:
            await _terminalize_recovered_runs(
                app.state.stream_bridge,
                recovered_runs,
                cleanup_delay=cleanup_delay,
                on_cleanup_scheduled=track_recovered_stream_cleanup,
            )

        app.state.run_manager = RunManager(
            store=app.state.run_store,
            run_ownership_config=run_ownership_config,
            run_config=getattr(config, "run", None),
            on_unstarted_limit=app.state.stream_bridge.publish_end,
            event_store=app.state.run_event_store,
            on_orphans_recovered=terminalize_recovered_runs,
        )
        # Startup recovery: mark inflight runs whose lease has expired as error.
        # In single-worker mode (SQLite / backend=memory), no run has a lease, so
        # all inflight rows are reclaimed (unchanged behaviour). In multi-worker
        # mode (Postgres), only runs with an expired lease are reclaimed; runs
        # owned by another live worker are skipped.
        from deerflow.utils.time import now_iso

        recovered_runs = await app.state.run_manager.reconcile_orphaned_inflight_runs(
            error=STARTUP_ORPHAN_RECOVERY_ERROR,
            before=now_iso(),
            stop_reason=ORPHAN_RECOVERY_STOP_REASON,
        )
        await _terminalize_recovered_runs(
            app.state.stream_bridge,
            recovered_runs,
            cleanup_delay=cleanup_delay,
            on_cleanup_scheduled=track_recovered_stream_cleanup,
        )
        await _mark_latest_startup_recovered_threads_error(
            app.state.run_manager,
            app.state.thread_store,
            recovered_runs,
        )

        # Start the lease heartbeat if enabled (multi-worker deployments).
        await app.state.run_manager.start_heartbeat()

        try:
            yield
        finally:
            # Drain in-flight run tasks BEFORE the AsyncExitStack tears down the
            # checkpointer (and its connection pool). A run still mid-graph would
            # otherwise leak into asyncio.run() shutdown, where langgraph's
            # _checkpointer_put_after_previous aput races the closed pool and
            # raises PoolClosed (issue #3373).
            run_manager = getattr(app.state, "run_manager", None)
            if run_manager is not None:
                shutdown_deadline = asyncio.get_running_loop().time() + _RUN_DRAIN_TIMEOUT_SECONDS
                try:
                    await _drain_inflight_runs(run_manager)
                finally:
                    await _flush_recovered_stream_cleanups(
                        app.state.stream_bridge,
                        recovered_stream_cleanup_tasks,
                        timeout=min(
                            1.0,
                            max(
                                0.0,
                                shutdown_deadline - asyncio.get_running_loop().time(),
                            ),
                        ),
                    )


# ---------------------------------------------------------------------------
# Getters – called by routers per-request
# ---------------------------------------------------------------------------


def _require(attr: str, label: str) -> Callable[[Request], T]:
    """Create a FastAPI dependency that returns ``app.state.<attr>`` or 503."""

    def dep(request: Request) -> T:
        val = getattr(request.app.state, attr, None)
        if val is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return cast(T, val)

    dep.__name__ = dep.__qualname__ = f"get_{attr}"
    return dep


get_stream_bridge: Callable[[Request], StreamBridge] = _require("stream_bridge", "Stream bridge")
get_run_manager: Callable[[Request], RunManager] = _require("run_manager", "Run manager")
get_checkpointer: Callable[[Request], Checkpointer] = _require("checkpointer", "Checkpointer")
get_run_event_store: Callable[[Request], RunEventStore] = _require("run_event_store", "Run event store")
get_feedback_repo: Callable[[Request], FeedbackRepository] = _require("feedback_repo", "Feedback")
get_run_store: Callable[[Request], RunStore] = _require("run_store", "Run store")
get_project_repo = _require("project_repo", "Projects")
get_project_document_repo = _require("project_document_repo", "Projects")
get_client_repo = _require("client_repo", "Clients")
get_board_repo = _require("board_repo", "Board")
get_team_board_repo = _require("team_board_repo", "Team board")
get_entitlement_repo = _require("entitlement_repo", "Entitlement")
get_academy_progress_repo = _require("academy_progress_repo", "Academy")
get_fleet_binding_repo = _require("fleet_binding_repo", "Fleet")
get_pending_action_repo = _require("pending_action_repo", "Approvals")


def get_store(request: Request):
    """Return the global store (may be ``None`` if not configured)."""
    return getattr(request.app.state, "store", None)


def get_thread_store(request: Request) -> ThreadMetaStore:
    """Return the thread metadata store (SQL or memory-backed)."""
    val = getattr(request.app.state, "thread_store", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Thread metadata store not available")
    return val


def get_scheduled_task_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task repo not available")
    return val


def get_scheduled_task_run_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_run_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task run repo not available")
    return val


def get_scheduled_task_service(request: Request):
    val = getattr(request.app.state, "scheduled_task_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task service not available")
    return val


def get_mcp_task_repo(request: Request):
    val = getattr(request.app.state, "mcp_task_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="MCP task repo not available")
    return val


def get_mcp_task_service(request: Request):
    val = getattr(request.app.state, "mcp_task_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="MCP task service not available")
    return val


def get_subagent_batch_repo(request: Request):
    val = getattr(request.app.state, "subagent_batch_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Subagent batch repository not available")
    return val


def get_subagent_batch_service(request: Request):
    val = getattr(request.app.state, "subagent_batch_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Subagent batch service not available")
    return val


def get_agent_room_repo(request: Request):
    val = getattr(request.app.state, "agent_room_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Agent Room repository not available")
    return val


def get_run_context(request: Request) -> RunContext:
    """Build a :class:`RunContext` from ``app.state`` singletons.

    Returns a *base* context with infrastructure dependencies. The
    ``app_config`` field is resolved live so per-run fields (e.g.
    ``models[*].max_tokens``) follow ``config.yaml`` edits; the
    ``event_store`` / ``run_events_config`` pair stays frozen to the snapshot
    captured in :func:`langgraph_runtime` so callers never see a store bound to
    one backend paired with a config pointing at another.
    """
    return RunContext(
        checkpointer=get_checkpointer(request),
        store=get_store(request),
        event_store=get_run_event_store(request),
        run_events_config=getattr(request.app.state, "run_events_config", None),
        checkpoint_channel_mode=getattr(request.app.state, "checkpoint_channel_mode", "full"),
        checkpoint_snapshot_frequency=getattr(request.app.state, "checkpoint_snapshot_frequency", None),
        thread_store=get_thread_store(request),
        mcp_task_repo=getattr(request.app.state, "mcp_task_repo", None),
        app_config=get_config(),
        extensions=getattr(request.app.state, "extensions", None),
        on_run_completed=getattr(request.app.state, "scheduled_task_service", None).handle_run_completion if getattr(request.app.state, "scheduled_task_service", None) is not None else None,
    )


# ---------------------------------------------------------------------------
# Auth helpers (used by authz.py and auth middleware)
# ---------------------------------------------------------------------------

# Cached singletons to avoid repeated instantiation per request
_cached_local_provider: LocalAuthProvider | None = None
_cached_repo: SQLiteUserRepository | None = None


def get_local_provider() -> LocalAuthProvider:
    """Get or create the cached LocalAuthProvider singleton.

    Must be called after ``init_engine_from_config()`` — the shared
    session factory is required to construct the user repository.
    """
    global _cached_local_provider, _cached_repo
    if _cached_repo is None:
        from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
        from deerflow.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("get_local_provider() called before init_engine_from_config(); cannot access users table")
        _cached_repo = SQLiteUserRepository(sf)
    if _cached_local_provider is None:
        from app.gateway.auth.local_provider import LocalAuthProvider

        _cached_local_provider = LocalAuthProvider(repository=_cached_repo)
    return _cached_local_provider


def get_audit_repo(request: Request):
    """Return the audit event repository, or raise 503 when unavailable.

    For the admin read endpoint (``GET /api/admin/audit-events``), which
    cannot serve anything meaningful without a durable store. Call sites that
    only *write* an audit row should use :func:`record_audit_event` instead,
    which no-ops rather than failing the action being audited.
    """
    audit_repo = getattr(request.app.state, "audit_repo", None)
    if audit_repo is None:
        raise HTTPException(status_code=503, detail="Audit log requires a configured database")
    return audit_repo


def audit_actor_id(request: Request) -> str | None:
    """Best-effort acting-user id for an audit row, from ``request.state.user``.

    Reads the identity ``AuthMiddleware`` already stamped rather than calling
    :func:`get_current_user_from_request` again: that function also accepts a
    bare cookie with no ``request.state`` set up (the "middleware-less test
    composition" case its own docstring describes), which several existing
    router-level tests exercise with a minimal fake ``Request`` that has no
    ``.cookies`` at all. Returns ``None`` on that same fallback path, which
    only means the audit row's ``actor_user_id`` is left blank.
    """
    # Handlers called directly (blocking-I/O tests) may pass request=None.
    user = getattr(getattr(request, "state", None), "user", None)
    user_id = getattr(user, "id", None)
    return str(user_id) if user_id is not None else None


async def record_audit_event(request: Request, **kwargs: Any) -> None:
    """Best-effort one-line audit call for routers.

    No-ops when the audit repo is unavailable (memory backend), and also
    when *request* carries no real ``app`` (several router-level tests in
    this codebase call an endpoint function directly against a lightweight
    fake ``Request``, matching the pattern ``test_mcp_config_secrets.py``
    uses for other admin routes). The repository's own ``record()`` already
    swallows and logs any write failure; catching broadly here extends that
    same "never break the audited action" guarantee to a malformed caller.
    """
    try:
        audit_repo = request.app.state.audit_repo
    except Exception:
        return
    if audit_repo is not None:
        await audit_repo.record(**kwargs)


def get_pat_repo(request: Request):
    """Return the personal-access-token repository from app state.

    Raises 503 when the process runs on the memory backend (no durable PAT
    storage), so PAT management routes fail explicitly instead of silently
    accepting tokens nobody can validate.
    """
    pat_repo = getattr(request.app.state, "pat_repo", None)
    if pat_repo is None:
        raise HTTPException(status_code=503, detail="Personal access tokens require a configured database")
    return pat_repo


def get_mfa_repo(request: Request):
    """Return the two-factor-authentication repository from app state.

    Raises 503 on the memory backend (no durable MFA storage), so enroll /
    confirm / disable routes fail explicitly instead of silently accepting
    an enrollment nobody could ever complete. The login path itself reads
    ``request.app.state.mfa_repo`` directly and treats ``None`` as "nobody
    has MFA enabled" -- a missing repo there must not break plain password
    login, since without durable storage no enrollment could ever have
    succeeded in the first place.
    """
    mfa_repo = getattr(request.app.state, "mfa_repo", None)
    if mfa_repo is None:
        raise HTTPException(status_code=503, detail="Two-factor authentication requires a configured database")
    return mfa_repo


async def get_current_user_from_request(request: Request):
    """Get the current authenticated user from the request cookie.

    Raises HTTPException 401 if not authenticated.
    """
    state = getattr(request, "state", None)
    state_user = getattr(state, "user", None)
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_PAT, AUTH_SOURCE_SESSION

    if state_user is not None and getattr(state, "auth_source", None) in {
        AUTH_SOURCE_SESSION,
        AUTH_SOURCE_AUTH_DISABLED,
        AUTH_SOURCE_INTERNAL,
        AUTH_SOURCE_PAT,
    }:
        return state_user

    from app.gateway.auth import decode_token
    from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError, token_error_to_code
    from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME

    access_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.NOT_AUTHENTICATED, message="Not authenticated").model_dump(),
        )

    payload = decode_token(access_token)
    if isinstance(payload, TokenError):
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=token_error_to_code(payload), message=f"Token error: {payload.value}").model_dump(),
        )

    provider = get_local_provider()
    user = await provider.get_user(payload.sub)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.USER_NOT_FOUND, message="User not found").model_dump(),
        )

    # Token version mismatch → password was changed, token is stale, or an
    # admin forced a logout by bumping token_version directly.
    if user.token_version != payload.ver:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.TOKEN_INVALID, message="Token revoked (password changed)").model_dump(),
        )

    # getattr, not a direct attribute access: several existing tests build a
    # minimal user double (SimpleNamespace) that predates this field.
    if getattr(user, "disabled_at", None) is not None:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.USER_DISABLED, message="This account has been disabled").model_dump(),
        )

    return user


async def is_admin_user(request: Request) -> bool:
    """Return whether the authenticated caller is an admin user.

    ``AuthMiddleware`` normally stamps ``request.state.user`` before the request
    reaches a router. Falling back to the strict dependency keeps the route safe
    in tests or alternative ASGI compositions that mount a router without the
    global middleware.

    Centralising this here means a future change to the admin definition (e.g.
    allowing an internal system role, adding audit logging, or switching to a
    permission-based check) lands in one place instead of drifting across the
    per-router copies that previously existed in ``mcp``, ``channel_connections``
    and ``channels``.
    """
    # PAT credentials never carry admin capability: no scope in the PAT
    # universe grants it, so an admin's automation token must not unlock
    # admin-only routes (skill installs, integration credentials, MCP config).
    from app.gateway.auth_disabled import AUTH_SOURCE_PAT

    if getattr(request.state, "auth_source", None) == AUTH_SOURCE_PAT:
        return False
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user_from_request(request)

    return getattr(user, "system_role", None) == "admin"


async def require_admin_user(request: Request, *, detail: str) -> None:
    """Require the authenticated caller to be an admin user.

    ``detail`` is the route-specific 403 message. The shared predicate keeps
    read-side redaction and write authorization on the same admin definition.
    """

    if not await is_admin_user(request):
        raise HTTPException(status_code=403, detail=detail)


async def get_optional_user_from_request(request: Request):
    """Get optional authenticated user from request.

    Returns None if not authenticated.
    """
    try:
        return await get_current_user_from_request(request)
    except HTTPException:
        return None


async def get_current_user(request: Request) -> str | None:
    """Return the verified content owner for repository and run filters.

    Account and credential callers use ``get_current_user_from_request`` to
    retain the authenticated person's identity.
    """
    user = await get_optional_user_from_request(request)
    if user is None:
        return None
    return str(getattr(request.state, "storage_user_id", None) or user.id)


async def get_current_actor_user_id(request: Request) -> str | None:
    """Return the person for per-user feedback, independent of workspace."""
    user = await get_optional_user_from_request(request)
    return str(user.id) if user else None
````

## backend/packages/harness/deerflow/persistence/projects/sql.py

````python
"""SQLAlchemy-backed project repositories.

Ownership discipline mirrors ``ThreadMetaRepository``: every method resolves
the caller via ``resolve_user_id(..., AUTO)`` and filters by ``user_id``;
a foreign project/document is indistinguishable from a missing one (callers
map ``None``/``False`` to 404). ``delete`` runs the membership-clearing
transaction from RFC v2 §5.1 plus the Phase-2 shelf-trash statement (§8.1):
every active ``project_documents`` row is moved to trash — with a
``trash_origin`` snapshot — inside the same transaction and row lock, so a
deleted project never leaves an active shelf row behind. No filesystem work
happens in either repository: shelf bytes are immutable, hash-qualified, and
owned by the document row's exclusive namespace, so trash and project delete
are pure row transitions.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.organizations.resolution import organization_from_owned_parent, private_organization_for_user
from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_organization_id, resolve_user_id
from deerflow.utils.file_io import await_drained
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

ProjectStatus = Literal["active", "archived"]


class _UnsetClientId:
    __slots__ = ()


_UNSET_CLIENT_ID = _UnsetClientId()


class ProjectNotAssignableError(ValueError):
    """Raised when a thread cannot be assigned to a project.

    The project is missing, foreign to the caller, or archived — the
    atomicity rules (RFC v2 §5.2) make these indistinguishable inside the
    mutating statement, so callers get one signal and map it to 404 (explicit
    API) or a dropped key (run admission).
    """


class ProjectRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        name: str,
        client_id: str | None = None,
        instructions: str = "",
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.create")
        now = datetime.now(UTC)
        row = ProjectRow(
            id=uuid.uuid4().hex,
            user_id=resolved_user_id,
            name=name,
            client_id=client_id,
            instructions=instructions,
            presentation=presentation or {},
            status="active",
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            row.organization_id = await private_organization_for_user(session, resolved_user_id)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.get")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            if resolved_organization_id is not None and row.organization_id != resolved_organization_id:
                return None
            return self._row_to_dict(row)

    async def list(
        self,
        *,
        status: ProjectStatus | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.list")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectRow).order_by(ProjectRow.created_at.asc(), ProjectRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectRow.organization_id == resolved_organization_id)
        if status is not None:
            stmt = stmt.where(ProjectRow.status == status)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def patch(
        self,
        project_id: str,
        *,
        name: str | None = None,
        client_id: str | None | _UnsetClientId = _UNSET_CLIENT_ID,
        instructions: str | None = None,
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.patch")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id) or (resolved_organization_id is not None and row.organization_id != resolved_organization_id):
                return None
            if name is not None:
                row.name = name
            if not isinstance(client_id, _UnsetClientId):
                row.client_id = client_id
            if instructions is not None:
                row.instructions = instructions
            if presentation is not None:
                row.presentation = presentation
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def set_status(
        self,
        project_id: str,
        status: ProjectStatus,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Idempotent status flip; returns the current row or None (missing/foreign)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.set_status")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id) or (resolved_organization_id is not None and row.organization_id != resolved_organization_id):
                return None
            row.status = status
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Delete a project and clear membership in one transaction (no filesystem work).

        Returns True when the project row was deleted; False when missing/foreign.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.delete")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            async with session.begin():
                # Lock the project row before touching it (FOR UPDATE on
                # Postgres; the clause renders nothing on SQLite). Membership
                # assignment (ThreadMetaRepository.set_project/create) takes
                # the same row lock before writing ``project_id``, so an
                # assigner either commits first and has its membership cleared
                # below, or blocks until this transaction commits and then
                # re-reads the row as gone — no dangling ``threads_meta.project_id``
                # (RFC v2 §14.14). Missing/foreign rows keep the False result.
                lock_stmt = select(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.user_id == resolved_user_id)
                if resolved_organization_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.organization_id == resolved_organization_id)
                locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
                if locked is None:
                    return False
                # §8.1 statement 2: every active shelf row moves to trash in
                # the same transaction and lock — never an active row pointing
                # at a deleted project. No filesystem work.
                await ProjectDocumentRepository.trash_all_for_project(session, project_id, project_name=locked.name, user_id=resolved_user_id, organization_id=resolved_organization_id)
                thread_update = update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id)
                delete_stmt = sa_delete(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    thread_update = thread_update.where(ThreadMetaRow.user_id == resolved_user_id)
                    delete_stmt = delete_stmt.where(ProjectRow.user_id == resolved_user_id)
                if resolved_organization_id is not None:
                    thread_update = thread_update.where(ThreadMetaRow.organization_id == resolved_organization_id)
                    delete_stmt = delete_stmt.where(ProjectRow.organization_id == resolved_organization_id)
                await session.execute(thread_update.values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                result = await session.execute(delete_stmt)
            return result.rowcount > 0


class ProjectDocumentRepository:
    """Project shelf documents: hash-qualified rows with a recoverable trash tier.

    Every read filters ``trashed_at IS NULL`` unless explicitly asked
    otherwise — trashed rows are invisible to the shelf index, the tools, and
    the listing APIs. Writes follow the Phase-1 lock idiom: SQLite takes the
    write lock up front (``BEGIN IMMEDIATE``), Postgres relies on
    ``SELECT … FOR UPDATE`` on the ``projects`` row; existence/ownership/
    status validation happens inside the mutating transaction, never as a
    separate check-then-act read (Phase-2 spec §6.3, §15.5).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectDocumentRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "trashed_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    @staticmethod
    async def _begin_immediate_if_sqlite(session: AsyncSession) -> None:
        if session.get_bind().dialect.name == "sqlite":
            # Read-then-write transaction: take the write lock up front
            # (ThreadMetaRepository precedent) so a concurrent writer cannot
            # interleave between the project lock and the mutation.
            await session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    async def _lock_active_project(session: AsyncSession, project_id: str, resolved_user_id: str | None, resolved_organization_id: str | None = None) -> ProjectRow | None:
        """Lock the owned ``status='active'`` project row inside the transaction."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id, ProjectRow.status == "active")
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectRow.organization_id == resolved_organization_id)
        return (await session.execute(stmt.with_for_update())).scalar_one_or_none()

    async def insert_active(
        self,
        project_id: str,
        *,
        document_id: str,
        name: str,
        relpath: str,
        sha256: str,
        size_bytes: int,
        source_thread_id: str | None = None,
        source_kind: str | None = None,
        source_name: str | None = None,
        place_file: Callable[[], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Insert one shelf row under the active-project lock, or return the dedup hit.

        One transaction (§6.3 shelf insert): lock the owned active project row
        (``None`` when missing/foreign/archived), dedup-``SELECT`` among active
        ``(project_id, sha256)`` rows, and on a miss invoke *place_file* — the
        atomic staging→final rename into this document's exclusive namespace —
        **before** the ``INSERT`` (file-before-row, §10.3): a crash leaves an
        unreferenced file the sweep collects, never a visible row without
        bytes. A dedup hit skips placement and returns the existing row — the
        first writer's name and provenance win (§10.9); callers recognize the
        hit by ``row["id"] != document_id``.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.insert_active")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            project = await self._lock_active_project(session, project_id, resolved_user_id, resolved_organization_id)
            if project is None:
                await session.rollback()
                return None
            dedup_stmt = select(ProjectDocumentRow).where(
                ProjectDocumentRow.project_id == project_id,
                ProjectDocumentRow.sha256 == sha256,
                ProjectDocumentRow.trashed_at.is_(None),
            )
            if resolved_user_id is not None:
                dedup_stmt = dedup_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                dedup_stmt = dedup_stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            existing = (await session.execute(dedup_stmt)).scalars().first()
            if existing is not None:
                await session.commit()
                return self._row_to_dict(existing)
            if place_file is not None:
                # Drained: cancellation waits for the placement worker instead of
                # releasing the project lock over in-flight filesystem work.
                await await_drained(place_file())
            now = datetime.now(UTC)
            row = ProjectDocumentRow(
                id=document_id,
                project_id=project_id,
                user_id=resolved_user_id,
                organization_id=organization_from_owned_parent(project, resolved_user_id, parent_name="project"),
                name=name,
                stored_relpath=relpath,
                sha256=sha256,
                size_bytes=size_bytes,
                source_thread_id=source_thread_id,
                source_kind=source_kind,
                source_name=source_name,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def find_active_by_sha256(self, project_id: str, sha256: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return the active row with this content address, or ``None`` (dedup probe)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.find_active_by_sha256")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(
            ProjectDocumentRow.project_id == project_id,
            ProjectDocumentRow.sha256 == sha256,
            ProjectDocumentRow.trashed_at.is_(None),
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._row_to_dict(row) if row is not None else None

    async def list_active(self, project_id: str, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Active shelf rows in index order: ``updated_at DESC, id ASC`` (§10.10)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_active")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None)).order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_active(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_active")
        resolved_organization_id = resolve_organization_id()
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def shelf_snapshot(self, project_id: str, *, limit: int, user_id: str | None | _AutoSentinel = AUTO) -> tuple[list[dict], int]:
        """Return ``(rows, total)`` for the pinned shelf index in one round trip.

        ``rows`` are the first ``limit`` active rows in ``updated_at DESC,
        id ASC`` order against the same database snapshot as ``total``; the
        caller (§7.1 step 2) fetches ``shelf_index_max_entries + 1`` and uses
        the extra row only to decide truncation — it is never rendered.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.shelf_snapshot")
        resolved_organization_id = resolve_organization_id()
        stmt = (
            select(ProjectDocumentRow, func.count().over().label("total"))
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc())
            .limit(limit)
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            pairs = result.all()
            rows = [self._row_to_dict(row) for row, _total in pairs]
            total = int(pairs[0][1]) if pairs else 0
            return rows, total

    async def get(self, document_id: str, *, include_trashed: bool = False, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return one owned row, or ``None`` (missing/foreign; trashed unless included)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.get")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            row = await session.get(ProjectDocumentRow, document_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            if resolved_organization_id is not None and row.organization_id != resolved_organization_id:
                return None
            if row.trashed_at is not None and not include_trashed:
                return None
            return self._row_to_dict(row)

    async def trash(self, document_id: str, *, project_id: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Move one owned document to trash; ``False`` ⇒ 404 (§6.3 trash).

        Locks the owned **active** project row first — an archived shelf
        rejects this write (§8.4) — then the owned document row in the same
        transaction, and applies the guarded ``UPDATE … WHERE project_id =
        :pid AND trashed_at IS NULL``. ``False`` covers every failure shape
        (missing/foreign document, missing/foreign/archived project, already
        trashed) so the route never leaks existence.

        *project_id* is the caller's expected project (the route's URL
        project): when given, both the unlocked probe and the locked re-read
        require the row to belong to it — a document of a sibling project is
        indistinguishable from missing, and the guarded ``UPDATE`` predicates
        on the expected id. When omitted, the document's own project is used.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.trash")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            # Route to the owning project: the authoritative validation is the
            # locked re-read below, so this unlocked probe leaks nothing.
            probe = await session.get(ProjectDocumentRow, document_id)
            if (
                probe is None
                or (project_id is not None and probe.project_id != project_id)
                or (resolved_user_id is not None and probe.user_id != resolved_user_id)
                or (resolved_organization_id is not None and probe.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return False
            expected_project_id = project_id if project_id is not None else probe.project_id
            locked_project = await self._lock_active_project(session, expected_project_id, resolved_user_id, resolved_organization_id)
            if locked_project is None:
                await session.rollback()
                return False
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != expected_project_id
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return False
            stmt = (
                update(ProjectDocumentRow)
                .where(
                    ProjectDocumentRow.id == document_id,
                    ProjectDocumentRow.project_id == expected_project_id,
                    ProjectDocumentRow.trashed_at.is_(None),
                )
                .values(
                    trashed_at=datetime.now(UTC),
                    trash_origin={"project_id": locked_project.id, "project_name": locked_project.name},
                )
            )
            if resolved_user_id is not None:
                stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def trash_all_for_project(session: AsyncSession, project_id: str, *, project_name: str, user_id: str | None, organization_id: str | None = None) -> int:
        """Trash every active shelf row of a project inside the caller's transaction.

        §8.1 statement 2: runs under the same project row lock
        ``ProjectRepository.delete`` already holds, so a concurrent shelf
        insert either commits first (and is trashed here) or blocks and then
        finds no active project — never an active row pointing at a deleted
        project. No filesystem work: rows snapshot ``{project_id,
        project_name}`` before the project row disappears.
        """
        stmt = (
            update(ProjectDocumentRow)
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .values(
                trashed_at=datetime.now(UTC),
                trash_origin={"project_id": project_id, "project_name": project_name},
            )
        )
        if user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == user_id)
        if organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == organization_id)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    async def stage_live_copy[T](
        self,
        document_id: str,
        *,
        project_id: str,
        stage: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *stage* while holding the owned LIVE document row's lock (§7.3 item 3).

        Attach-to-thread reads a stable source copy serialized against purge
        and trash: this takes the document row lock inside one transaction
        (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE`` elsewhere),
        validates ownership, shelf membership and liveness (``trashed_at IS
        NULL`` — an archived source project stays readable, §8.4), then
        invokes *stage* with the row dict and commits. A concurrent purge
        either commits first (the locked re-read finds the row gone/trashed
        and this returns ``None``) or blocks until the copy finishes — never
        a partially copied source. Only the document lock is taken, so no
        lock-ordering hazard exists against purge's project→document order
        (§6.3). The staged copy is the caller's responsibility once the lock
        is released.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.stage_live_copy")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != project_id
                or locked.trashed_at is not None
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: the lock is never released over an in-flight staging copy.
            staged = await await_drained(stage(row))
            await session.commit()
            return row, staged

    async def convert_under_live_lock[T](
        self,
        document_id: str,
        *,
        project_id: str,
        convert: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *convert* while holding the owned LIVE document row's lock (§6.3).

        Lazy conversion publishes ``derived/converted.md`` serialized against
        trash and purge: this takes the document row lock inside one
        transaction (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE``
        elsewhere), revalidates ownership, shelf membership and active state
        (``trashed_at IS NULL``) AFTER locking, then invokes *convert* — the
        offloaded convert-to-temp + atomic ``os.replace`` publish — and
        commits. A concurrent trash/purge either commits first (the locked
        re-read finds the row gone/trashed and this returns ``None`` without
        invoking *convert*, so nothing is published) or blocks until the
        publish commits — a derived file is never published after purge
        removed the original (§6.3 lock order, §13). Only the document lock
        is taken, so no lock-ordering hazard exists against trash's
        project→document order. ``None`` means missing/foreign/trashed; the
        caller maps it to its not-on-the-shelf / ``content_missing``
        semantics.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.convert_under_live_lock")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if (
                locked is None
                or locked.project_id != project_id
                or locked.trashed_at is not None
                or (resolved_user_id is not None and locked.user_id != resolved_user_id)
                or (resolved_organization_id is not None and locked.organization_id != resolved_organization_id)
            ):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: a cancelled conversion finishes its worker (and any
            # publish) before the document lock unwinds (§6.3).
            result = await await_drained(convert(row))
            await session.commit()
            return row, result

    async def list_trashed(self, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows, most recently trashed first (trash listing, §6.5)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None)).order_by(ProjectDocumentRow.trashed_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_trashed(self, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def list_all_trashed(self, *, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Every trashed row of the caller, oldest first — the Empty-trash pool (§8.3).

        Empty trash removes exactly what the user confirmed, so it selects on
        trashed state alone; ``purge_candidates`` stays the only age-gated
        selection (the retention sweep's).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_all_trashed")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None)).order_by(ProjectDocumentRow.trashed_at.asc(), ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_all_for_sweep(self, *, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Every row — active and trashed — for retention-sweep reconciliation.

        The sweep (§8.3) needs the full row set of the swept user(s): any row
        protects its entire original/derived namespace from orphan collection
        (even after restore re-pointed it to another project), and row-side
        reconciliation detects missing/size-mismatched content without
        deleting anything.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_all_for_sweep")
        resolved_organization_id = resolve_organization_id()
        stmt = select(ProjectDocumentRow).order_by(ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def restore(
        self,
        document_id: str,
        *,
        target_project_id: str,
        check_content: Callable[[dict[str, Any]], Awaitable[bool]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[Literal["restored", "merged", "not_found", "no_target", "content_missing"], dict | None]:
        """Restore one trashed row into an active target project (§6.3/§8.2).

        One transaction: lock the target active owned project row first
        (``None`` ⇒ ``no_target``: missing/foreign/archived are
        indistinguishable), then lock the source and any merge-candidate rows
        in ID order. Source ownership and ``trashed_at IS NOT NULL`` are
        revalidated after locking (missing/already-restored/purged ⇒
        ``not_found``). Before either outcome, *check_content* verifies the
        original's existence/size under the source lock — and, for a merge,
        the surviving target's content under its lock; a failure yields
        ``content_missing`` and leaves the source trashed (§8.3). Merge: the
        target already has an active row with the same ``sha256``, so the
        trash row is deleted and the surviving row returned; the caller
        unlinks the discarded source namespace best-effort AFTER commit.
        Otherwise the row is re-pointed (``project_id`` = target, trash
        fields cleared, ``organization_id`` re-derived from the target) with
        NO file moves — ``stored_relpath`` is projects-root-relative, so the
        bytes stay valid (§10.6).

        The source lookup below intentionally checks only ``user_id``, never
        ``organization_id``: ``user_id`` (the storage principal) already
        proves ownership on this table, and restore is the row's one
        healing opportunity for a stale/NULL ``organization_id`` (a legacy
        row, or a prior restore that predates this fix) — gating the lookup
        on a match would make such a row permanently unrestorable instead of
        healed.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.restore")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked_project = await self._lock_active_project(session, target_project_id, resolved_user_id, resolved_organization_id)
            if locked_project is None:
                await session.rollback()
                return "no_target", None
            # Identify the source and any merge candidates before locking.
            # This unlocked probe only chooses WHICH rows to lock; every
            # validation below re-reads the locked rows.
            probe = (await session.execute(select(ProjectDocumentRow.id, ProjectDocumentRow.sha256, ProjectDocumentRow.trashed_at).where(ProjectDocumentRow.id == document_id))).first()
            if probe is None:
                await session.rollback()
                return "not_found", None
            lock_ids = [document_id]
            if probe.trashed_at is not None:
                candidates = await session.execute(
                    select(ProjectDocumentRow.id).where(
                        ProjectDocumentRow.project_id == target_project_id,
                        ProjectDocumentRow.sha256 == probe.sha256,
                        ProjectDocumentRow.trashed_at.is_(None),
                        ProjectDocumentRow.id != document_id,
                    )
                )
                lock_ids.extend(row[0] for row in candidates.all())
            locked_rows = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id.in_(lock_ids)).order_by(ProjectDocumentRow.id.asc()).with_for_update())).scalars().all()
            by_id = {row.id: row for row in locked_rows}
            source = by_id.get(document_id)
            # Revalidate under the lock: ownership + still trashed. See the
            # docstring above for why this is user_id-only.
            if source is None or source.trashed_at is None or (resolved_user_id is not None and source.user_id != resolved_user_id):
                await session.rollback()
                return "not_found", None
            if check_content is not None and not await await_drained(check_content(self._row_to_dict(source))):
                # Missing/size-mismatched bytes: leave the row trashed (§8.3).
                await session.rollback()
                return "content_missing", None
            surviving = next(
                (row for row in locked_rows if row.id != document_id and row.project_id == target_project_id and row.sha256 == source.sha256 and row.trashed_at is None and (resolved_user_id is None or row.user_id == resolved_user_id)),
                None,
            )
            if surviving is not None:
                if check_content is not None and not await await_drained(check_content(self._row_to_dict(surviving))):
                    await session.rollback()
                    return "content_missing", None
                # Merge: the target already serves these bytes; delete the
                # trash row (guarded) and report the surviving row. No file
                # mutation inside the transaction — the discarded namespace
                # cleanup follows commit (§8.2).
                result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
                await session.commit()
                if result.rowcount == 0:
                    return "not_found", None
                return "merged", self._row_to_dict(surviving)
            # Re-point: no file moves (§10.6). The document row lock held
            # since the revalidation above serializes this against purge.
            # organization_id is re-derived from the now-locked target
            # project, exactly like insert_active's stamp — never left as
            # whatever the source row carried (the bug this fixes: a stale
            # or NULL organization_id survived a restore untouched).
            source.project_id = target_project_id
            source.organization_id = organization_from_owned_parent(locked_project, resolved_user_id, parent_name="project")
            source.trashed_at = None
            source.trash_origin = None
            await session.commit()
            await session.refresh(source)
            return "restored", self._row_to_dict(source)

    async def purge_candidates(self, retention_days: int, *, now: datetime | None = None, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows at or past the retention window, oldest first (§8.3).

        A row trashed exactly ``retention_days`` ago is eligible — the window
        has fully passed. The sweep revalidates each candidate's trash
        timestamp and the cutoff under the purge lock before removing
        anything (§6.1).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge_candidates")
        resolved_organization_id = resolve_organization_id()
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None), ProjectDocumentRow.trashed_at <= cutoff).order_by(ProjectDocumentRow.trashed_at.asc(), ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        if resolved_organization_id is not None:
            stmt = stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def purge(
        self,
        document_id: str,
        *,
        retention_cutoff: datetime | None = None,
        expected_trashed_at: datetime | str | None = None,
        remove_files: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        """Permanently delete one trashed row and its bytes (§6.3/§8.3).

        One database transaction holds the owned document-row lock
        continuously across trashed-state revalidation, *remove_files*
        (unlink of the original and ``derived/converted.md``), row deletion
        and commit — restore cannot pass its source-row lock meanwhile.
        Purge acquires only its document lock and never later waits on a
        project lock (§6.3 lock order). Retention callers pass
        ``expected_trashed_at`` + ``retention_cutoff`` from their candidate
        selection; both are revalidated under the lock, so a row restored
        and later re-trashed is NOT purged on its former expiry. Manual
        purge passes neither and only requires the row to be trashed now.
        ``FileNotFoundError`` inside *remove_files* counts as already
        removed; any other error rolls the transaction back and leaves a
        retryable trashed row. ``False`` ⇒ 404 (missing, foreign, not
        trashed, or no longer matching the retention selection). No public
        unguarded row deletion exists.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge")
        resolved_organization_id = resolve_organization_id()
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            lock_stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id)
            if resolved_user_id is not None:
                lock_stmt = lock_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            if resolved_organization_id is not None:
                lock_stmt = lock_stmt.where(ProjectDocumentRow.organization_id == resolved_organization_id)
            locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
            if locked is None or locked.trashed_at is None:
                await session.rollback()
                return False
            if expected_trashed_at is not None and coerce_iso(locked.trashed_at) != coerce_iso(expected_trashed_at):
                # Restored and re-trashed since candidate selection: the
                # former expiry no longer applies (§6.1).
                await session.rollback()
                return False
            if retention_cutoff is not None:
                trashed_at = locked.trashed_at
                if trashed_at.tzinfo is None:
                    trashed_at = trashed_at.replace(tzinfo=UTC)
                if trashed_at > retention_cutoff:
                    await session.rollback()
                    return False
            if remove_files is not None:
                try:
                    # Drained: cancellation waits for the unlink worker, so the
                    # row lock is released only after the filesystem work finished.
                    await await_drained(remove_files(self._row_to_dict(locked)))
                except Exception:
                    # Filesystem work is not rollbackable, but the row is:
                    # keep the trashed row so the purge stays retryable (§8.3).
                    await session.rollback()
                    raise
            result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
            await session.commit()
            return result.rowcount > 0
````

## backend/packages/harness/deerflow/projects/documents.py

````python
"""Project document shelf service: staging, atomic insert, conversion.

Implements the Phase-2 shelf-insert atomicity (spec §6.3): bytes are staged
under ``.staging/{uuid}``, hashed, then — inside the repository's one
transaction (active-project row lock → dedup select → insert) — atomically
renamed into the document's exclusive namespace **before** the row exists
(file-before-row, §10.3). A dedup hit removes staging and returns the existing
row (the first writer's name wins, §10.9); a failed insert cleans up only its
own namespace, best-effort. Every filesystem operation runs off the event
loop via :func:`deerflow.utils.file_io.run_file_io`.

Files are immutable and hash-qualified: ``stored_relpath`` (relative to
``users/{user_id}/projects/``) embeds the content hash and the row's own
document ID, so rows never share bytes and a re-upload after trash lands in a
fresh namespace (§6.2). Conversion is lazy: a convertible original is turned
into ``derived/converted.md`` on first read, written through a temporary file
and an atomic rename, and only when ``uploads.auto_convert_documents`` is on
(§6.4, §7.3).
"""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import logging
import os
import shutil
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import Paths
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown
from deerflow.utils.file_io import run_file_io
from deerflow.utils.text_detection import is_text_file_by_content

if TYPE_CHECKING:
    from deerflow.persistence.projects import ProjectDocumentRepository

logger = logging.getLogger(__name__)

_MAX_FILENAME_BYTES = 255


def _filesystem_path(path: Path) -> Path:
    """Use Windows' extended-length form after safe namespace resolution."""
    if os.name != "nt" or str(path).startswith("\\\\?\\") or len(str(path)) < 248:
        return path
    raw = str(path)
    return Path(f"\\\\?\\UNC\\{raw[2:]}") if raw.startswith("\\\\") else Path(f"\\\\?\\{raw}")


class ShelfUploadTooLargeError(Exception):
    """Raised when staged bytes exceed ``uploads.max_file_size`` (mapped to 413)."""


def validate_shelf_filename(name: str) -> str:
    """Normalize and validate a shelf display filename; ``ValueError`` ⇒ 400.

    The display filename occupies its own path component (no hash prefix or
    suffix), so it must be a bare, non-empty filename within the 255 UTF-8
    byte filesystem limit — path separators are rejected outright rather than
    stripped (§6.5).
    """
    candidate = name.strip() if name else ""
    if not candidate:
        raise ValueError("Filename is empty")
    if "/" in candidate or "\\" in candidate:
        raise ValueError(f"Filename contains a path separator: {name!r}")
    if candidate in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {name!r}")
    if len(candidate.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ValueError(f"Filename exceeds {_MAX_FILENAME_BYTES} UTF-8 bytes")
    return candidate


def shelf_relpath(project_id: str, sha256: str, document_id: str) -> str:
    """Content-addressed namespace root for one row, relative to ``users/{user_id}/projects/``."""
    return f"{project_id}/documents/{sha256[:2]}/{sha256}/{document_id}"


def original_file_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's immutable original bytes."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[0]


def converted_markdown_path(paths: Paths, *, user_id: str, row: dict) -> Path:
    """Absolute host path of a row's optional ``derived/converted.md`` companion."""
    return resolve_document_paths(paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])[1]


def resolve_document_paths(paths: Paths, *, user_id: str, relpath: str, name: str) -> tuple[Path, Path]:
    """Resolve a row's ``(original, derived)`` host paths — worker-thread only on async paths.

    ``Paths.project_document_path`` resolves symlinks against the real
    filesystem, so async callers MUST dispatch this through ``run_file_io``
    (filesystem-offload convention); the helper itself stays sync because it
    is also used from worker contexts already off the loop.
    """
    namespace = paths.project_document_path(user_id, relpath)
    return _filesystem_path(namespace / "original" / name), _filesystem_path(namespace / "derived" / "converted.md")


def _content_intact(paths: Paths, *, user_id: str, row: dict) -> bool:
    """Worker-thread: resolve the original and verify it exists and matches the row's recorded size."""
    original = original_file_path(paths, user_id=user_id, row=row)
    try:
        return original.stat().st_size == int(row.get("size_bytes") or -1)
    except OSError:
        return False


async def check_document_content(paths: Paths, *, user_id: str, row: dict) -> bool:
    """True when the row's immutable original exists and matches ``size_bytes``.

    The one content check shared by the text serving path, restore (under
    the document lock), the content endpoint, and the retention sweep's row
    reconciliation (§8.3/§11): missing or size-mismatched bytes mean external
    interference — reported as ``content_missing``, never served, repaired,
    or treated as an empty document.
    """
    return await run_file_io(_content_intact, paths, user_id=user_id, row=row)


def _content_intact_batch(paths: Paths, *, user_id: str, rows: list[dict]) -> list[bool]:
    """Worker-thread: existence+size check for a whole page of rows in one offload pass."""
    return [_content_intact(paths, user_id=user_id, row=row) for row in rows]


@dataclass(slots=True)
class StagedDocument:
    """Bytes staged under ``.staging/`` with their content address."""

    staging_path: Path
    sha256: str
    size_bytes: int


def _open_staging(staging_dir: Path, staging_path: Path):
    """Worker-thread: create the staging directory and open the staging file."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    return open(staging_path, "wb")


def _close_and_unlink(handle: Any, staging_path: Path) -> None:
    try:
        handle.close()
    finally:
        staging_path.unlink(missing_ok=True)


async def stage_document_bytes(paths: Paths, *, user_id: str, project_id: str, chunks: AsyncIterator[bytes] | list[bytes], max_bytes: int) -> StagedDocument:
    """Stage upload/promote bytes off-loop, enforcing the single-file size cap.

    Chunks are streamed to ``.staging/{uuid}`` (writes offloaded one by one,
    the uploads router's discipline) while the content hash accumulates.
    ``max_bytes`` is the thread-upload limit (``uploads.max_file_size``) —
    the shelf deliberately reuses it instead of growing a second knob with
    the same meaning (§6.4). Overflow raises :class:`ShelfUploadTooLargeError`
    (the route maps it to 413, mirroring the uploads router) and leaves no
    staging file behind.
    """
    staging_dir = paths.project_documents_dir(user_id, project_id) / ".staging"
    staging_path = staging_dir / uuid.uuid4().hex
    handle = await run_file_io(_open_staging, staging_dir, staging_path)
    digest = hashlib.sha256()
    size = 0

    async def _aiter() -> AsyncIterator[bytes]:
        if isinstance(chunks, list):
            for chunk in chunks:
                yield chunk
        else:
            async for chunk in chunks:
                yield chunk

    try:
        async for chunk in _aiter():
            size += len(chunk)
            if size > max_bytes:
                raise ShelfUploadTooLargeError(f"File exceeds the {max_bytes}-byte limit")
            digest.update(chunk)
            await run_file_io(handle.write, chunk)
        await run_file_io(handle.close)
    except Exception:
        await run_file_io(_close_and_unlink, handle, staging_path)
        raise
    return StagedDocument(staging_path=staging_path, sha256=digest.hexdigest(), size_bytes=size)


def _place_staging(staging_path: Path, final_path: Path) -> None:
    """Atomically move staged bytes into the document's exclusive namespace."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staging_path, final_path)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def _remove_staging(staging_path: Path) -> None:
    staging_path.unlink(missing_ok=True)


def _remove_namespace(paths: Paths, *, user_id: str, relpath: str) -> None:
    """Best-effort removal of one document's exclusive namespace (never another row's)."""
    shutil.rmtree(paths.project_document_path(user_id, relpath), ignore_errors=True)


async def add_staged_document(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    name: str,
    staged: StagedDocument,
    source_thread_id: str | None = None,
    source_kind: str | None = None,
    source_name: str | None = None,
) -> tuple[dict, bool] | None:
    """Publish staged bytes as a shelf row, or fold into the dedup hit.

    Returns ``(row, created)`` — ``created`` is ``False`` for a dedup hit, in
    which case the returned row is the pre-existing one (its name and
    provenance win, §10.9) and the staged bytes are discarded. ``None`` means
    the project is missing, foreign, or archived (the route maps it to 404).
    A failure removes this document's namespace only when the row PROVABLY
    does not exist: a post-commit failure (e.g. the insert's trailing
    refresh) leaves the live row serving its placed bytes and is reported as
    success, and an indeterminate liveness check leaves the namespace for
    the reference-aware sweep (§8.3).
    """
    document_id = uuid.uuid4().hex
    relpath = shelf_relpath(project_id, staged.sha256, document_id)
    # Symlink-resolving lookup — offloaded like every filesystem touch here.
    final_path = (await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=relpath, name=name))[0]

    async def _place() -> None:
        await run_file_io(_place_staging, staged.staging_path, final_path)

    try:
        row = await repo.insert_active(
            project_id,
            document_id=document_id,
            name=name,
            relpath=relpath,
            sha256=staged.sha256,
            size_bytes=staged.size_bytes,
            source_thread_id=source_thread_id,
            source_kind=source_kind,
            source_name=source_name,
            place_file=_place,
            user_id=user_id,
        )
    except Exception:
        # ``insert_active`` owns its commit: a failure may surface AFTER the
        # row committed (e.g. its trailing refresh), so the placed namespace
        # is removed only when the row PROVABLY does not exist. When the row
        # is live the insert effectively succeeded — the shelf already serves
        # these bytes — so return it instead of raising; when liveness cannot
        # be determined, leave the namespace for the reference-aware
        # retention sweep (§8.3), which only collects unreferenced files and
        # protects any row's namespace. The probe includes TRASHED rows: a
        # row raced into trash (or a trashing project deletion) before the
        # re-check still owns the placed bytes — trash is recoverable, so
        # deleting the namespace would destroy a recoverable document.
        await run_file_io(_remove_staging, staged.staging_path)
        committed: dict | None
        try:
            committed = await repo.get(document_id, include_trashed=True, user_id=user_id)
        except Exception:
            committed = None
            row_provably_absent = False
            logger.warning(
                "Shelf insert of %s failed and the liveness re-check failed too; leaving the namespace for the retention sweep",
                document_id,
                exc_info=True,
            )
        else:
            row_provably_absent = committed is None
        if committed is not None:
            if committed.get("trashed_at") is None:
                logger.warning("Shelf insert of %s raised after commit; the row is live — keeping its namespace and reporting success", document_id)
                return committed, True
            # Committed but raced into trash before the re-check: keep the
            # bytes recoverable in trash and surface the failure rather than
            # presenting a trashed row as created.
            logger.warning("Shelf insert of %s raised after commit and the row was trashed meanwhile; keeping its namespace in trash", document_id)
        elif row_provably_absent:
            # Confirmed rollback: the bytes are unreferenced — clean up only
            # this document's own namespace (§6.3).
            await run_file_io(_remove_namespace, paths, user_id=user_id, relpath=relpath)
        raise
    if row is None:
        # Missing/foreign/archived project: nothing was placed or inserted.
        await run_file_io(_remove_staging, staged.staging_path)
        return None
    if row["id"] != document_id:
        # Dedup hit: the existing row wins; discard the staged duplicate.
        await run_file_io(_remove_staging, staged.staging_path)
        return row, False
    return row, True


def _convert_in_thread(original: Path, output_path: Path) -> Path | None:
    """Run the async conversion engine on a private loop inside the worker.

    ``convert_file_to_markdown`` offloads its own heavy work (>1 MiB) but
    stats and writes on its caller's loop; running the whole coroutine here
    keeps every byte of the conversion path off the serving event loop.
    """
    return asyncio.run(convert_file_to_markdown(original, output_path=output_path))


def _convert_and_publish(original: Path, derived: Path) -> bool:
    """Worker-thread body: convert to a temp file, then atomically publish.

    The temp file lives beside the final path (same filesystem) so the
    rename is atomic: readers only ever see a complete ``converted.md`` or
    none at all. A conversion failure publishes nothing and removes the temp.
    """
    derived.parent.mkdir(parents=True, exist_ok=True)
    temp_path = derived.parent / f".{derived.name}.{uuid.uuid4().hex}.tmp"
    try:
        produced = _convert_in_thread(original, temp_path)
        if produced is None:
            return False
        os.replace(produced, derived)
        return True
    except Exception:
        logger.warning("Failed to convert shelf document %s", original, exc_info=True)
        temp_path.unlink(missing_ok=True)
        return False
    finally:
        temp_path.unlink(missing_ok=True)


async def ensure_converted_markdown(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Return ``(converted_path, None)`` or ``(None, reason)``, converting on first read.

    Conversion runs — and ``derived/converted.md`` is published — while the
    repository holds the document row lock, with ownership, shelf membership
    and active state revalidated AFTER locking (§6.3): a trash/purge that
    committed first makes this decline as ``content_missing`` without
    converting or publishing anything, and one arriving during conversion
    blocks on the row lock and then proceeds. The temp-file + atomic
    ``os.replace`` publish stays inside the lock, so no partial converted
    text is ever exposed. The published companion is valid for the lifetime
    of the row's immutable original and never needs invalidation (§6.2,
    §10.9). ``reason`` is one of ``"conversion_disabled"`` (auto-convert
    off, §7.3), ``"content_missing"`` (row no longer live), or ``"binary"``
    (not convertible, or the conversion itself failed).
    """
    if not auto_convert:
        return None, "conversion_disabled"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if original.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        return None, "binary"
    if await run_file_io(derived.is_file):
        return derived, None

    async def _convert(_locked_row: dict) -> bool:
        # Re-check under the lock: a conversion that blocked on this row's
        # lock may already have been published by the lock's previous holder.
        if await run_file_io(derived.is_file):
            return True
        return await run_file_io(_convert_and_publish, original, derived)

    locked = await repo.convert_under_live_lock(row["id"], project_id=row["project_id"], convert=_convert, user_id=user_id)
    if locked is None:
        # Purged/trashed (or foreign) between the caller's read and the
        # locked revalidation: decline without publishing anything (§6.3).
        return None, "content_missing"
    _locked_row, published = locked
    return (derived, None) if published else (None, "binary")


async def read_text_serving_path(repo: ProjectDocumentRepository, paths: Paths, *, user_id: str, row: dict, auto_convert: bool) -> tuple[Path | None, str | None]:
    """Resolve which file serves a row's text reads, or why none can.

    Returns ``(path, None)`` for a servable text source — the cached
    ``derived/converted.md``, the original when it samples as text, or a
    freshly converted companion — and ``(None, reason)`` otherwise, where
    ``reason`` is one of ``"content_missing"``, ``"conversion_disabled"`` or
    ``"binary"`` so the caller can produce the §11 error without re-deriving
    the classification. The immutable ORIGINAL is validated (existence AND
    recorded size, the shared §8.3 check) before either serving source is
    selected: a truncated or zero-byte original is ``content_missing``, never
    served as complete, and the derived companion is only servable while its
    owning original validates (§6.2). A convertible extension
    (``CONVERTIBLE_EXTENSIONS``) takes the conversion path — or the
    ``conversion_disabled`` decline — BEFORE the text heuristic: a
    null-free head (e.g. an ASCII85 PDF) must never be raw-served as text.
    Genuine text extensions keep the sampled-head heuristic (no
    ``mime``/``is_text`` columns exist by design, §6.1).
    """
    if not await check_document_content(paths, user_id=user_id, row=row):
        return None, "content_missing"
    original, derived = await run_file_io(resolve_document_paths, paths, user_id=user_id, relpath=row["stored_relpath"], name=row["name"])
    if await run_file_io(derived.is_file):
        return derived, None
    if original.suffix.lower() in CONVERTIBLE_EXTENSIONS:
        return await ensure_converted_markdown(repo, paths, user_id=user_id, row=row, auto_convert=auto_convert)
    if await run_file_io(is_text_file_by_content, original):
        return original, None
    return None, "binary"


#: Bounded decode window: reads stop once the requested character page is full.
_TEXT_READ_CHUNK = 65536

#: Bounded process-local LRU of decoded character counts, keyed by content
#: identity ``(document_id, sha256)``. Documents are immutable within a row's
#: lifetime (§6.2/§10.9) and ids are never reused, so a purge simply orphans
#: an entry until LRU eviction — no invalidation hook needed.
_CHAR_COUNT_CACHE: OrderedDict[tuple[str, str], int] = OrderedDict()
_CHAR_COUNT_CACHE_MAX = 256


def _read_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Worker-thread: decode only enough of *path* to fill ``[offset, offset+limit)``.

    Incremental UTF-8 decode (replacement-tolerant, split-sequence safe) over
    bounded chunks: the full decoded string is never materialized and reading
    stops as soon as the window is filled, so an early page of a multi-MiB
    document never reads the whole file.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    parts: list[str] = []
    position = 0  # decoded characters seen so far
    end = offset + limit
    with open(path, "rb") as handle:
        while position < end:
            chunk = handle.read(_TEXT_READ_CHUNK)
            final = not chunk
            text = decoder.decode(chunk, final)
            if not text:
                if final:
                    break
                continue
            if position + len(text) > offset:
                parts.append(text[max(offset - position, 0) :])
            position += len(text)
            if final:
                break
    return "".join(parts)[:limit]


def _count_text_chars(path: Path) -> int:
    """Worker-thread: full scan-decode COUNT without materializing the string."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    total = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(_TEXT_READ_CHUNK):
            total += len(decoder.decode(chunk))
    return total + len(decoder.decode(b"", True))


def _cached_char_count(document_id: str, sha256: str, path: Path) -> int:
    """Worker-thread: character count of an immutable document, cached by content identity."""
    key = (document_id, sha256)
    cached = _CHAR_COUNT_CACHE.get(key)
    if cached is not None:
        _CHAR_COUNT_CACHE.move_to_end(key)
        return cached
    total = _count_text_chars(path)
    _CHAR_COUNT_CACHE[key] = total
    while len(_CHAR_COUNT_CACHE) > _CHAR_COUNT_CACHE_MAX:
        _CHAR_COUNT_CACHE.popitem(last=False)
    return total


async def read_document_text_window(path: Path, *, offset: int, limit: int) -> str:
    """Decode the ``[offset, offset+limit)`` character window of a serving file, off-loop."""
    return await run_file_io(_read_text_window, path, offset=offset, limit=limit)


async def document_char_count(*, document_id: str, sha256: str, path: Path) -> int:
    """Total decoded characters of a serving file, off-loop and content-identity cached."""
    return await run_file_io(_cached_char_count, document_id, sha256, path)


def auto_convert_documents_enabled(app_config: Any) -> bool:
    """Return whether host-side document conversion is enabled (secure default off).

    Mirrors the uploads router's reader: a malformed value declines rather
    than crashing, and stringly-typed YAML booleans are honored.
    """
    try:
        uploads_cfg = getattr(app_config, "uploads", None)
        raw = uploads_cfg.get("auto_convert_documents", False) if isinstance(uploads_cfg, dict) else getattr(uploads_cfg, "auto_convert_documents", False)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    except Exception:
        return False


class ShelfContentMissingError(Exception):
    """A live row's original bytes are absent or size-mismatched (§11 ``content_missing``)."""


async def read_file_chunks(path: Path, *, chunk_size: int = 65536) -> AsyncIterator[bytes]:
    """Yield one file's bytes with every read off the event loop.

    Shared by the from-thread promote path (thread file → shelf staging) and
    the attach path (staged shelf copy → thread-upload ingestion).
    """

    def _open() -> Any:
        return open(path, "rb")

    handle = await run_file_io(_open)
    try:
        while chunk := await run_file_io(handle.read, chunk_size):
            yield chunk
    finally:
        await run_file_io(handle.close)


def _copy_original_under_lock(paths: Paths, staging_path: Path, *, user_id: str, row: dict) -> None:
    """Worker-thread: copy a live document's original to a stable staging file.

    Runs inside the document row lock (``stage_live_copy``): the bytes are
    immutable, so an absent file or a size disagreement means external
    interference — reported as ``content_missing``, never copied (§8.3).
    Resolving the original's path happens here too: ``project_document_path``
    resolves symlinks against the real filesystem, so it stays off the
    caller's event loop.
    """
    source = original_file_path(paths, user_id=user_id, row=row)
    expected_size = row.get("size_bytes")
    if not source.is_file():
        raise ShelfContentMissingError("original bytes are missing")
    if expected_size is not None and source.stat().st_size != expected_size:
        raise ShelfContentMissingError("original size disagrees with the row")
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, staging_path)


async def stage_document_copy_for_attach(
    repo: ProjectDocumentRepository,
    paths: Paths,
    *,
    user_id: str,
    project_id: str,
    document_id: str,
) -> tuple[dict, Path] | None:
    """Stage a stable copy of a live document's original under its row lock.

    §7.3 item 3: attach is serialized against purge/trash — the copy runs
    while the repository holds the document row lock, then the lock is
    released BEFORE the caller performs sandbox allocation/network sync.
    The copy lands in the project shelf's ``.staging/`` (a crash leftover is
    collected by the retention sweep's 24-hour orphan guard, §8.3) and is
    the caller's responsibility to unlink. ``None`` means the document is
    missing, foreign, trashed, or not on this project's shelf (the route
    maps it to 404); :class:`ShelfContentMissingError` maps to 409.
    """
    staging_path = paths.project_documents_dir(user_id, project_id) / ".staging" / f"attach-{uuid.uuid4().hex}"

    async def _copy(row: dict) -> Path:
        await run_file_io(_copy_original_under_lock, paths, staging_path, user_id=user_id, row=row)
        return staging_path

    result = await repo.stage_live_copy(document_id, project_id=project_id, stage=_copy, user_id=user_id)
    if result is None:
        return None
    row, staged_path = result
    return row, staged_path
````

## backend/app/gateway/authz.py

````python
"""Authorization decorators and context for DeerFlow.

Inspired by LangGraph Auth system: https://github.com/langchain-ai/langgraph/blob/main/libs/sdk-py/langgraph_sdk/auth/__init__.py

**Usage:**

1. Use ``@require_auth`` on routes that need authentication
2. Use ``@require_permission("resource", "action", filter_key=...)`` for permission checks
3. The decorator chain processes from bottom to top

**Example:**

    @router.get("/{thread_id}")
    @require_auth
    @require_permission("threads", "read", owner_check=True)
    async def get_thread(thread_id: str, request: Request):
        # User is authenticated and has threads:read permission
        ...

**Permission Model:**

- threads:read   - View thread
- threads:write  - Create/update thread
- threads:delete - Delete thread
- runs:create   - Run agent
- runs:read     - View run
- runs:cancel   - Cancel run
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from fastapi import HTTPException, Request

from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider, AuthzDecision, AuthzRequest, Principal
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.authorization_config import AuthorizationConfig

if TYPE_CHECKING:
    from app.gateway.auth.models import User
    from deerflow.config.app_config import AppConfig

P = ParamSpec("P")
T = TypeVar("T")
logger = logging.getLogger(__name__)


# Permission constants
class Permissions:
    """Permission constants for resource:action format."""

    # Threads
    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"

    # Runs
    RUNS_CREATE = "runs:create"
    RUNS_READ = "runs:read"
    RUNS_CANCEL = "runs:cancel"
    # Projects
    PROJECTS_READ = "projects:read"
    PROJECTS_WRITE = "projects:write"
    PROJECTS_DELETE = "projects:delete"
    # Clients
    CLIENTS_READ = "clients:read"
    CLIENTS_WRITE = "clients:write"
    CLIENTS_DELETE = "clients:delete"
    # Momo Board
    BOARD_READ = "board:read"
    BOARD_WRITE = "board:write"
    # Momentum-internal: team channels and AI Academy (staff only)
    TEAM_READ = "team:read"
    TEAM_WRITE = "team:write"
    ACADEMY_READ = "academy:read"
    ACADEMY_WRITE = "academy:write"
    # Approvals inbox: review/approve outbound actions agents proposed
    APPROVALS_READ = "approvals:read"
    APPROVALS_WRITE = "approvals:write"
    # Fleet hosts: claim, renew, finalize and release fleet-executed batch items
    FLEET_WORK = "fleet:work"


class AuthContext:
    """Authentication context for the current request.

    Stored in request.state.auth after require_auth decoration.

    Attributes:
        user: The authenticated user, or None if anonymous
        permissions: List of permission strings (e.g., "threads:read")
        organization_id: Active server-resolved organization for session/PAT callers
        actor_user_id: Authenticated human identity, retained for audit/credentials
        storage_user_id: Server-selected content storage principal
    """

    __slots__ = ("user", "permissions", "organization_id", "actor_user_id", "storage_user_id", "organization_role")

    def __init__(
        self,
        user: User | None = None,
        permissions: list[str] | None = None,
        organization_id: str | None = None,
        *,
        actor_user_id: str | None = None,
        storage_user_id: str | None = None,
        organization_role: str | None = None,
    ):
        self.user = user
        self.permissions = permissions or []
        self.organization_id = organization_id
        self.actor_user_id = actor_user_id
        self.storage_user_id = storage_user_id
        self.organization_role = organization_role

    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self.user is not None

    def has_permission(self, resource: str, action: str) -> bool:
        """Check if context has permission for resource:action.

        Args:
            resource: Resource name (e.g., "threads")
            action: Action name (e.g., "read")

        Returns:
            True if user has permission
        """
        permission = f"{resource}:{action}"
        return permission in self.permissions

    def require_user(self) -> User:
        """Get user or raise 401.

        Raises:
            HTTPException 401 if not authenticated
        """
        if not self.user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.user


def get_auth_context(request: Request) -> AuthContext | None:
    """Get AuthContext from request state."""
    return getattr(request.state, "auth", None)


def require_cancel_permission_if(request: Request, can_cancel: bool) -> None:
    """Require ``runs:cancel`` when a request carries cancel capability.

    Cancel capability reaches the run lifecycle through more than the dedicated
    cancel route: ``?action=interrupt|rollback`` on the join-stream entry and
    ``multitask_strategy=interrupt|rollback`` on run creation both terminate an
    already-active run. A credential whose scopes omit ``runs:cancel`` (e.g. a
    create- or read-only PAT) must not reach any of those paths, and
    decorators cannot express query- or body-parameter-conditional
    permissions, so callers apply this check where the capability is known.

    ``request.state.auth`` may be absent in middleware-less compositions
    (unit-test stubs, auth-disabled startup); the shipped Gateway always
    stamps it via ``AuthMiddleware`` before handlers run.
    """
    if not can_cancel:
        return
    auth = getattr(request.state, "auth", None)
    if auth is not None and not auth.has_permission("runs", "cancel"):
        raise HTTPException(status_code=403, detail="Permission denied: runs:cancel")


_ALL_PERMISSIONS: list[str] = [
    Permissions.THREADS_READ,
    Permissions.THREADS_WRITE,
    Permissions.THREADS_DELETE,
    Permissions.RUNS_CREATE,
    Permissions.RUNS_READ,
    Permissions.RUNS_CANCEL,
    Permissions.PROJECTS_READ,
    Permissions.PROJECTS_WRITE,
    Permissions.PROJECTS_DELETE,
    Permissions.CLIENTS_READ,
    Permissions.CLIENTS_WRITE,
    Permissions.CLIENTS_DELETE,
    Permissions.BOARD_READ,
    Permissions.BOARD_WRITE,
    Permissions.TEAM_READ,
    Permissions.TEAM_WRITE,
    Permissions.ACADEMY_READ,
    Permissions.ACADEMY_WRITE,
    Permissions.APPROVALS_READ,
    Permissions.APPROVALS_WRITE,
    Permissions.FLEET_WORK,
]


def _make_test_request_stub() -> Any:
    """Create a minimal request-like object for direct unit calls.

    Used when decorated route handlers are invoked without FastAPI's
    request injection. Includes fields accessed by auth helpers.
    """
    return SimpleNamespace(state=SimpleNamespace(), cookies={}, _deerflow_test_bypass_auth=True)


def _get_route_authorization_config() -> AuthorizationConfig:
    """Return the hot-reloaded authorization config for this request.

    Falls back to a disabled config when AppConfig is not available (e.g. test
    environments without a config.yaml), preserving legacy all-permissions behavior.
    """
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().authorization
    except (FileNotFoundError, RuntimeError):
        return AuthorizationConfig()


# --- Provider cache (W1/F1) ---
# Keyed by config object identity (id) so the expensive model_dump() signature
# is only recomputed when get_app_config() returns a new object (hot-reload).
_route_provider_cache: dict[str, AuthorizationProvider] = {}
_route_provider_config_id: int | None = None
_route_provider_config_sig: str | None = None


def _get_cached_route_provider(config: AuthorizationConfig) -> AuthorizationProvider | None:
    """Resolve (or reuse) the authorization provider for route permissions.

    The provider is cached per config object identity. When ``get_app_config()``
    returns a new object (hot-reload), the signature is recomputed and compared;
    only an actual content change triggers re-resolution. This avoids calling
    ``model_dump()`` on every request — the fast path is a single ``id()`` check.
    """
    global _route_provider_config_id, _route_provider_config_sig, _route_provider_cache

    config_id = id(config)

    # Fast path: same config object as last time → return cached provider.
    if config_id == _route_provider_config_id and _route_provider_cache:
        return _route_provider_cache.get("provider")

    # Config object changed (hot-reload): compute signature to check if
    # content actually changed or just the wrapper object identity.
    sig = repr(sorted(config.model_dump().items()))
    if sig == _route_provider_config_sig and _route_provider_cache:
        # Same content, different object — update id, reuse provider.
        _route_provider_config_id = config_id
        return _route_provider_cache.get("provider")

    # Content changed (or first call): re-resolve into a local first,
    # then publish id + sig + provider together to avoid a race window.
    _route_provider_cache.clear()

    provider = resolve_authorization_provider(config)
    if provider is not None:
        _route_provider_cache["provider"] = provider
    _route_provider_config_id = config_id
    _route_provider_config_sig = sig
    return provider


async def resolve_route_permissions(user: User, *, is_internal: bool) -> list[str]:
    """Return the route permissions granted to an authenticated user.

    Disabled authorization preserves the legacy all-permissions behavior.
    When enabled, every registered ``resource:action`` permission is evaluated
    independently so a provider failure affects only the route being checked.
    Provider instances are cached per config signature (hot-reload safe).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return list(_ALL_PERMISSIONS)

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for Gateway routes", exc_info=True)
        return [] if config.fail_closed else list(_ALL_PERMISSIONS)

    # Align with Phase 1B's tool path: internal callers (IM channel workers,
    # scheduler) have system_role="internal", which is not a real RBAC role.
    # Omit it so default_role applies, mirroring inject_authenticated_user_context
    # which pops user_role for internal callers without a resolved owner.
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None

    principal = build_principal_from_context(
        {
            "user_id": str(user.id),
            "user_role": user_role,
            "oauth_provider": getattr(user, "oauth_provider", None),
            "oauth_id": getattr(user, "oauth_id", None),
            "is_internal": is_internal,
        },
        default_role=config.default_role,
    )

    # Evaluate all permissions in parallel (W2).
    async def _evaluate(permission: str) -> str | None:
        _, action = permission.split(":", maxsplit=1)
        request = AuthzRequest(
            principal=principal,
            resource="route",
            action=action,
            target=permission,
        )
        try:
            decision = await provider.aauthorize(request)
            if not isinstance(decision, AuthzDecision):
                raise TypeError("AuthorizationProvider.aauthorize must return AuthzDecision")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Authorization provider failed while evaluating route permission %s",
                permission,
                exc_info=True,
            )
            return permission if not config.fail_closed else None
        return permission if decision.allow else None

    results = await asyncio.gather(*[_evaluate(p) for p in _ALL_PERMISSIONS])
    return [p for p in results if p is not None]


async def resolve_route_permissions_for_request(request: Request, user: Any) -> list[str]:
    """Resolve the effective route permissions for a request's authenticated user.

    Public wrapper pairing ``resolve_route_permissions`` with the internal-caller
    heuristics of ``_is_internal_caller`` (auth source, synthetic internal role,
    internal auth header), so middleware-less consumers resolve exactly what
    ``_authenticate`` resolves and the two cannot drift apart.
    """
    return await resolve_route_permissions(user, is_internal=_is_internal_caller(request, user))


def role_has_policy(role: str) -> bool:
    """Whether *role* has a policy block, so assigning it cannot lock the user out.

    False only when RBAC is enabled and certain to treat *role* as undefined (it
    would then fail closed on every check). A disabled or unresolvable provider
    answers True: there is no role table to be missing from.
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return True
    try:
        provider = _get_cached_route_provider(config)
    except Exception:
        return True
    validate_role = getattr(provider, "validate_role", None)
    if validate_role is None:
        return True
    try:
        validate_role(role)
    except ValueError:
        return False
    return True


class _AuthorizationUnavailable(Exception):
    """Raised internally when the provider cannot be resolved for a route check.

    Carries the ``fail_closed`` flag so the caller can decide between deny-all
    and legacy allow-all without re-reading config.
    """

    def __init__(self, *, fail_closed: bool) -> None:
        self.fail_closed = fail_closed


def _resolve_route_scoped_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for route-level resource authorization.

    When authorization is disabled, returns ``(None, None)`` so callers can
    short-circuit to legacy behavior (resource visible). When enabled,
    resolves the cached provider and builds a Principal identical to
    ``resolve_route_permissions`` (including the ``INTERNAL_SYSTEM_ROLE``
    → ``None`` pop so internal callers fall under ``default_role``).

    Raises ``_AuthorizationUnavailable`` (carrying the ``fail_closed`` flag)
    when the provider cannot be resolved; callers translate that into the
    appropriate deny response (empty list / 403).
    """
    config = _get_route_authorization_config()
    if config.enabled is not True:
        return None, None

    try:
        provider = _get_cached_route_provider(config)
        if provider is None:
            raise ValueError("authorization is enabled but provider resolution returned None")
    except Exception:
        logger.warning("Failed to resolve authorization provider for route-level resources", exc_info=True)
        raise _AuthorizationUnavailable(fail_closed=config.fail_closed)

    principal = build_principal_from_context(
        _route_authz_context(user, is_internal=is_internal),
        default_role=config.default_role,
    )
    return provider, principal


def resolve_model_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for model-route authorization.

    Delegates to ``_resolve_route_scoped_authorization``: disabled →
    ``(None, None)``; provider-resolution failure raises
    ``_AuthorizationUnavailable`` (carrying ``fail_closed``).
    """
    return _resolve_route_scoped_authorization(user, is_internal=is_internal)


def model_use_allowed(user: User, model_name: str, *, is_internal: bool, fail_closed: bool) -> bool:
    """Whether *user*'s role may ``use`` *model_name* (``authorize("model", "use")``).

    Disabled authorization allows. A provider that cannot be resolved or that
    raises answers ``not fail_closed``. Shared by ``GET /api/models/{name}`` and
    the built-in-agent visibility checks so they can never disagree.
    """
    try:
        provider, principal = resolve_model_authorization(user, is_internal=is_internal)
    except _AuthorizationUnavailable:
        return not fail_closed
    if provider is None or principal is None:
        return True
    try:
        decision = provider.authorize(AuthzRequest(principal=principal, resource="model", action="use", target=model_name))
        if not isinstance(decision, AuthzDecision):
            raise TypeError("AuthorizationProvider.authorize must return AuthzDecision")
        return decision.allow
    except Exception:
        logger.warning("Authorization provider failed while checking model:use for %s", model_name, exc_info=True)
        return not fail_closed


def resolve_skill_authorization(user: User, *, is_internal: bool) -> tuple[AuthorizationProvider | None, Principal | None]:
    """Return ``(provider, principal)`` for skill-route authorization.

    Same resolution and Principal construction as ``resolve_model_authorization``
    (disabled → ``(None, None)``; provider-resolution failure raises
    ``_AuthorizationUnavailable`` carrying ``fail_closed``). Consumers translate
    that into the appropriate deny response (empty skill listing).
    """
    return _resolve_route_scoped_authorization(user, is_internal=is_internal)


def _route_authz_context(user: User, *, is_internal: bool) -> dict:
    """Build the shared Principal context dict for a request-scoped user.

    Applies the ``INTERNAL_SYSTEM_ROLE → None`` pop so internal callers fall
    under ``default_role`` (mirrors ``inject_authenticated_user_context``).
    Used by ``_resolve_route_scoped_authorization`` (model/skill routes) and
    ``authorize_sandbox_for_request`` so every route-level authorization path
    builds the identity the same way.
    """
    from app.gateway.internal_auth import INTERNAL_SYSTEM_ROLE

    user_role = getattr(user, "system_role", None)
    if user_role == INTERNAL_SYSTEM_ROLE:
        user_role = None
    return {
        "user_id": str(user.id),
        "user_role": user_role,
        "oauth_provider": getattr(user, "oauth_provider", None),
        "oauth_id": getattr(user, "oauth_id", None),
        "is_internal": is_internal,
    }


def authorize_sandbox_for_request(
    user: User,
    *,
    is_internal: bool,
    app_config: AppConfig | None,
) -> None:
    """Check ``sandbox:execute`` for a Gateway request before sandbox acquisition.

    Thin wrapper over the harness-level ``authorize_sandbox_execution`` that
    builds the Principal from the request-scoped ``user`` — the same identity
    construction as ``resolve_model_authorization`` (including the
    ``INTERNAL_SYSTEM_ROLE → None`` pop). Raises
    :class:`~deerflow.sandbox.exceptions.SandboxAuthorizationError` on deny or
    on provider-resolution failure under ``fail_closed``; callers translate
    that into skipping the sandbox sync (not an HTTP error, since the primary
    operation — e.g. file upload — can proceed without it).

    No-op when ``authorization.enabled`` is false.
    """
    from deerflow.authz.sandbox_authz import authorize_sandbox_execution
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    config = _get_route_authorization_config()
    if config.enabled is not True:
        return

    context = _route_authz_context(user, is_internal=is_internal)

    try:
        authorize_sandbox_execution(
            context=context,
            app_config=app_config,
        )
    except SandboxAuthorizationError:
        raise
    except Exception:
        # Defense-in-depth: provider resolution and authorize() errors are
        # already converted to SandboxAuthorizationError (or allowed under
        # fail-open) one layer down inside authorize_sandbox_execution, so this
        # normally only catches config-read failures here (e.g. get_config()
        # raising in a config-less environment). Those must not 500 the
        # upload/artifact route — degrade per fail_closed instead.
        logger.warning("Failed to resolve authorization provider for sandbox:execute", exc_info=True)
        if config.fail_closed:
            raise SandboxAuthorizationError(role=context.get("user_role")) from None


@dataclass(slots=True)
class SandboxRequestLease:
    """One Gateway request's process-local use of a sandbox client."""

    sandbox: object | None
    sandbox_id: str | None
    denied: bool
    owner_id: str | None
    provider: object | None

    async def release(self) -> None:
        """Drop the request holder without bypassing concurrent executions."""
        if self.owner_id is None or self.provider is None:
            return
        from deerflow.sandbox.lease import get_sandbox_lease_manager

        owner_id = self.owner_id
        self.owner_id = None
        await get_sandbox_lease_manager(self.provider).release_async(owner_id)


async def try_acquire_sandbox_for_request(
    request: Request,
    sandbox_provider,
    thread_id: str,
    *,
    user_id: str,
    app_config: AppConfig | None,
    owner_prefix: str = "gateway",
    release_on_last: bool = True,
) -> SandboxRequestLease:
    """Gate + acquire the thread sandbox for a Gateway sync path.

    Single entry point for the uploads/artifacts sandbox-sync paths so the
    deny/skip semantics live in one place: runs the ``sandbox:execute`` gate
    for the request's user, then acquires the sandbox under a unique request
    holder. Callers must await :meth:`SandboxRequestLease.release` after their
    last client operation.

    - denied role → no sandbox/owner and ``denied=True``: acquisition was skipped by policy;
      the primary operation (upload / artifact edit) proceeds without the
      sandbox copy.
    - allowed → ``sandbox`` is the acquired instance, or ``sandbox is None`` when
      the provider lost it right after acquiring (infrastructure error —
      callers surface it as 500 / RuntimeError respectively, since that is
      not a policy decision).
    - ``request is None`` (direct-call tests) and unresolvable users skip the
      gate — same fail-open semantics as the models routes' anonymous bypass.
    """
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    try:
        from app.gateway.deps import get_optional_user_from_request

        user = await get_optional_user_from_request(request) if request is not None else None
        if user is not None:
            authorize_sandbox_for_request(user, is_internal=_is_internal_caller(request, user), app_config=app_config)
    except SandboxAuthorizationError:
        logger.info("Sandbox sync skipped: sandbox execution not permitted for this caller (thread_id=%s)", thread_id)
        return SandboxRequestLease(
            sandbox=None,
            sandbox_id=None,
            denied=True,
            owner_id=None,
            provider=None,
        )

    from deerflow.sandbox.lease import get_sandbox_lease_manager

    owner_id = f"{owner_prefix}:{uuid.uuid4()}"
    sandbox_id = await get_sandbox_lease_manager(sandbox_provider).acquire_async(
        owner_id,
        thread_id,
        user_id=user_id,
        release_on_last=release_on_last,
    )
    return SandboxRequestLease(
        sandbox=sandbox_provider.get(sandbox_id),
        sandbox_id=sandbox_id,
        denied=False,
        owner_id=owner_id,
        provider=sandbox_provider,
    )


async def _authenticate(request: Request) -> AuthContext:
    """Authenticate request and return AuthContext.

    Delegates to deps.get_optional_user_from_request() for the JWT→User pipeline.
    Returns AuthContext with user=None for anonymous requests.
    """
    from app.gateway.deps import get_optional_user_from_request

    user = await get_optional_user_from_request(request)
    if user is None:
        return AuthContext(user=None, permissions=[])

    permissions = await resolve_route_permissions_for_request(request, user)
    return AuthContext(user=user, permissions=permissions)


def _is_internal_caller(request: Request, user: Any) -> bool:
    """Determine if the request originates from a trusted internal caller.

    Checks three signals (any one suffices):
    1. ``request.state.auth_source == AUTH_SOURCE_INTERNAL`` (set by AuthMiddleware).
    2. ``user.system_role == INTERNAL_SYSTEM_ROLE`` (synthetic internal user).
    3. The request carries a valid internal auth token header (decorator-only path
       where AuthMiddleware may not have stamped ``auth_source`` yet).
    """
    from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
    from app.gateway.internal_auth import INTERNAL_AUTH_HEADER_NAME, INTERNAL_SYSTEM_ROLE, is_valid_internal_auth_token

    if getattr(getattr(request, "state", None), "auth_source", None) == AUTH_SOURCE_INTERNAL:
        return True
    if getattr(user, "system_role", None) == INTERNAL_SYSTEM_ROLE:
        return True
    # Decorator-only path: check the internal token header directly.
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER_NAME) if hasattr(request, "headers") else None
    if internal_token and is_valid_internal_auth_token(internal_token):
        return True
    return False


def require_auth[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Decorator that authenticates the request and enforces authentication.

    Independently raises HTTP 401 for unauthenticated requests, regardless of
    whether ``AuthMiddleware`` is present in the ASGI stack. Sets the resolved
    ``AuthContext`` on ``request.state.auth`` for downstream handlers.

    Must be placed ABOVE other decorators (executes after them).

    Usage:
        @router.get("/{thread_id}")
        @require_auth  # Bottom decorator (executes first after permission check)
        @require_permission("threads", "read")
        async def get_thread(thread_id: str, request: Request):
            auth: AuthContext = request.state.auth
            ...

    Raises:
        HTTPException: 401 if the request is unauthenticated.
        ValueError: If 'request' parameter is missing.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request")
        if request is None:
            # Unit tests may call decorated handlers directly without a
            # FastAPI Request object. Inject a minimal request stub when
            # the wrapped function declares `request`.
            if "request" in inspect.signature(func).parameters:
                kwargs["request"] = _make_test_request_stub()
            else:
                raise ValueError("require_auth decorator requires 'request' parameter")
            request = kwargs["request"]

        if getattr(request, "_deerflow_test_bypass_auth", False):
            return await func(*args, **kwargs)

        # Authenticate and set context
        auth_context = await _authenticate(request)
        request.state.auth = auth_context

        if not auth_context.is_authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")

        return await func(*args, **kwargs)

    return wrapper


def require_permission(
    resource: str,
    action: str,
    owner_check: bool = False,
    require_existing: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that checks permission for resource:action.

    Must be used AFTER @require_auth.

    Args:
        resource: Resource name (e.g., "threads", "runs")
        action: Action name (e.g., "read", "write", "delete")
        owner_check: If True, validates that the current user owns the resource.
                     Requires 'thread_id' path parameter and performs ownership check.
        require_existing: Only meaningful with ``owner_check=True``. If True, a
                          missing ``threads_meta`` row counts as a denial (404)
                          instead of "untracked legacy thread, allow". Use on
                          **destructive / mutating** routes (DELETE, PATCH,
                          state-update) so a deleted thread can't be re-targeted
                          by another user via the missing-row code path.

    Usage:
        # Read-style: legacy untracked threads are allowed
        @require_permission("threads", "read", owner_check=True)
        async def get_thread(thread_id: str, request: Request):
            ...

        # Destructive: thread row MUST exist and be owned by caller
        @require_permission("threads", "delete", owner_check=True, require_existing=True)
        async def delete_thread(thread_id: str, request: Request):
            ...

    Raises:
        HTTPException 401: If authentication required but user is anonymous
        HTTPException 403: If user lacks permission
        HTTPException 404: If owner_check=True but user doesn't own the thread
        ValueError: If owner_check=True but 'thread_id' parameter is missing
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                # Unit tests may call decorated route handlers directly — with
                # or without constructing a FastAPI Request object — and may
                # pass ``request`` positionally. Bind to the real signature
                # first so a positional request is found rather than
                # duplicated by the stub injection below.
                try:
                    bound = inspect.signature(func).bind_partial(*args, **kwargs)
                except TypeError:
                    bound = None
                if bound is not None and "request" in bound.arguments:
                    request = bound.arguments["request"]
                elif "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                    request = kwargs["request"]
                else:
                    return await func(*args, **kwargs)

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            auth: AuthContext = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            # Check permission
            if not auth.has_permission(resource, action):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {resource}:{action}",
                )

            # Owner check for thread-specific resources.
            #
            # 2.0-rc moved thread metadata into the SQL persistence layer
            # (``threads_meta`` table). We verify ownership via
            # ``ThreadMetaStore.check_access``: it returns True for
            # missing rows (untracked legacy thread) and for rows whose
            # ``user_id`` is NULL (shared / pre-auth data), so this is
            # strict-deny rather than strict-allow — only an *existing*
            # row with a *different* user_id triggers 404.
            if owner_check:
                thread_id = kwargs.get("thread_id")
                if thread_id is None:
                    raise ValueError("require_permission with owner_check=True requires 'thread_id' parameter")

                from app.gateway.deps import get_thread_store

                thread_store = get_thread_store(request)
                # Internal callers get no owner-header fallback: AuthMiddleware
                # already stamped a delegated caller's storage principal here,
                # and an undelegated one never reaches a route.
                storage_user_id = auth.storage_user_id or str(auth.user.id)
                allowed = await thread_store.check_access(
                    thread_id,
                    storage_user_id,
                    require_existing=require_existing,
                )
                if not allowed:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Thread {thread_id} not found",
                    )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def resource_permission_dependency(resource: str):
    """Enforce HTTP read/write/delete scopes for request-free CRUD handlers.

    Router dependencies run with the real HTTP request even when a handler's
    ``request`` parameter is its Pydantic body. Reuse the normal authorization
    check rather than treating route admission as a grant of every action.
    """
    checks = {}
    for action in ("read", "write", "delete"):

        async def permitted(request: Request) -> None:
            return None

        checks[action] = require_permission(resource, action)(permitted)

    async def dependency(request: Request) -> None:
        action = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "delete" if request.method == "DELETE" else "write"
        await checks[action](request=request)

    return dependency


def require_entitlement(
    key: str,
    *,
    requested_amount: int = 1,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator enforcing the M4 entitlement gate for a paid mutation.

    Design: ``docs/momo-week/m4-entitlement.md`` §3, §7.3 (task ``c2``/``e6``).
    Must be composed AFTER ``@require_permission`` (i.e. placed BELOW it in
    the decorator stack, so it executes second) — it reads
    ``request.state.auth.organization_id``, which only ``AuthMiddleware`` or
    ``require_permission``'s own ``_authenticate()`` populate. No router in
    this codebase uses ``@require_auth`` today, and stacking it back in above
    this decorator would wipe that org context right before it's needed.

    Only suitable for a gate key (no attempted-count needed). A limit key
    (``projects.max`` etc.) needs the caller's live usage count from the
    request body, so those routes call ``evaluate_entitlement(...)`` inline
    in the handler instead — the same "decorator for the common case, inline
    call for the parametrized case" split ``board.py`` already uses for
    ``_require_client_access``.

    Raises:
        HTTPException 401: If unauthenticated.
        HTTPException 403: If entitlements are enabled and the key is denied
            (no resolved organization, no row, or a suspended row). The body
            is ``{"error": "entitlement_exceeded", "key": ..., "reason": ...}``
            so the frontend can show upgrade copy instead of a bare
            permission error.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                try:
                    bound = inspect.signature(func).bind_partial(*args, **kwargs)
                except TypeError:
                    bound = None
                if bound is not None and "request" in bound.arguments:
                    request = bound.arguments["request"]
                elif "request" in inspect.signature(func).parameters:
                    kwargs["request"] = _make_test_request_stub()
                    request = kwargs["request"]
                else:
                    return await func(*args, **kwargs)

            if getattr(request, "_deerflow_test_bypass_auth", False):
                return await func(*args, **kwargs)

            from deerflow.config.entitlement_config import resolve_current_entitlement_config

            entitlement_config = resolve_current_entitlement_config()
            if not entitlement_config.enabled:
                return await func(*args, **kwargs)

            auth: AuthContext | None = getattr(request.state, "auth", None)
            if auth is None:
                auth = await _authenticate(request)
                request.state.auth = auth

            if not auth.is_authenticated:
                raise HTTPException(status_code=401, detail="Authentication required")

            from app.gateway.deps import get_entitlement_repo
            from deerflow.authz.entitlements import evaluate_entitlement

            repo = get_entitlement_repo(request)
            decision = await evaluate_entitlement(
                repo,
                auth.organization_id,
                key,
                requested_amount=requested_amount,
                config=entitlement_config,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "entitlement_exceeded", "key": key, "reason": decision.reason},
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
````

## backend/app/gateway/auth_middleware.py

````python
"""Global authentication middleware — fail-closed safety net.

Rejects unauthenticated requests to non-public paths with 401. When a
request passes the cookie check, resolves the JWT payload to a real
``User`` object and stamps it into both ``request.state.user`` and the
``deerflow.runtime.user_context`` contextvar so that repository-layer
owner filtering works automatically via the sentinel pattern.

Fine-grained permission checks remain in authz.py decorators.
"""

import logging
import re
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME
from app.gateway.auth_disabled import (
    AUTH_SOURCE_AUTH_DISABLED,
    AUTH_SOURCE_INTERNAL,
    AUTH_SOURCE_PAT,
    AUTH_SOURCE_SESSION,
    get_auth_disabled_user,
    is_auth_disabled,
)
from app.gateway.authz import AuthContext, resolve_route_permissions
from app.gateway.client_boundary import CLIENT_ROLE, is_client_allowed_route
from app.gateway.internal_auth import (
    INTERNAL_AUTH_HEADER_NAME,
    INTERNAL_DELEGATION_ID_HEADER_NAME,
    INTERNAL_OWNER_USER_ID_HEADER_NAME,
    get_internal_user,
    is_valid_internal_auth_token,
)
from app.gateway.request_path import get_request_route_path
from deerflow.persistence.organizations.delegation import ActiveDelegation
from deerflow.persistence.organizations.resolution import ActiveOrganization, storage_user_id_for_organization
from deerflow.runtime.user_context import (
    WorkspaceStorageContext,
    reset_current_user,
    reset_storage_context,
    set_current_user,
    set_storage_context,
)

logger = logging.getLogger(__name__)

WORKSPACE_COOKIE_NAME = "deerflow_workspace"
_WORKSPACE_AUTH_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/",
    "/api/integrations",
    # Workspace discovery and explicit selection must stay on the actor's
    # private organization so a stale/revoked cookie can be cleared safely.
    "/api/workspaces",
)
# Kept for callers/tests that imported the original single-prefix seam.
_WORKSPACE_AUTH_EXEMPT_PREFIX = "/api/v1/auth/"

# Personal access tokens are themselves an organization-scoped resource (M3,
# migration 0037_pat_organization): unlike genuine credential-management
# routes (login, password change, MFA, invitations -- which must stay pinned
# to the actor's identity regardless of any cookie), PAT create/list/revoke
# is carved out of the blanket ``/api/v1/auth/`` exemption above so the
# session's active organization (the workspace-selection cookie) selects
# which organization a PAT is minted for, listed from, or revoked in -- the
# same ``organization_for_write`` treatment every other M3 resource gets.
# This is safe precisely because organization selection is fail-closed
# (``active_organization_for_user`` re-verifies active membership before any
# row is stamped or returned): a stale/forged cookie naming an organization
# the caller cannot prove membership in 403s the whole request rather than
# widening it.
_PAT_MANAGEMENT_PREFIX = "/api/v1/auth/pats"

# Paths that never require authentication.
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/oauth/",
    "/api/v1/auth/callback/",
    # Inbound webhooks authenticate themselves via provider-specific signatures
    # (e.g. GitHub's X-Hub-Signature-256), not session cookies.
    "/api/webhooks/",
)

# Exact auth paths that are public (login/register/status check).
# /api/v1/auth/me, /api/v1/auth/change-password etc. are NOT public.
_PUBLIC_EXACT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/login/local",
        # The caller holds only the single-use challenge from login/local's
        # mfa_required response, not a session yet -- the challenge itself
        # (signed, short-lived, attempt-limited) is the auth boundary here.
        "/api/v1/auth/login/mfa",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
        "/api/v1/auth/initialize",
        "/api/v1/auth/providers",
        # Invitation inspection and acceptance happen before the recipient has
        # a session.  Creation/revocation routes remain protected by the
        # normal middleware and invitation router permissions.
        "/api/v1/auth/invitations/inspect",
        "/api/v1/auth/invitations/accept",
    }
)


def _is_public(path: str) -> bool:
    stripped = path.rstrip("/")
    if stripped in _PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PATH_PREFIXES)


async def _resolve_active_workspace(user_id: str, selected_organization_id: str | None) -> ActiveOrganization | None:
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.resolution import active_organization_for_user

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    # Keep the existing private-org gate as the compatibility seam used by
    # deployments/tests that override it. A missing private membership is a
    # hard denial; a cookie-selected workspace is resolved independently.
    if selected_organization_id is None:
        private_id = await _resolve_active_private_organization_id(user_id)
        if private_id is None:
            return None
    async with session_factory() as session:
        return await active_organization_for_user(session, user_id, selected_organization_id or private_id)


async def _resolve_active_private_organization_id(user_id: str) -> str | None:
    """Backward-compatible private-org membership resolver."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.resolution import active_private_organization_for_user

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    async with session_factory() as session:
        return await active_private_organization_for_user(session, user_id)


_DELEGATION_REQUIRED_DETAIL = "Internal calls require an active organization delegation"


async def _resolve_internal_delegation(delegation_id: str | None) -> ActiveDelegation | None:
    """Resolve an internal caller's delegation by id; ``None`` denies."""
    if not delegation_id:
        return None
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.organizations.delegation import OrganizationDelegationRepository

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("organization authorization requires a configured database")
    return await OrganizationDelegationRepository(session_factory).resolve_delegation_by_id(delegation_id)


def _workspace_selection_for_request(request: Request, auth_source: str) -> str | None:
    """Return a cookie-selected organization only for browser session calls.

    Credential-management routes always stay on the actor's private
    organization, preventing an ambient browser cookie from widening a
    bearer-token request or changing account semantics. PAT management
    (``/api/v1/auth/pats``) is carved out of that exemption: a PAT is itself
    an organization-scoped resource, so its active organization is selected
    the same way every other M3 resource's is (see ``_PAT_MANAGEMENT_PREFIX``).
    """
    if auth_source != AUTH_SOURCE_SESSION:
        return None
    path = get_request_route_path(request)
    composio_path = path in {"/api/integrations/connect", "/api/integrations/callback", "/api/integrations/status"} or re.fullmatch(r"/api/integrations/connect/[A-Za-z0-9_-]{24}/open", path) is not None
    if not path.startswith(_PAT_MANAGEMENT_PREFIX) and not composio_path and any(path.startswith(prefix) for prefix in _WORKSPACE_AUTH_EXEMPT_PREFIXES):
        return None
    selected = request.cookies.get(WORKSPACE_COOKIE_NAME)
    return selected.strip() if selected and selected.strip() else None


class AuthMiddleware(BaseHTTPMiddleware):
    """Strict auth gate: reject requests without a valid session.

    Two-stage check for non-public paths:

    1. Cookie presence — return 401 NOT_AUTHENTICATED if missing
    2. JWT validation via ``get_optional_user_from_request`` — return 401
       TOKEN_INVALID if the token is absent, malformed, expired, or the
       signed user does not exist / is stale

    On success, stamps ``request.state.user`` and the
    ``deerflow.runtime.user_context`` contextvar so that repository-layer
    owner filters work downstream without every route needing a
    ``@require_auth`` decorator. Routes that need per-resource
    authorization (e.g. "user A cannot read user B's thread by guessing
    the URL") should additionally use ``@require_permission(...,
    owner_check=True)`` for explicit enforcement — but authentication
    itself is fully handled here.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if _is_public(get_request_route_path(request)):
            return await call_next(request)

        internal_user = None
        delegation: ActiveDelegation | None = None
        if is_valid_internal_auth_token(request.headers.get(INTERNAL_AUTH_HEADER_NAME)):
            owner_user_id = (request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) or "").strip() or None
            if is_auth_disabled():
                # Operator override of all authentication (dev/E2E only):
                # keep the legacy synthetic identity.
                internal_user = get_internal_user(owner_user_id=owner_user_id)
            else:
                # Contract section 4: an internal token (plus an owner header)
                # is never enough by itself. The caller names its delegation;
                # it must be active, unexpired, owned by an active member of an
                # active organization, and name the same owner as the header.
                delegation_id = (request.headers.get(INTERNAL_DELEGATION_ID_HEADER_NAME) or "").strip() or None
                try:
                    delegation = await _resolve_internal_delegation(delegation_id)
                except Exception:
                    logger.exception("Could not resolve the delegation of an internal request")
                    return JSONResponse(status_code=503, content={"detail": "Organization authorization is unavailable"})
                if delegation is None or (owner_user_id is not None and owner_user_id != delegation.owner_user_id):
                    logger.warning(
                        "Rejected internal call without a matching active delegation: path=%s delegation_id=%s owner_header=%s",
                        get_request_route_path(request),
                        "present" if delegation_id else "missing",
                        "present" if owner_user_id else "missing",
                    )
                    return JSONResponse(status_code=403, content={"detail": _DELEGATION_REQUIRED_DETAIL})
                internal_user = get_internal_user(owner_user_id=delegation.owner_user_id)

        auth_source = AUTH_SOURCE_SESSION
        access_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
        authorization = request.headers.get("authorization")
        pat_scopes: frozenset[str] = frozenset()
        pat_organization_id: str | None = None

        # Non-public path: require session cookie
        if internal_user is not None:
            user = internal_user
            auth_source = AUTH_SOURCE_INTERNAL
        elif authorization is not None and not is_auth_disabled():
            # Bearer (PAT) credential precedence (#4849): a present-but-invalid
            # Authorization header is a hard 401 and never silently falls back
            # to the session cookie. This is also what makes the CSRF
            # middleware's Bearer skip safe — a cross-site attacker cannot ride
            # a victim's cookie by padding the request with a garbage Bearer
            # header, because the request dies here before any route runs.
            # Auth-disabled mode is an operator override of all authentication,
            # so it stays ahead of the Bearer check (a stray Authorization
            # header from a proxy must not 401 an E2E sandbox).
            from app.gateway.auth.pat import authenticate_pat, is_pat_allowed_route
            from deerflow.config.app_config import get_app_config

            try:
                user, pat_scopes, pat_organization_id = await authenticate_pat(request.app, authorization)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            # Default-deny route boundary (#5041 review P1-1): scopes only
            # constrain @require_permission routes, so any route outside the
            # explicit PAT policy is closed to PAT callers outright — an
            # all-scopes token must not reach undecorated mutation routes.
            # private_workspace.enabled additionally gates the fleet/agents/
            # scheduled-task routes (PR #14 review): false on every
            # client-facing MomoBot, so a leaked client PAT cannot create a
            # persistent custom agent or schedule it to run unattended. Fails
            # closed (disabled) on any config-resolution error -- a missing
            # or malformed config.yaml must never crash authenticated
            # requests, and "closed" here means the strictest, safest policy
            # anyway.
            try:
                private_workspace_enabled = get_app_config().private_workspace.enabled
            except Exception:
                private_workspace_enabled = False
            if not is_pat_allowed_route(request.method, get_request_route_path(request), private_workspace_enabled=private_workspace_enabled):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "PAT credentials are not permitted on this route"},
                )
            auth_source = AUTH_SOURCE_PAT
        elif access_token:
            # Strict JWT validation: reject junk/expired tokens with 401
            # right here instead of silently passing through. This closes
            # the "junk cookie bypass" gap (AUTH_TEST_PLAN test 7.5.8):
            # without this, non-isolation routes like /api/models would
            # accept any cookie-shaped string as authentication.
            #
            # We call the *strict* resolver so that fine-grained error
            # codes (token_expired, token_invalid, user_not_found, …)
            # propagate from AuthErrorCode, not get flattened into one
            # generic code. BaseHTTPMiddleware doesn't let HTTPException
            # bubble up, so we catch and render it as JSONResponse here.
            from app.gateway.deps import get_current_user_from_request

            try:
                user = await get_current_user_from_request(request)
            except HTTPException as exc:
                if not is_auth_disabled():
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                user = get_auth_disabled_user()
                auth_source = AUTH_SOURCE_AUTH_DISABLED
        elif is_auth_disabled():
            user = get_auth_disabled_user()
            auth_source = AUTH_SOURCE_AUTH_DISABLED
        else:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": AuthErrorResponse(
                        code=AuthErrorCode.NOT_AUTHENTICATED,
                        message="Authentication required",
                    ).model_dump()
                },
            )

        # Stamp both request.state.user (for the contextvar pattern)
        # and request.state.auth (so @require_permission's "auth is
        # None" branch short-circuits instead of running the entire
        # JWT-decode + DB-lookup pipeline a second time per request).
        request.state.user = user
        request.state.auth_source = auth_source
        # A client (external customer) reaches chat and nothing else; the table
        # is default-deny, so it also closes routes added after it was written.
        if getattr(user, "system_role", None) == CLIENT_ROLE and not is_client_allowed_route(request.method, get_request_route_path(request)):
            return JSONResponse(status_code=403, content={"detail": "This area is not available for your account"})
        organization: ActiveOrganization | None = delegation.organization if delegation is not None else None
        if auth_source in {AUTH_SOURCE_SESSION, AUTH_SOURCE_PAT}:
            # A PAT is pinned to the organization active when it was minted
            # (its own stamped ``organization_id``, migration
            # 0037_pat_organization) — never to a workspace-selection cookie,
            # which only ever applies to interactive sessions. This is what
            # stops a PAT minted in one organization from acting in another
            # even if the bearer request carries a stale/forged workspace
            # cookie, and what makes a since-revoked membership in that
            # organization fail closed below (organization is None -> 403).
            selected_organization_id = pat_organization_id if auth_source == AUTH_SOURCE_PAT else _workspace_selection_for_request(request, auth_source)
            try:
                organization = await _resolve_active_workspace(
                    str(user.id),
                    selected_organization_id,
                )
            except Exception:
                logger.exception("Could not resolve organization authorization for authenticated request")
                return JSONResponse(status_code=503, content={"detail": "Organization authorization is unavailable"})
            if organization is None:
                return JSONResponse(status_code=403, content={"detail": "Active organization membership required"})
        organization_id = organization.id if organization is not None else None
        # A delegated internal call acts as its owner, never the synthetic user.
        actor_user_id = delegation.owner_user_id if delegation is not None else str(user.id)
        storage_user_id = actor_user_id
        organization_role = None
        if organization is not None:
            storage_user_id = storage_user_id_for_organization(organization, actor_user_id) or ""
            organization_role = organization.role
            if not storage_user_id:
                logger.error("Active organization %s has no valid storage principal", organization.id)
                return JSONResponse(status_code=503, content={"detail": "Organization storage is unavailable"})
        request.state.organization_id = organization_id
        request.state.organization_role = organization_role
        request.state.actor_user_id = actor_user_id
        request.state.storage_user_id = storage_user_id
        request.state.delegation_id = delegation.id if delegation is not None else None
        permissions = await resolve_route_permissions(
            user,
            is_internal=auth_source == AUTH_SOURCE_INTERNAL,
        )
        if auth_source == AUTH_SOURCE_PAT:
            # A PAT can only narrow its owning user's permissions: the stored
            # scopes intersect the resolved route permissions, never widen
            # them, and role changes / authorization policy stay authoritative
            # because they were resolved fresh from the owning user above.
            permissions = [permission for permission in permissions if permission in pat_scopes]
        if delegation is not None:
            # A delegation narrows route permissions exactly like PAT scopes.
            permissions = [permission for permission in permissions if permission in delegation.scopes]
        request.state.auth = AuthContext(
            user=user,
            permissions=permissions,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            storage_user_id=storage_user_id,
            organization_role=organization_role,
        )
        token = set_current_user(user)
        storage_token = set_storage_context(
            WorkspaceStorageContext(
                actor_user_id=actor_user_id,
                organization_id=organization_id,
                storage_user_id=storage_user_id,
                role=organization_role,
            )
        )
        try:
            return await call_next(request)
        finally:
            reset_storage_context(storage_token)
            reset_current_user(token)
````

## backend/packages/harness/deerflow/runtime/user_context.py

````python
"""Request-scoped user context for user-based authorization.

This module holds a :class:`~contextvars.ContextVar` that the gateway's
auth middleware sets after a successful authentication. Repository
methods read the contextvar via a sentinel default parameter, letting
routers stay free of ``user_id`` boilerplate.

Three-state semantics for the repository ``user_id`` parameter (the
consumer side of this module lives in ``deerflow.persistence.*``):

- ``_AUTO`` (module-private sentinel, default): read from contextvar;
  raise :class:`RuntimeError` if unset.
- Explicit ``str``: use the provided value, overriding contextvar.
- Explicit ``None``: no WHERE clause — used only by migration scripts
  and admin CLIs that intentionally bypass isolation.

Dependency direction
--------------------
``persistence`` (lower layer) reads from this module; ``gateway.auth``
(higher layer) writes to it. ``CurrentUser`` is defined here as a
:class:`typing.Protocol` so that ``persistence`` never needs to import
the concrete ``User`` class from ``gateway.auth.models``. Any object
with an ``.id: str`` attribute structurally satisfies the protocol.

Asyncio semantics
-----------------
``ContextVar`` is task-local under asyncio, not thread-local. Each
FastAPI request runs in its own task, so the context is naturally
isolated. ``asyncio.create_task`` and ``asyncio.to_thread`` inherit the
parent task's context, which is typically the intended behaviour; if
a background task must *not* see the foreground user, wrap it with
``contextvars.copy_context()`` to get a clean copy.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable


@runtime_checkable
class CurrentUser(Protocol):
    """Structural type for the current authenticated user.

    Any object with an ``.id: str`` attribute satisfies this protocol.
    Concrete implementations live in ``app.gateway.auth.models.User``.
    """

    id: str


_current_user: Final[ContextVar[CurrentUser | None]] = ContextVar("deerflow_current_user", default=None)

# The Gateway stamps these fields after authentication.  The marker is an
# in-process capability: it lets the run worker distinguish the values that
# were written by ``inject_authenticated_user_context`` from a caller's
# ordinary ``RunnableConfig.context`` without persisting a secret or relying
# on a user-controlled boolean.  The worker consumes and removes the marker
# before exposing ``ToolRuntime.context``.
AUTHENTICATED_CONTEXT_MARKER_KEY: Final[str] = "__deerflow_authenticated_context"
AUTHENTICATED_CONTEXT_MARKER: Final[object] = object()

# Keep the private-session capability in this dependency-light auth context.
# Run bootstrap must not import MCP/tool assembly while repositories initialize.
PRIVATE_MCP_SESSION_CONTEXT_KEY: Final[str] = "__deerflow_private_mcp_session"
PRIVATE_MCP_SESSION_MARKER: Final[object] = object()

WORKSPACE_IDENTITY_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "actor_user_id",
        "storage_user_id",
        "organization_id",
        "organization_role",
    }
)


@dataclass(frozen=True, slots=True)
class WorkspaceStorageContext:
    """Server-selected workspace identity for shared resource storage.

    ``actor_user_id`` is the authenticated human. ``storage_user_id`` is the
    owner bucket used by repositories and filesystem paths; it equals the
    actor for private organizations and is a dedicated non-login principal for
    shared workspaces. The two identities must not be conflated.
    """

    actor_user_id: str
    organization_id: str | None
    storage_user_id: str
    role: str | None = None


StorageContext = WorkspaceStorageContext
_storage_context: Final[ContextVar[WorkspaceStorageContext | None]] = ContextVar("deerflow_storage_context", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    """Set the current user for this async task.

    Returns a reset token that should be passed to
    :func:`reset_current_user` in a ``finally`` block to restore the
    previous context.
    """
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    """Restore the context to the state captured by ``token``."""
    _current_user.reset(token)


def get_current_user() -> CurrentUser | None:
    """Return the current user, or ``None`` if unset.

    Safe to call in any context. Used by code paths that can proceed
    without a user (e.g. migration scripts, public endpoints).
    """
    return _current_user.get()


def set_storage_context(context: WorkspaceStorageContext) -> Token[WorkspaceStorageContext | None]:
    """Set the server-validated workspace storage identity for this task."""

    if not context.actor_user_id or not context.storage_user_id:
        raise ValueError("workspace storage context requires actor and storage user ids")
    return _storage_context.set(context)


def reset_storage_context(token: Token[WorkspaceStorageContext | None]) -> None:
    """Restore the previous workspace storage context."""

    _storage_context.reset(token)


def get_storage_context() -> WorkspaceStorageContext | None:
    """Return the server-validated workspace context, if one is active."""

    return _storage_context.get()


def get_workspace_actor_user_id() -> str | None:
    """Return the authenticated actor id without changing storage scoping."""

    context = _storage_context.get()
    if context is not None:
        return context.actor_user_id
    user = _current_user.get()
    return str(user.id) if user is not None else None


def require_current_user() -> CurrentUser:
    """Return the current user, or raise :class:`RuntimeError`.

    Used by repository code that must not be called outside a
    request-authenticated context. The error message is phrased so
    that a caller debugging a stack trace can locate the offending
    code path.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError("repository accessed without user context")
    return user


# ---------------------------------------------------------------------------
# Effective user_id helpers (filesystem isolation)
# ---------------------------------------------------------------------------

DEFAULT_USER_ID: Final[str] = "default"


def get_effective_user_id() -> str:
    """Return the active storage principal, or DEFAULT_USER_ID if unset.

    Unlike :func:`require_current_user` this never raises — it is designed
    for filesystem-path resolution where a valid user bucket is always needed.
    A shared workspace supplies its dedicated principal; private requests fall
    back to the authenticated actor for backwards compatibility.
    """
    context = _storage_context.get()
    if context is not None:
        return context.storage_user_id
    user = _current_user.get()
    if user is None:
        return DEFAULT_USER_ID
    return str(user.id)


def get_effective_storage_user_id() -> str:
    """Explicit spelling for callers that need the workspace storage bucket."""

    return get_effective_user_id()


def get_effective_actor_user_id() -> str:
    """Return the authenticated actor id, with the legacy default fallback."""

    return get_workspace_actor_user_id() or DEFAULT_USER_ID


def resolve_organization_id() -> str | None:
    """Return the request's server-resolved active organization, if any.

    Only ``AuthMiddleware`` sets it, after proving the session or PAT caller's
    active membership, so no request field can choose it. ``None`` (internal
    callers, auth-disabled mode, work outside a request) means no organization
    boundary was established: keep the user filter and add no organization
    filter.
    """
    context = _storage_context.get()
    return context.organization_id if context is not None else None


def _storage_user_id_from_auth_identity(identity: object | None) -> str | None:
    """Return a stable storage-safe ID for a LangGraph auth identity."""
    if not isinstance(identity, str) or not identity:
        return None

    # LangGraph permits arbitrary strings (commonly email addresses) for
    # BaseUser.identity, while DeerFlow's user directories require a narrower
    # charset. Keep the normalization at the auth boundary so graph
    # construction and runtime middleware always select the same bucket.
    from deerflow.config.paths import make_safe_user_id

    return make_safe_user_id(identity)


def _user_id_from_auth_user(user: object | None) -> str | None:
    if isinstance(user, Mapping):
        identity = user.get("identity")
    else:
        identity = getattr(user, "identity", None)
    return _storage_user_id_from_auth_identity(identity)


def _user_id_from_langgraph_config(config: object | None) -> str | None:
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None

    user_id = _storage_user_id_from_auth_identity(configurable.get("langgraph_auth_user_id"))
    if user_id:
        return user_id
    return _user_id_from_auth_user(configurable.get("langgraph_auth_user"))


def resolve_config_user_id(config: object | None) -> str:
    """Resolve the effective user from a LangGraph/Gateway run config.

    Server-owned LangGraph authentication fields take precedence over ordinary
    ``user_id`` values because Agent Server reserves and overwrites the auth
    fields, while a standalone client may supply regular configurable/context
    values. Gateway runtime context remains the next source for DeerFlow's
    embedded run path, followed by the legacy configurable channel and the
    request ContextVar/default fallback.
    """
    # Gateway-injected storage identity is server-owned and must win over the
    # authenticated actor when a selected shared workspace is active.  The
    # in-process marker prevents an arbitrary standalone RunnableConfig from
    # selecting another workspace by naming ``storage_user_id`` directly.
    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            storage_user_id = context.get("storage_user_id")
            if storage_user_id:
                if context.get(AUTHENTICATED_CONTEXT_MARKER_KEY) is AUTHENTICATED_CONTEXT_MARKER:
                    return str(storage_user_id)
                # Once the worker consumes the in-process marker, the
                # middleware's task-local storage context remains the trusted
                # proof for this live run.  Do not infer trust from a caller's
                # actor/org fields; those are ordinary mapping values.
                active_storage = _storage_context.get()
                if active_storage is not None and active_storage.storage_user_id == str(storage_user_id):
                    return str(storage_user_id)

    langgraph_user_id = _user_id_from_langgraph_config(config)
    if langgraph_user_id:
        return langgraph_user_id

    if isinstance(config, Mapping):
        context = config.get("context")
        if isinstance(context, Mapping):
            context_user_id = context.get("user_id")
            if context_user_id:
                return str(context_user_id)

        configurable = config.get("configurable")
        if isinstance(configurable, Mapping):
            configurable_user_id = configurable.get("user_id")
            if configurable_user_id:
                return str(configurable_user_id)

    return get_effective_user_id()


def resolve_runtime_user_id(runtime: object | None) -> str:
    """Single source of truth for a tool/middleware's effective user_id.

    Resolution order (most authoritative first):
      1. server-owned ``runtime.context["storage_user_id"]`` from the Gateway
         workspace selector.
      2. ``runtime.server_info.user.identity`` — populated by current LangGraph
         runtimes from Agent Server's authenticated user. Unlike ordinary run
         context, this is server-owned.
      3. ``config["configurable"]["langgraph_auth_user_id"]`` — populated by
         LangGraph Server from the deployment's ``@auth.authenticate`` result.
         This supports older runtimes and code paths without ``server_info``.
      4. ``runtime.context["user_id"]`` — legacy Gateway identity when no
         workspace storage principal was selected.
      5. The workspace ContextVar, then
         ``_current_user`` — set by the auth middleware at request entry.
      6. ``DEFAULT_USER_ID`` — last-resort fallback.

    ``actor_user_id`` is carried beside this value for credential-sensitive
    consumers; use :func:`resolve_runtime_actor_user_id` there.

    The storage identity survives boundaries where the contextvar may have
    been lost (background tasks scheduled outside the request task, worker
    pools, and future cross-process drivers).
    """
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        storage_user_id = context.get("storage_user_id")
        if storage_user_id:
            return str(storage_user_id)
    active_storage = _storage_context.get()
    if active_storage is not None:
        return active_storage.storage_user_id

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_user_id()


def resolve_runtime_actor_user_id(runtime: object | None) -> str:
    """Resolve the authenticated actor for credentials and audit attribution."""
    server_info = getattr(runtime, "server_info", None)
    server_user_id = _user_id_from_auth_user(getattr(server_info, "user", None))
    if server_user_id:
        return server_user_id

    langgraph_user_id = _user_id_from_langgraph_auth()
    if langgraph_user_id:
        return langgraph_user_id

    context = getattr(runtime, "context", None)
    if isinstance(context, Mapping):
        actor_user_id = context.get("actor_user_id")
        if actor_user_id:
            return str(actor_user_id)

    if isinstance(context, Mapping):
        ctx_user_id = context.get("user_id")
        if ctx_user_id:
            return str(ctx_user_id)
    return get_effective_actor_user_id()


def _user_id_from_langgraph_auth() -> str | None:
    """Return the authenticated LangGraph Server user id, if available.

    LangGraph Server reserves the ``langgraph_auth_user`` and
    ``langgraph_auth_user_id`` configurable keys and populates them from the
    deployment's ``@auth.authenticate`` result. ``get_config()`` raises when
    called outside a runnable context, which simply means this identity channel
    is unavailable.
    """
    try:
        from langgraph.config import get_config

        config = get_config()
    except RuntimeError:
        return None

    return _user_id_from_langgraph_config(config)


# ---------------------------------------------------------------------------
# Sentinel-based user_id resolution
# ---------------------------------------------------------------------------
#
# Repository methods accept a ``user_id`` keyword-only argument that
# defaults to ``AUTO``. The three possible values drive distinct
# behaviours; see the docstring on :func:`resolve_user_id`.


class _AutoSentinel:
    """Singleton marker meaning 'resolve user_id from contextvar'."""

    _instance: _AutoSentinel | None = None

    def __new__(cls) -> _AutoSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<AUTO>"


AUTO: Final[_AutoSentinel] = _AutoSentinel()


def resolve_user_id(
    value: str | None | _AutoSentinel,
    *,
    method_name: str = "repository method",
) -> str | None:
    """Resolve the user_id parameter passed to a repository method.

    Three-state semantics:

    - :data:`AUTO` (default): read from contextvar; raise
      :class:`RuntimeError` if no user is in context. This is the
      common case for request-scoped calls.
    - Explicit ``str``: use the provided id verbatim, overriding any
      contextvar value. Useful for tests and admin-override flows.
    - Explicit ``None``: no filter — the repository should skip the
      user_id WHERE clause entirely. Reserved for migration scripts
      and CLI tools that intentionally bypass isolation.
    """
    if isinstance(value, _AutoSentinel):
        storage_context = _storage_context.get()
        if storage_context is not None:
            return storage_context.storage_user_id
        user = _current_user.get()
        if user is None:
            raise RuntimeError(f"{method_name} called with user_id=AUTO but no user context is set; pass an explicit user_id, set the contextvar via auth middleware, or opt out with user_id=None for migration/CLI paths.")
        # Coerce to ``str`` at the boundary: ``User.id`` is typed as
        # ``UUID`` for the API surface, but the persistence layer
        # stores ``user_id`` as ``String(64)`` and aiosqlite cannot
        # bind a raw UUID object to a VARCHAR column ("type 'UUID' is
        # not supported"). Honour the documented return type here
        # rather than ripple a type change through every caller.
        return str(user.id)
    return value
````

## backend/packages/harness/deerflow/persistence/organizations/resolution.py

````python
"""Small server-side organization resolution helpers for the dual-write window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from deerflow.persistence.organizations.identity import private_organization_id
from deerflow.persistence.organizations.model import OrganizationMemberRow, OrganizationRow
from deerflow.persistence.user.model import UserRow


class _OwnedRow(Protocol):
    user_id: str | None
    organization_id: str | None


@dataclass(frozen=True, slots=True)
class ActiveOrganization:
    """Server-validated organization membership and storage principal."""

    id: str
    name: str
    role: str
    storage_user_id: str | None


async def active_organization_for_user(
    session: AsyncSession,
    user_id: str | None,
    organization_id: str | None = None,
) -> ActiveOrganization | None:
    """Resolve one active organization selected by an authenticated actor.

    A missing selector means the actor's deterministic private organization.
    An explicit selector is accepted only with an active membership row. The
    nullable storage principal is intentional: private organizations continue
    to use the actor's id, while shared organizations provide a dedicated
    principal.
    """
    if user_id is None:
        return None
    target_id = organization_id or private_organization_id(user_id)
    row = (
        await session.execute(
            select(OrganizationRow, OrganizationMemberRow.role)
            .join(
                OrganizationMemberRow,
                (OrganizationMemberRow.organization_id == OrganizationRow.id) & (OrganizationMemberRow.user_id == user_id),
            )
            .where(
                OrganizationRow.id == target_id,
                OrganizationRow.status == "active",
                OrganizationMemberRow.status == "active",
                # A disabled account keeps no organization, which closes its
                # sessions, PATs and internal delegations in this one place.
                ~exists().where(UserRow.id == user_id, UserRow.disabled_at.is_not(None)),
            )
        )
    ).first()
    if row is None:
        return None
    organization, role = row
    return ActiveOrganization(
        id=organization.id,
        name=organization.name,
        role=str(role),
        storage_user_id=organization.storage_user_id,
    )


def storage_user_id_for_organization(organization: ActiveOrganization, actor_user_id: str) -> str | None:
    """Return the storage principal, or the actor for a private org."""
    if organization.storage_user_id:
        return organization.storage_user_id
    if organization.id == private_organization_id(actor_user_id):
        return actor_user_id
    return None


async def private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return await session.scalar(select(OrganizationRow.id).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active"))


async def active_private_organization_for_user(session: AsyncSession, user_id: str | None) -> str | None:
    """Return the user's active private organization only with active membership."""
    active = await active_organization_for_user(session, user_id)
    return active.id if active is not None else None


def private_organization_for_user_sync(session: Session, user_id: str | None) -> str | None:
    if user_id is None:
        return None
    organization_id = private_organization_id(user_id)
    return session.scalar(select(OrganizationRow.id).where(OrganizationRow.id == organization_id, OrganizationRow.status == "active"))


def organization_from_owned_parent(parent: _OwnedRow | None, expected_user_id: str | None, *, parent_name: str) -> str | None:
    """Return a verified parent's organization, preserving NULL legacy quarantine."""
    if parent is None:
        return None
    if parent.user_id is None:
        if parent.organization_id is not None:
            raise ValueError(f"{parent_name} has organization ownership without an audit owner")
        return None
    if expected_user_id is not None and parent.user_id != expected_user_id:
        raise ValueError(f"{parent_name} belongs to a different user")
    expected_organization_id = private_organization_id(parent.user_id)
    if parent.organization_id is not None and parent.organization_id != expected_organization_id:
        raise ValueError(f"{parent_name} has conflicting organization ownership")
    return parent.organization_id


class OrganizationMismatchError(LookupError):
    """A write cannot be proven to belong to its organization; answer 404."""


def organization_for_write(active_organization_id: str | None, parent_organization_id: str | None, storage_user_id: str | None) -> str | None:
    """Return the organization to stamp on a new or re-parented row.

    Takes server-owned inputs only: the middleware-verified active organization
    (``resolve_organization_id()``), the organization of a parent row already
    loaded under the caller's user filter, and the storage principal of the
    workspace being written (``resolve_user_id(AUTO)``), which is not the row's
    ``user_id`` when the row is audited to a person, such as feedback in a shared
    workspace. Every organization is
    ``private_organization_id(storage principal)``, so any other value is a
    cross-organization attach or an actor/storage mix-up and raises
    :class:`OrganizationMismatchError`. With no active organization and no
    parent organization the result is ``None``, the quarantine marker, never a
    guess.
    """
    expected = private_organization_id(storage_user_id) if storage_user_id else None
    for organization_id in (active_organization_id, parent_organization_id):
        if organization_id is not None and organization_id != expected:
            raise OrganizationMismatchError("organization does not match the storage principal")
    return active_organization_id or parent_organization_id
````

## backend/packages/harness/deerflow/persistence/projects/model.py

````python
"""ORM models for projects.

``ProjectRow``: one row per user-owned project. ``id`` (uuid4 hex) is the only
external identity; ``name``/``presentation`` are display attributes — renaming
touches exactly this row and never affects membership (threads reference
``threads_meta.project_id``). ``instructions`` is user-authored project
context; Phase 1 stores and PATCHes it, Phase 2 injects it. There is
deliberately no ``memory_mode``/sharing/agent-config column: no consumer
exists in Phase 1/2 (RFC v2 §3, §4.1).

``ProjectDocumentRow``: one row per project shelf document. ``stored_relpath``
is a server-generated content address relative to ``users/{user_id}/projects/``
that embeds both ``sha256`` and the row's own ``id``, so rows never share
files and a re-upload after trash always lands in a fresh namespace. Text
detection is a sampled read at serve time, and the shelf has no history by
design — hence no ``mime``/``is_text``/``version``/``deleted_by`` columns
(Phase-2 spec §6.1). ``source_*`` records promotion provenance (Slice C);
``trashed_at``/``trash_origin`` implement the recoverable trash tier: every
read query filters ``trashed_at IS NULL`` so trashed rows are invisible to the
index, tools, and listing APIs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Momentum Phase 2 item 2: optional link to the owning client (clients.id).
    # Nullable -- most projects have no client yet -- and unenforced by a FK,
    # matching threads_meta.project_id's precedent (0020).
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    instructions: Mapped[str] = mapped_column(Text, default="")
    presentation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProjectDocumentRow(Base):
    __tablename__ = "project_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    stored_relpath: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    source_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    trash_origin: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
````

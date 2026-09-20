import { ArrowUpRight, Bot } from "lucide-react";
import Link from "next/link";

import styles from "./command-center.module.css";

export type AgentTopologyItem = {
  name: string;
  display_name?: string | null;
  enabled: boolean;
};

type AgentTopologyProps = {
  leadLabel: string;
  leadHref: string;
  roster: AgentTopologyItem[];
  selectedName: string | null;
  loading?: boolean;
  error?: boolean;
  /** True when run history was readable, so per-agent live state is known. */
  runtimeKnown?: boolean;
  /** Names with an active recorded run. Only meaningful when runtimeKnown. */
  activeAgentNames?: readonly string[] | null;
  onSelect: (name: string) => void;
};

export function AgentTopology({
  leadLabel,
  leadHref,
  roster,
  selectedName,
  loading,
  error,
  runtimeKnown = false,
  activeAgentNames = null,
  onSelect,
}: AgentTopologyProps) {
  return (
    <div className={styles.topology}>
      <div className={styles.topologyLead}>
        <span className={styles.leadIcon}>
          <Bot size={25} />
        </span>
        <div>
          <strong>{leadLabel}</strong>
          <span>Orchestration &amp; delegation</span>
        </div>
        <Link aria-label="Open lead agent conversation" href={leadHref}>
          <ArrowUpRight size={20} />
        </Link>
      </div>
      <div
        className={styles.topologyRoster}
        aria-label={
          runtimeKnown
            ? "Specialist definitions with recorded live state"
            : "Specialist definitions (live state unknown)"
        }
      >
        {loading ? (
          <p role="status">Loading agent definitions…</p>
        ) : error ? (
          <p role="alert">The specialist catalog could not be loaded.</p>
        ) : roster.length === 0 ? (
          <p>No specialist definitions are available to this account.</p>
        ) : (
          roster.map((agent) => {
            const hasActiveRun =
              runtimeKnown && (activeAgentNames ?? []).includes(agent.name);
            return (
              <button
                key={agent.name}
                className={styles.agent}
                aria-pressed={selectedName === agent.name}
                onClick={() => onSelect(agent.name)}
              >
                <span className={styles.agentMonogram}>
                  {(agent.display_name ?? agent.name)
                    .replace(/^dillon[ -]/i, "")
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <strong>
                  {agent.display_name ?? agent.name.replace("dillon-", "")}
                </strong>
                <span>
                  {runtimeKnown
                    ? hasActiveRun
                      ? "Active run recorded"
                      : "No active run recorded"
                    : "Live state unknown"}
                </span>
                <span>
                  <i data-enabled={agent.enabled} />
                  {agent.enabled ? "Enabled" : "Disabled"}
                </span>
              </button>
            );
          })
        )}
      </div>
      <p className={styles.diagramNote}>
        {runtimeKnown
          ? "Definitions above; live state from recorded runs. Connections do not indicate active dispatch."
          : "Definitions above; live state unknown - run history unavailable. Connections do not indicate active dispatch."}
      </p>
    </div>
  );
}

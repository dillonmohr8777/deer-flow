import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import { MomoAvatar } from "./momo-avatar";

import styles from "./command-center.module.css";

export type AgentTopologyItem = {
  name: string;
  display_name?: string | null;
  enabled: boolean;
  description?: string;
  model?: string;
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
        {/* The lead role always wears the canon lead Momo ("lead" in
            MomoAvatar's map), whichever agent is leading. Hidden from
            assistive tech: the name beside it says who this is. */}
        <span className={styles.leadMomo} aria-hidden="true">
          <MomoAvatar agent={{ name: "lead", display_name: leadLabel }} size={160} />
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
        role="group"
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
              // "paper-card" (2px hover lift), "pinned" (brass pin) and
              // "paper-pixels" (steps(3) tick) are paper.css hooks, inert
              // outside the paper treatment. A pin means working: only a
              // specialist with an active recorded run wears one, with the
              // three working squares. The words carry the state either way.
              <button
                key={agent.name}
                className={cn(
                  styles.agent,
                  "paper-card",
                  hasActiveRun && "pinned",
                )}
                aria-pressed={selectedName === agent.name}
                onClick={() => onSelect(agent.name)}
              >
                <span className={styles.agentMomo} aria-hidden="true">
                  <MomoAvatar agent={agent} size={56} />
                </span>
                <span className={styles.agentText}>
                  <strong>
                    {agent.display_name ?? agent.name.replace("dillon-", "")}
                  </strong>
                  <span className={styles.agentState}>
                    <span>
                      {hasActiveRun && (
                        <span
                          className={`${styles.working} paper-pixels`}
                          data-active="true"
                          aria-hidden="true"
                        />
                      )}
                      {runtimeKnown
                        ? hasActiveRun
                          ? "Active run recorded"
                          : "Idle"
                        : "Live state unknown"}
                    </span>
                    <span>
                      <i data-enabled={agent.enabled} />
                      {agent.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </span>
                </span>
              </button>
            );
          })
        )}
      </div>
      <p className={styles.diagramNote}>
        {runtimeKnown
          ? "Definitions above; live state from recorded runs."
          : "Definitions above; live state is unknown because run history is unavailable."}
      </p>
    </div>
  );
}

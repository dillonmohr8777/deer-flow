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
  /** Names with a running recorded run. Only meaningful when runtimeKnown. */
  runningAgentNames?: readonly string[] | null;
  /**
   * Names whose only live runs are still pending. Queued is waiting, not
   * acting, so it gets the word and never the pin (DESIGN.md, dispatch board).
   */
  queuedAgentNames?: readonly string[] | null;
  onSelect: (name: string) => void;
};

type LiveState = "running" | "queued" | "idle" | "unknown";

// Short words, so a working card stays one line tall beside its Momo, and
// the same words the dispatch board prints on the slip.
const STATE_WORDS: Record<LiveState, string> = {
  running: "Working",
  queued: "Queued",
  idle: "Idle",
  unknown: "Live state unknown",
};

export function AgentTopology({
  leadLabel,
  leadHref,
  roster,
  selectedName,
  loading,
  error,
  runtimeKnown = false,
  runningAgentNames = null,
  queuedAgentNames = null,
  onSelect,
}: AgentTopologyProps) {
  // Unknown live state is never activity: without run history every agent
  // reads "Live state unknown", unpinned and still.
  const liveState = (name: string): LiveState =>
    !runtimeKnown
      ? "unknown"
      : (runningAgentNames ?? []).includes(name)
        ? "running"
        : (queuedAgentNames ?? []).includes(name)
          ? "queued"
          : "idle";
  const leadState = liveState("dillon-brain");
  const leadActive = leadState === "running";

  return (
    <div className={styles.topology}>
      {/* The frame lets the topology's own container query move the lead
          beside the roster when there is room (a container cannot restyle
          itself, only its descendants). */}
      <div className={styles.topologyFrame}>
        {/* The lead is a sheet on the same board: it wears the pin, as the
            specialists do, only while its own run is going. */}
        <div className={cn(styles.topologyLead, leadActive && "pinned")}>
          {/* The lead is Dillon Brain (agent name "dillon-brain"), a pulsing
            brain rather than a robot Momo. Hidden from assistive tech: the
            name beside it says who this is. */}
          <span className={styles.leadMomo} aria-hidden="true">
            <MomoAvatar
              agent={{ name: "dillon-brain", display_name: leadLabel }}
              size={160}
              active={leadActive}
            />
          </span>
          <div>
            <strong>{leadLabel}</strong>
            <span>Orchestration &amp; delegation</span>
            <span className={styles.leadState} data-state={leadState}>
              {leadActive && (
                <span
                  className={`${styles.working} paper-pixels`}
                  data-active="true"
                  aria-hidden="true"
                />
              )}
              {STATE_WORDS[leadState]}
            </span>
            {!loading && !error && roster.length > 0 ? (
              <span className={styles.leadCount}>
                Delegates to {roster.length}{" "}
                {roster.length === 1 ? "specialist" : "specialists"}
              </span>
            ) : null}
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
            <p role="alert">The specialist catalog couldn&apos;t be loaded.</p>
          ) : roster.length === 0 ? (
            <p>No specialist definitions are available to this account.</p>
          ) : (
            roster.map((agent) => {
              const state = liveState(agent.name);
              const hasActiveRun = state === "running";
              return (
                // "paper-card" (2px hover lift), "pinned" (brass pin) and
                // "paper-pixels" (steps(3) tick) are paper.css hooks, inert
                // outside the paper treatment. A pin means working: only a
                // specialist with a running recorded run wears one, with the
                // three working squares; a queued one says so, unpinned, as
                // its slip on the dispatch board does. The words carry the
                // state either way.
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
                      <span data-state={state}>
                        {hasActiveRun && (
                          <span
                            className={`${styles.working} paper-pixels`}
                            data-active="true"
                            aria-hidden="true"
                          />
                        )}
                        {STATE_WORDS[state]}
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
      </div>
      <p className={styles.diagramNote}>
        {runtimeKnown
          ? "Definitions above; live state from recorded runs."
          : "Definitions above; live state is unknown because run history is unavailable."}
      </p>
    </div>
  );
}

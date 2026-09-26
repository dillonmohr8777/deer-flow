import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import { AgentAlive } from "./agent-alive";
import { agentLifeLabel, type AgentLife } from "./agent-life";
import { useWorkspaceAppearance } from "./appearance-provider";
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
  /**
   * Each agent's recorded run state (agent-life.ts), keyed by agent name.
   * Only meaningful when runtimeKnown. A name missing here falls back to
   * activeAgentNames: running if listed, else idle.
   */
  lives?: Readonly<Record<string, AgentLife>> | null;
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
  lives = null,
  onSelect,
}: AgentTopologyProps) {
  const { motionOn } = useWorkspaceAppearance();
  // Only meaningful when runtimeKnown: an unknown live state must never
  // read as work, a finish or a failure.
  const lifeOf = (name: string): AgentLife =>
    !runtimeKnown
      ? { state: "idle" }
      : (lives?.[name] ??
        ((activeAgentNames ?? []).includes(name)
          ? { state: "running" }
          : { state: "idle" }));
  const leadLife = lifeOf("dillon-brain");
  const leadActive =
    leadLife.state === "running" || leadLife.state === "thinking";

  return (
    <div className={styles.topology}>
      <div className={styles.topologyLead}>
        {/* The lead is Dillon Brain (agent name "dillon-brain"), a pulsing
            brain rather than a robot Momo. Hidden from assistive tech: the
            name beside it says who this is. */}
        <AgentAlive
          className={styles.leadMomo}
          life={leadLife}
          motion={motionOn}
        >
          <MomoAvatar
            agent={{ name: "dillon-brain", display_name: leadLabel }}
            size={160}
            active={leadActive}
          />
        </AgentAlive>
        <div>
          <strong>{leadLabel}</strong>
          <span>Orchestration &amp; delegation</span>
          {runtimeKnown && (
            <span data-life={leadLife.state}>{agentLifeLabel(leadLife)}</span>
          )}
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
            const life = lifeOf(agent.name);
            const working =
              life.state === "running" || life.state === "thinking";
            return (
              // "paper-card" (2px hover lift) and "paper-pixels" (steps(3)
              // tick) are paper.css hooks, inert outside the paper
              // treatment. AgentAlive draws the run state on the avatar:
              // only a running agent wears the brass pin. The words carry
              // the state either way.
              <button
                key={agent.name}
                className={cn(styles.agent, "paper-card")}
                data-life={life.state}
                aria-pressed={selectedName === agent.name}
                onClick={() => onSelect(agent.name)}
              >
                <AgentAlive
                  className={styles.agentMomo}
                  life={life}
                  motion={motionOn}
                >
                  <MomoAvatar agent={agent} size={56} />
                </AgentAlive>
                <span className={styles.agentText}>
                  <strong>
                    {agent.display_name ?? agent.name.replace("dillon-", "")}
                  </strong>
                  <span className={styles.agentState}>
                    <span data-life={life.state}>
                      {working && (
                        <span
                          className={`${styles.working} paper-pixels`}
                          data-active="true"
                          aria-hidden="true"
                        />
                      )}
                      {runtimeKnown
                        ? agentLifeLabel(life)
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

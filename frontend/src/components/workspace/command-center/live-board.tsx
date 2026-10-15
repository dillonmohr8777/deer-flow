"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { useApprovals } from "@/core/approvals";
import { useBoard, useSpend } from "@/core/command-center";
import { useConsoleRuns, useConsoleStats } from "@/core/console";

import { useWorkspaceAppearance } from "./appearance-provider";
import {
  ACCENTS,
  asOfLabel,
  circleLayout,
  easeOutValue,
  oldestPending,
  spendRows,
  waitingFor,
} from "./live-board-model";

import styles from "./live-board.module.css";

const usd = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(v);

/** Counts up to the real value; with motion off it simply shows the value. */
function Eased({
  value,
  format,
}: {
  value: number;
  format: (v: number) => string;
}) {
  const { motionOn } = useWorkspaceAppearance();
  const [shown, setShown] = useState(motionOn ? 0 : value);
  const from = useRef(shown);
  useEffect(() => {
    if (!motionOn) {
      from.current = value;
      setShown(value);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = (now - start) / 700;
      const v = easeOutValue(origin, value, t);
      from.current = v;
      setShown(v);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, motionOn]);
  return <>{format(shown)}</>;
}

function Tile({
  title,
  accent,
  source,
  asOf,
  className,
  children,
}: {
  title: string;
  accent: string;
  source: string;
  asOf: string | number | null | undefined;
  className: string | undefined;
  children: ReactNode;
}) {
  const id = `board-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section
      className={`${styles.tile} ${className}`}
      style={{ "--accent": accent } as CSSProperties}
      aria-labelledby={id}
    >
      <h3 id={id} className={styles.label}>
        <span className={styles.dot} aria-hidden="true" />
        {title}
      </h3>
      <div className={styles.body}>{children}</div>
      <p className={styles.meta}>
        Source: <code>{source}</code>. As of {asOfLabel(asOf)}.
      </p>
    </section>
  );
}

function Unavailable({ reason }: { reason: string }) {
  return (
    <p className={styles.unavailable}>
      <strong>Unavailable.</strong> {reason}
    </p>
  );
}

function Loading() {
  return (
    <p className={styles.loading} role="status">
      Loading
    </p>
  );
}

function Meter({
  label,
  used,
  cap,
  ratio,
}: {
  label: string;
  used: number;
  cap: number | null;
  ratio: number | null;
}) {
  return (
    <div className={styles.meterRow}>
      <div className={styles.meterText}>
        <strong>{label}</strong>
        <span>
          {usd(used)} {cap ? `of ${usd(cap)}` : "(no cap set)"}
        </span>
      </div>
      {ratio !== null ? (
        <div
          className={styles.track}
          role="meter"
          aria-label={`${label} spend against cap`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(ratio * 100)}
          aria-valuetext={`${Math.round(ratio * 100)} percent of cap`}
        >
          <span className={styles.fill} style={{ width: `${ratio * 100}%` }} />
        </div>
      ) : null}
    </div>
  );
}

export function LiveBoard({
  canReadRuns,
  agentLabel,
}: {
  canReadRuns: boolean;
  agentLabel: (assistantId: string | null) => string;
}) {
  const spend = useSpend();
  const board = useBoard();
  const approvals = useApprovals("pending");
  const stats = useConsoleStats();
  const runs = useConsoleRuns({});

  const activeRuns =
    runs.data?.runs.filter(
      (r) => r.status === "pending" || r.status === "running",
    ) ?? [];
  const pending = approvals.data ? oldestPending(approvals.data) : null;
  const err = (q: { error: unknown }) =>
    q.error instanceof Error ? q.error.message : "The request failed.";

  return (
    <div className={styles.board} data-testid="live-board">
      <p className={styles.intro}>
        Every tile names its source and when it was read. A source that cannot
        be read says so; it never shows zero.
      </p>
      <div className={styles.grid}>
        <Tile
          title="Spend vs caps"
          accent={ACCENTS.spend}
          source="GET /api/cost-router/spend"
          asOf={spend.dataUpdatedAt || null}
          className={styles.spend}
        >
          {spend.isError ? (
            <Unavailable reason={err(spend)} />
          ) : !spend.data ? (
            <Loading />
          ) : Object.keys(spend.data.routes).length === 0 ? (
            <Unavailable reason="The cost router has no routes configured." />
          ) : (
            <>
              {!spend.data.enabled ? (
                <p className={styles.note}>
                  The cost router is off in config, so caps are not enforced.
                </p>
              ) : null}
              {spendRows(spend.data).map((row) => (
                <div key={row.name} className={styles.route}>
                  <p className={styles.routeName}>
                    <strong>{row.name}</strong> <span>{row.model}</span>
                  </p>
                  <Meter label="Today" {...row.today} />
                  <Meter label="Month" {...row.month} />
                  {row.unpriced ? (
                    <p className={styles.note}>
                      Some usage has no price, so it is not counted above.
                    </p>
                  ) : null}
                </div>
              ))}
            </>
          )}
        </Tile>

        <Tile
          title="Approvals waiting"
          accent={ACCENTS.approvals}
          source="GET /api/approvals?status=pending"
          asOf={approvals.dataUpdatedAt || null}
          className={styles.approvals}
        >
          {approvals.isError ? (
            <Unavailable reason={err(approvals)} />
          ) : !pending ? (
            <Loading />
          ) : (
            <>
              <p className={styles.big}>
                <Eased
                  value={pending.count}
                  format={(v) => String(Math.round(v))}
                />
              </p>
              {pending.oldest ? (
                <p>
                  Oldest: <strong>{pending.oldest.title}</strong>, waiting{" "}
                  {waitingFor(pending.oldest.created_at)}.
                </p>
              ) : (
                <p>Nothing is waiting on you.</p>
              )}
            </>
          )}
        </Tile>

        <Tile
          title="Agents active now"
          accent={ACCENTS.agents}
          source="GET /api/console/stats and /api/console/runs"
          asOf={runs.dataUpdatedAt || null}
          className={styles.agents}
        >
          {!canReadRuns ? (
            <Unavailable reason="Your role cannot read runs." />
          ) : runs.isError || stats.isError ? (
            <Unavailable reason={err(runs.isError ? runs : stats)} />
          ) : !stats.data || !runs.data ? (
            <Loading />
          ) : (
            <>
              <p className={styles.big}>
                <Eased
                  value={stats.data.active_runs}
                  format={(v) => String(Math.round(v))}
                />
              </p>
              {activeRuns.length === 0 ? (
                <p>No runs in progress.</p>
              ) : (
                <ul className={styles.list}>
                  {activeRuns.slice(0, 5).map((r) => (
                    <li key={r.run_id}>
                      <strong>{agentLabel(r.assistant_id)}</strong>{" "}
                      {r.thread_title ?? "Untitled thread"}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Tile>

        <Tile
          title="Paid-route ledger"
          accent={ACCENTS.ledger}
          source="GET /api/command-center/board (admission ledger)"
          asOf={
            board.data?.admission.available ? board.data.admission.as_of : null
          }
          className={styles.ledger}
        >
          {board.isError ? (
            <Unavailable reason={err(board)} />
          ) : !board.data ? (
            <Loading />
          ) : !board.data.admission.available ? (
            <Unavailable reason={board.data.admission.reason} />
          ) : (
            <>
              <Meter
                label="This month"
                used={board.data.admission.used_usd}
                cap={board.data.admission.ceiling_usd}
                ratio={Math.min(
                  board.data.admission.used_usd /
                    board.data.admission.ceiling_usd,
                  1,
                )}
              />
              <ul className={styles.list}>
                {Object.entries(board.data.admission.by_route).map(
                  ([name, v]) => (
                    <li key={name}>
                      <strong>{name}</strong> {usd(v)}
                    </li>
                  ),
                )}
              </ul>
            </>
          )}
        </Tile>

        <Tile
          title="Eval pass rate by week"
          accent={ACCENTS.evals}
          source="GET /api/command-center/board (agency evals)"
          asOf={board.data?.evals.available ? board.data.evals.as_of : null}
          className={styles.evals}
        >
          {board.isError ? (
            <Unavailable reason={err(board)} />
          ) : !board.data ? (
            <Loading />
          ) : !board.data.evals.available ? (
            <Unavailable reason={board.data.evals.reason} />
          ) : (
            <ul className={styles.weeks}>
              {board.data.evals.weeks.map((w) => (
                <li key={w.week}>
                  <span className={styles.weekName}>{w.week}</span>
                  <span className={styles.track} aria-hidden="true">
                    <span
                      className={styles.fill}
                      style={{ width: `${Math.round(w.pass_rate * 100)}%` }}
                    />
                  </span>
                  <strong>{Math.round(w.pass_rate * 100)}%</strong>
                  <span className={styles.muted}>
                    {w.runs} run{w.runs === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Tile>

        <Tile
          title="Lobby friendships"
          accent={ACCENTS.lobby}
          source="GET /api/command-center/board (lobby notes)"
          asOf={board.data?.lobby.available ? board.data.lobby.as_of : null}
          className={styles.lobby}
        >
          {board.isError ? (
            <Unavailable reason={err(board)} />
          ) : !board.data ? (
            <Loading />
          ) : !board.data.lobby.available ? (
            <Unavailable reason={board.data.lobby.reason} />
          ) : (
            <FriendGraph
              nodes={board.data.lobby.nodes}
              edges={board.data.lobby.edges}
            />
          )}
        </Tile>
      </div>
    </div>
  );
}

function FriendGraph({
  nodes,
  edges,
}: {
  nodes: { id: string }[];
  edges: { source: string; target: string; score: number }[];
}) {
  const laid = circleLayout(nodes);
  const at = new Map(laid.map((n) => [n.id, n]));
  const top = Math.max(5, ...edges.map((e) => e.score));
  return (
    <>
      <svg
        viewBox="0 0 100 100"
        className={styles.graph}
        role="img"
        aria-label={`Friendship graph with ${nodes.length} agents and ${edges.length} links`}
      >
        {edges.map((e) => {
          const a = at.get(e.source);
          const b = at.get(e.target);
          if (!a || !b) return null;
          return (
            <line
              key={`${e.source}-${e.target}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={styles.edge}
              strokeWidth={0.6 + (e.score / top) * 2.4}
            />
          );
        })}
        {laid.map((n) => (
          <g key={n.id}>
            <circle cx={n.x} cy={n.y} r={3.2} className={styles.node} />
            <text
              x={n.x}
              y={n.y + (n.y < 50 ? -6 : 9)}
              textAnchor="middle"
              className={styles.nodeLabel}
            >
              {n.id}
            </text>
          </g>
        ))}
      </svg>
      <ul className={styles.srOnly}>
        {edges.map((e) => (
          <li key={`${e.source}-${e.target}`}>
            {e.source} and {e.target}: score {e.score.toFixed(1)}
          </li>
        ))}
      </ul>
    </>
  );
}

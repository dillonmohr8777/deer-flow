"use client";

import {
  ErrorState,
  pageStyles,
  WorkingState,
} from "@/components/workspace/page-body";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  brandAssetUrl,
  priceLabel,
  sharedNote,
  useBrandKit,
  type BrandAgent,
  type BrandKit,
  type BrandVideo,
} from "@/core/momobot-brand";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

import styles from "./lineup.module.css";

/** Column spans (of 6) that give the roll call its uneven rhythm on wide screens. */
const SPANS = [4, 2, 3, 3, 2, 4, 6, 3, 3, 4, 2, 6];

function titleOf(key: string): string {
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Landscape on wide screens, vertical on narrow. Controls on, never autoplays. */
export function LineupVideo({
  name,
  video,
}: {
  name: string;
  video: BrandVideo;
}) {
  const narrow = useIsMobile();
  const file = narrow ? video.vertical : video.landscape;
  const poster = narrow ? video.poster_vertical : video.poster_landscape;
  return (
    <figure className={styles.video}>
      <video
        key={file}
        className={narrow ? styles.vertical : styles.landscape}
        controls
        playsInline
        preload="none"
        poster={brandAssetUrl(poster)}
        src={brandAssetUrl(file)}
        aria-label={`${name}, ${video.seconds} second video`}
      />
      <figcaption>
        {name} · {video.seconds}s
      </figcaption>
    </figure>
  );
}

function AgentEntry({
  agent,
  index,
  showPricing,
  names,
}: {
  agent: BrandAgent;
  index: number;
  showPricing: boolean;
  names: Record<string, string>;
}) {
  const price = priceLabel(agent.price, showPricing);
  const shared = showPricing ? sharedNote(agent.price, names) : null;
  return (
    <li
      className={styles.entry}
      style={
        {
          "--span": SPANS[index] ?? 3,
          "--accent": agent.color,
        } as React.CSSProperties
      }
    >
      <img
        className={styles.icon}
        src={brandAssetUrl(agent.icon)}
        alt={agent.icon_alt}
        width={72}
        height={72}
        loading="lazy"
      />
      <div className={styles.entryText}>
        <p className={styles.order} aria-hidden="true">
          {String(agent.order).padStart(2, "0")}
        </p>
        <h3>{agent.name}</h3>
        <p>{agent.job}</p>
        <p className={styles.chip}>{agent.short_name}</p>
        {price && (
          <p className={styles.price}>
            {price}
            {shared && <span> · {shared}</span>}
          </p>
        )}
      </div>
    </li>
  );
}

export function LineupContent({ kit }: { kit: BrandKit }) {
  const { max_plus: max } = kit;
  const agents = [...kit.agents].sort((a, b) => a.order - b.order);
  const names = Object.fromEntries(agents.map((a) => [a.id, a.name]));
  const maxPrice = priceLabel(max.price, kit.show_pricing);
  return (
    <div className={styles.page}>
      <h1>MomoBot Agents</h1>

      <section className={cn(styles.flagship, pageStyles.sheet)}>
        {max.hero_art && (
          <img
            className={styles.mascot}
            src={brandAssetUrl(max.hero_art)}
            alt=""
            width={240}
            height={240}
          />
        )}
        <div>
          <img
            className={styles.maxIcon}
            src={brandAssetUrl(max.icon)}
            alt=""
            width={56}
            height={56}
          />
          <h2>{max.tagline}</h2>
          <p className={styles.bundle}>{max.bundle_line}</p>
          {maxPrice && <p className={styles.price}>{maxPrice}</p>}
        </div>
      </section>

      <section aria-label="Videos" className={styles.videos}>
        {Object.entries(kit.videos).map(([key, video]) => (
          <LineupVideo
            key={key}
            name={video.title ?? titleOf(key)}
            video={video}
          />
        ))}
      </section>

      <ol className={styles.roll} aria-label="Agents">
        {agents.map((agent, i) => (
          <AgentEntry
            key={agent.id}
            agent={agent}
            index={i}
            showPricing={kit.show_pricing}
            names={names}
          />
        ))}
      </ol>

      {kit.brand?.end_card_line && (
        <p className={styles.endCard}>{kit.brand.end_card_line}</p>
      )}
    </div>
  );
}

export function LineupPage() {
  const { data, isPending, isError } = useBrandKit();
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className={cn("overflow-y-auto", pageStyles.page)}>
        {isPending ? (
          <WorkingState label="Loading" className="m-8" />
        ) : isError || !data ? (
          <ErrorState
            message="Not available"
            detail="The MomoBot agents lineup is not set up on this workspace."
          />
        ) : (
          <LineupContent kit={data} />
        )}
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

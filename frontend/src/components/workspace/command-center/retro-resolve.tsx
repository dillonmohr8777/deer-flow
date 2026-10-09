"use client";

/*
 * Retro treatment: on first paint of a page, main content resolves from
 * heavily pixelated to crisp in steps (16px, 8px, 4px, 2px, crisp) over
 * about 600ms, via an SVG mosaic filter (feFlood/feComposite/feTile/
 * feMorphology) whose step size is driven from here. The filter is removed
 * entirely once the resolve finishes — nothing is left applied.
 *
 * The <svg><filter> tree is built with raw DOM APIs (createElementNS), not
 * JSX. A React-rendered filter subtree — confirmed byte-identical markup,
 * correct SVG namespace, single instance, portalled straight to <body> —
 * measurably had zero visual effect in this app (diffed screenshots showed
 * 0 changed pixels), while the same primitives built with createElementNS
 * and appended directly rendered correctly. Root cause not identified.
 *
 * The filter itself is applied to #workspace-main-content
 * (WORKSPACE_MAIN_CONTENT_ID, skip-to-content.tsx): a plain div that
 * `WorkspaceContent` always renders as the sole child of #workspace-main,
 * carrying every page's real content, including the two connectivity
 * banners. This effect only ever reads and writes that node's own
 * `style.filter` — never its children — so nothing here can race React's
 * reconciliation of that content, however it changes shape mid-resolve
 * (loading states swapping to real content or an error, banners appearing
 * or disappearing, client-side navigation swapping the whole route).
 *
 * An earlier version instead built its own wrapper div with createElement,
 * physically moved #workspace-main's *existing* children into it, applied
 * the filter to that wrapper, and moved the children back out (or removed
 * the wrapper on cleanup) once the resolve finished. That worked for the
 * pixelation effect itself, but it silently broke React's bookkeeping:
 * React still believed those children were direct children of
 * #workspace-main, because nothing told its fiber tree they had been
 * relocated. The instant React next needed to add or remove one of them —
 * for example /workspace/agents replacing its loading state with the real
 * page (or a disabled/error state) the moment /api/features answered,
 * while the moved-out wrapper was still in place — it called
 * `#workspace-main.removeChild(node)` on a node that was actually a child
 * of the wrapper, and the browser threw "Failed to execute 'removeChild' on
 * 'Node': The node to be removed is not a child of this node." Uncaught
 * (this app defines no error.tsx/global-error.tsx), that took down the
 * whole app to Next's built-in fallback. Applying the filter directly to
 * #workspace-main itself (no wrapper at all) was tried before introducing
 * that wrapper and "measurably had zero visual effect" (same
 * diffed-screenshot method) — the persistent, React-owned target below
 * keeps the working technique (a dedicated filtered element, not
 * #workspace-main itself) without ever touching its children.
 *
 * Gated on brandMotionAllowed (appearance-preferences.ts); reduced motion or
 * brand motion off means no resolve at all: content stays exactly as
 * rendered, filter never applied. Retriggers per route (usePathname) —
 * #workspace-main-content is not remounted by client-side navigation.
 */

import { usePathname } from "next/navigation";
import { useEffect, useId } from "react";

import { WORKSPACE_MAIN_CONTENT_ID } from "@/components/workspace/skip-to-content";

import { useWorkspaceAppearance } from "./appearance-provider";

// Pixel size in px at each step; 0 means crisp (filter removed).
const STEPS = [16, 8, 4, 2, 0] as const;
const STEP_MS = 150; // 4 intervals between the 5 steps * 150ms = 600ms total.
const SVG_NS = "http://www.w3.org/2000/svg";

export function RetroResolve() {
  const { preferences, motionOn } = useWorkspaceAppearance();
  const pathname = usePathname();
  const rawId = useId();
  const filterId = `retro-resolve-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;

  const active = preferences.treatment === "retro";

  useEffect(() => {
    if (!active || !motionOn) return;
    const target = document.getElementById(WORKSPACE_MAIN_CONTENT_ID);
    if (!target) return;

    // feFlood paints a small fixed dot near one corner of each tile cell;
    // feTile repeats that cell (sized by the first feComposite's width/
    // height, the actual "pixel size") across the content; the second
    // feComposite masks the source down to just those dots; feMorphology
    // dilates each surviving dot back out until it covers its whole cell —
    // the classic SVG mosaic/pixelation recipe. Dilate radius must be
    // roughly half the tile size or gaps show between cells.
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.setAttribute("aria-hidden", "true");
    svg.style.position = "absolute";
    svg.style.width = "0";
    svg.style.height = "0";
    svg.style.overflow = "hidden";

    const filter = document.createElementNS(SVG_NS, "filter");
    filter.setAttribute("id", filterId);
    filter.setAttribute("x", "-10%");
    filter.setAttribute("y", "-10%");
    filter.setAttribute("width", "120%");
    filter.setAttribute("height", "120%");

    const flood = document.createElementNS(SVG_NS, "feFlood");
    flood.setAttribute("x", "2");
    flood.setAttribute("y", "2");
    flood.setAttribute("width", "2");
    flood.setAttribute("height", "2");

    const composite1 = document.createElementNS(SVG_NS, "feComposite");
    composite1.setAttribute("width", "16");
    composite1.setAttribute("height", "16");

    const tile = document.createElementNS(SVG_NS, "feTile");
    tile.setAttribute("result", "retro-tile");

    const composite2 = document.createElementNS(SVG_NS, "feComposite");
    composite2.setAttribute("in", "SourceGraphic");
    composite2.setAttribute("in2", "retro-tile");
    composite2.setAttribute("operator", "in");

    const morphology = document.createElementNS(SVG_NS, "feMorphology");
    morphology.setAttribute("operator", "dilate");
    morphology.setAttribute("radius", "8");

    filter.append(flood, composite1, tile, composite2, morphology);
    svg.append(filter);
    document.body.append(svg);

    target.style.filter = `url(#${filterId})`;

    const setStep = (px: number) => {
      const tileSize = String(Math.max(px, 1));
      composite1.setAttribute("width", tileSize);
      composite1.setAttribute("height", tileSize);
      morphology.setAttribute("radius", String(Math.max(px / 2, 1)));
    };

    // Idempotent by design (plain style clear + remove()), unlike the old
    // wrapper's move-children-back dance, so natural completion and effect
    // cleanup can never double-run into each other.
    const clearFilter = () => {
      target.style.filter = "";
      svg.remove();
    };

    let index = 0;
    setStep(STEPS[0]);

    const timer = window.setInterval(() => {
      index += 1;
      const px = STEPS[index];
      if (px === undefined || px === 0) {
        window.clearInterval(timer);
        clearFilter();
        return;
      }
      setStep(px);
    }, STEP_MS);

    return () => {
      window.clearInterval(timer);
      clearFilter();
    };
  }, [active, motionOn, pathname, filterId]);

  return null;
}

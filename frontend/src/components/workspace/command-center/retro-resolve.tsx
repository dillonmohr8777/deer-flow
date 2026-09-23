"use client";

/*
 * Retro treatment: on first paint of a page, main content resolves from
 * heavily pixelated to crisp in steps (16px, 8px, 4px, 2px, crisp) over
 * about 600ms, via an SVG mosaic filter (feFlood/feComposite/feTile/
 * feMorphology) whose step size is driven from here. The filter is removed
 * entirely once the resolve finishes — nothing is left applied.
 *
 * Two things are built with raw DOM APIs, not JSX:
 *
 * 1. The <svg><filter> tree (createElementNS). A React-rendered filter
 *    subtree — confirmed byte-identical markup, correct SVG namespace,
 *    single instance, portalled straight to <body> — measurably had zero
 *    visual effect in this app (diffed screenshots showed 0 changed
 *    pixels), while the same primitives built with createElementNS and
 *    appended directly rendered correctly. Root cause not identified.
 *
 * 2. A plain wrapper div around #workspace-main's children, which the
 *    filter is actually applied to. Applying the filter directly to
 *    #workspace-main (the flex SidebarInset, already mounted and painted
 *    before this effect runs) also measurably had zero visual effect;
 *    moving the same content into a freshly created wrapper and filtering
 *    that instead worked. The wrapper mirrors #workspace-main's own flex
 *    container properties so layout is unaffected, and is unwrapped
 *    (children moved back, wrapper removed) the moment the resolve
 *    finishes or the effect is cleaned up — nothing lingers in the DOM.
 *
 * Gated on brandMotionAllowed (appearance-preferences.ts); reduced motion or
 * brand motion off means no resolve at all: content stays exactly as
 * rendered, no wrapper, no filter. Retriggers per route (usePathname) —
 * #workspace-main is not remounted by client-side navigation.
 */

import { usePathname } from "next/navigation";
import { useEffect, useId } from "react";

import { WORKSPACE_MAIN_ID } from "@/components/workspace/skip-to-content";

import { useWorkspaceAppearance } from "./appearance-provider";

// Pixel size in px at each step; 0 means crisp (filter removed).
const STEPS = [16, 8, 4, 2, 0] as const;
const STEP_MS = 150; // 4 intervals between the 5 steps * 150ms = 600ms total.
const SVG_NS = "http://www.w3.org/2000/svg";
const WRAPPER_ATTR = "data-retro-resolve-wrapper";

export function RetroResolve() {
  const { preferences, motionOn } = useWorkspaceAppearance();
  const pathname = usePathname();
  const rawId = useId();
  const filterId = `retro-resolve-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;

  const active = preferences.treatment === "retro";

  useEffect(() => {
    if (!active || !motionOn) return;
    const main = document.getElementById(WORKSPACE_MAIN_ID);
    if (!main) return;

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

    // Move #workspace-main's current children into a fresh wrapper that
    // mirrors its flex-container layout, so the resolve is invisible to
    // layout — only the filter target changes.
    const wrapper = document.createElement("div");
    wrapper.setAttribute(WRAPPER_ATTR, "true");
    wrapper.style.display = "flex";
    wrapper.style.flexDirection = "column";
    wrapper.style.flex = "1 1 auto";
    wrapper.style.minHeight = "0";
    wrapper.style.minWidth = "0";
    wrapper.style.width = "100%";
    while (main.firstChild) wrapper.append(main.firstChild);
    main.append(wrapper);
    wrapper.style.filter = `url(#${filterId})`;

    const setStep = (px: number) => {
      const tileSize = String(Math.max(px, 1));
      composite1.setAttribute("width", tileSize);
      composite1.setAttribute("height", tileSize);
      morphology.setAttribute("radius", String(Math.max(px / 2, 1)));
    };

    const unwrap = () => {
      while (wrapper.firstChild) main.insertBefore(wrapper.firstChild, wrapper);
      wrapper.remove();
      svg.remove();
    };

    let index = 0;
    setStep(STEPS[0]);

    const timer = window.setInterval(() => {
      index += 1;
      const px = STEPS[index];
      if (px === undefined || px === 0) {
        window.clearInterval(timer);
        unwrap();
        return;
      }
      setStep(px);
    }, STEP_MS);

    return () => {
      window.clearInterval(timer);
      // A cleanup can fire after unwrap() already ran (natural completion);
      // guard against double-removal.
      if (wrapper.isConnected) unwrap();
    };
  }, [active, motionOn, pathname, filterId]);

  return null;
}

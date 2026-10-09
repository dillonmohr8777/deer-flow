/** Release pinned content only after the library's target layout has committed
 * and both real panel transitions have finished. The caller owns resize(), the
 * transition classes, and invalidation when its layout context changes. */
export function waitForRightPanelTransition(
  group: HTMLElement,
  targetLayout: Record<string, number>,
  onComplete: () => void,
): () => void {
  const view = group.ownerDocument.defaultView;
  if (!view) return () => undefined;

  const panels = Array.from(group.children).filter(
    (node): node is HTMLElement =>
      node instanceof view.HTMLElement && node.hasAttribute("data-panel"),
  );
  const targets = panels.map((panel) => targetLayout[panel.id]);
  const serializedTargets = targets.map((target) => {
    const style = group.ownerDocument.createElement("div").style;
    style.flexGrow = String(target);
    return style.flexGrow;
  });
  let cancelled = false;
  let frame: number | undefined;
  let restoreTransitions: (() => void) | undefined;

  const cleanup = () => {
    cancelled = true;
    if (frame !== undefined) view.cancelAnimationFrame(frame);
    frame = undefined;
    restoreTransitions?.();
    restoreTransitions = undefined;
  };

  const schedule = () => {
    if (!cancelled && frame === undefined) {
      frame = view.requestAnimationFrame(check);
    }
  };

  const check = () => {
    frame = undefined;
    if (cancelled) return;
    if (
      !group.isConnected ||
      panels.length === 0 ||
      panels.some((panel) => panel.parentElement !== group)
    ) {
      cleanup();
      return;
    }

    // resize() updates library state before React writes these inline targets.
    // No animations before that write does not mean the operation has finished.
    if (
      panels.some(
        (panel, index) =>
          !Number.isFinite(targets[index]) ||
          serializedTargets[index] === "" ||
          panel.style.flexGrow === "" ||
          Number(panel.style.flexGrow) !== Number(serializedTargets[index]),
      )
    ) {
      schedule();
      return;
    }

    if (
      !restoreTransitions &&
      (typeof view.CSSTransition !== "function" ||
        panels.some((panel) => typeof panel.getAnimations !== "function"))
    ) {
      // Without transition introspection, snap the committed layout while the
      // caller still holds the width pin; never guess completion from a timer.
      const previous = panels.map((panel) => ({
        value: panel.style.getPropertyValue("transition-property"),
        priority: panel.style.getPropertyPriority("transition-property"),
      }));
      restoreTransitions = () => {
        panels.forEach((panel, index) => {
          const { value, priority } = previous[index]!;
          if (value) {
            panel.style.setProperty("transition-property", value, priority);
          } else {
            panel.style.removeProperty("transition-property");
          }
        });
      };
      panels.forEach((panel) => {
        panel.style.setProperty("transition-property", "none", "important");
        panel.getBoundingClientRect();
      });
    }

    // Flush the committed styles before asking for transitions. Restrict to
    // each panel itself: descendants' opacity, controls, etc. are unrelated.
    const computedGrow = panels.map((panel) => {
      panel.getBoundingClientRect();
      return view.getComputedStyle(panel).flexGrow;
    });
    const transitions = panels.flatMap((panel) =>
      typeof panel.getAnimations === "function" &&
      typeof view.CSSTransition === "function"
        ? panel
            .getAnimations()
            .filter(
              (animation) =>
                animation instanceof view.CSSTransition &&
                animation.transitionProperty === "flex-grow" &&
                (animation.effect as KeyframeEffect | null)?.target === panel &&
                animation.playState !== "finished" &&
                animation.playState !== "idle",
            )
        : [],
    );
    if (transitions.length > 0) {
      // A cancel may replace a transition. Recheck on a fresh frame rather than
      // treating a rejection as successful completion of the current target.
      void Promise.allSettled(
        transitions.map((transition) => transition.finished),
      ).then(schedule);
      return;
    }

    // Computed CSS numbers may serialize to six significant digits. For
    // 0..100 layout weights the rounding error is at most 0.00005. This guard
    // follows actual transition completion; it is not a pixel or animation
    // tolerance (0.0001/100 is 0.001px in a 1000px group).
    if (
      computedGrow.some((value, index) => {
        const grow = Number(value);
        return (
          !Number.isFinite(grow) ||
          Math.abs(grow - Number(serializedTargets[index])) > 0.0001
        );
      })
    ) {
      schedule();
      return;
    }

    cleanup();
    onComplete();
  };

  schedule();
  return cleanup;
}

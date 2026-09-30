import { type Locator, type Page, expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const ARTIFACT_PATH = "/artifact-fixtures/report.html";
const THREAD_ID = "00000000-0000-0000-0000-000000003125";

function writeFileMessages() {
  return [
    {
      type: "human",
      id: "msg-human-artifact",
      content: [{ type: "text", text: "Create a report artifact" }],
    },
    {
      type: "ai",
      id: "msg-ai-write-artifact",
      content: "",
      tool_calls: [
        {
          id: "write-file-artifact",
          name: "write_file",
          args: {
            description: "Writing report artifact",
            path: ARTIFACT_PATH,
            content:
              "<!doctype html><html><body><h1>Report draft</h1></body></html>",
          },
        },
      ],
    },
    {
      type: "tool",
      id: "msg-tool-write-artifact",
      name: "write_file",
      tool_call_id: "write-file-artifact",
      content: "OK",
    },
  ];
}

async function panelWidth(panel: Locator): Promise<number> {
  const box = await panel.boundingBox();
  return box?.width ?? 0;
}

async function dragPanel(handle: Locator, ...deltas: number[]): Promise<void> {
  // hover() waits for a stable bounding box: the open animation moves the
  // 1px-wide divider, so coordinates read any earlier miss it entirely.
  await handle.hover();
  await expect(handle).toHaveAttribute("data-separator", "hover");

  const box = await handle.boundingBox();
  expect(box).not.toBeNull();
  const y = box!.y + box!.height / 2;
  const x = box!.x + box!.width / 2;

  const mouse = handle.page().mouse;
  await mouse.down();
  await expect(handle).toHaveAttribute("data-separator", "active");
  let currentX = x;
  for (const delta of deltas) {
    currentX += delta;
    await mouse.move(currentX, y, { steps: 10 });
  }
  await mouse.up();
}

/** Drag the divider left by `distance` px, widening the right panel. */
async function widenPanel(handle: Locator, distance: number): Promise<void> {
  await dragPanel(handle, -distance);
}

/** Drag the divider right by `distance` px, narrowing the right panel. */
async function narrowPanel(handle: Locator, distance: number): Promise<void> {
  await dragPanel(handle, distance);
}

async function openArtifact(page: Page): Promise<void> {
  await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({ timeout: 15_000 });
  await page.getByText(ARTIFACT_PATH).click();
}

async function settledArtifactWidth(panel: Locator): Promise<number> {
  await expect(panel).toHaveAttribute("aria-hidden", "false");
  await expect(panel.getByText("report.html")).toBeVisible();
  await expect
    .poll(() =>
      panel.evaluate((element) => {
        const content = element.firstElementChild as HTMLElement | null;
        const group = element.closest('[data-slot="resizable-panel-group"]');
        const moving = Array.from(group?.children ?? []).some((child) =>
          child
            .getAnimations()
            .some(
              (animation) =>
                animation instanceof CSSTransition &&
                animation.transitionProperty === "flex-grow" &&
                animation.playState === "running",
            ),
        );
        return (
          element.getBoundingClientRect().width > 0 &&
          content?.style.width === "" &&
          !moving
        );
      }),
    )
    .toBe(true);
  return panelWidth(panel);
}

test.describe("Artifacts panel resize", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Artifact panel resize",
          messages: writeFileMessages(),
        },
      ],
    });
    await page.goto(`/workspace/chats/${THREAD_ID}`);
  });

  test("the divider resizes the artifacts panel", async ({ page }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel).toBeVisible();

    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(handle).toBeVisible();
    await handle.hover();

    const widthBefore = await panelWidth(artifactsPanel);
    expect(widthBefore).toBeGreaterThan(0);

    await widenPanel(handle, 200);

    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthBefore + 100);
  });

  test("drag-collapse closes the panel and it can be reopened", async ({
    page,
  }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    const group = page.locator('[data-slot="resizable-panel-group"]');
    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(artifactsPanel).toBeVisible();

    await narrowPanel(handle, 500);

    await expect(artifactsPanel).toBeHidden();
    await expect(handle).toHaveAttribute("data-separator", "disabled");

    await openArtifact(page);
    await expect(artifactsPanel).toBeVisible();

    const groupWidth = await panelWidth(group);
    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(groupWidth * 0.19);
  });

  test("reversing a collapse drag before release keeps the panel open", async ({
    page,
  }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(artifactsPanel.getByText("report.html")).toBeVisible();

    // Cross the collapse threshold, then reverse the same drag before the
    // pointer is released. The final non-zero layout should remain open.
    await dragPanel(handle, 500, -500);

    await expect(artifactsPanel).toHaveAttribute("aria-hidden", "false");
    await expect(artifactsPanel.getByText("report.html")).toBeVisible();
    await expect(handle).not.toHaveAttribute("data-separator", "disabled");
  });

  test("a dragged width is kept when the panel is reopened", async ({
    page,
  }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel).toBeVisible();

    const handle = page.locator('[data-slot="resizable-handle"]');
    await handle.hover();
    const widthBefore = await panelWidth(artifactsPanel);
    await widenPanel(handle, 200);
    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthBefore + 100);
    const widthAfterDrag = await panelWidth(artifactsPanel);

    await artifactsPanel
      .getByRole("button", { name: /close/i })
      .first()
      .click();
    await expect(artifactsPanel).toBeHidden();

    await openArtifact(page);
    await expect(artifactsPanel).toBeVisible();

    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthAfterDrag - 20);
  });
  test("opening animates the width, dragging does not", async ({ page }) => {
    await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });

    // Listen for the transition instead of sampling widths: `transitionrun`
    // fires when the transition is created, so a loaded machine dropping
    // frames cannot turn a real animation into a missed one.
    await page.evaluate(() => {
      const store = window as unknown as { __transitions?: string[] };
      store.__transitions = [];
      document.addEventListener(
        "transitionrun",
        (event) => {
          store.__transitions?.push(event.propertyName);
        },
        true,
      );
    });

    await page.getByText(ARTIFACT_PATH).click();

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (window as unknown as { __transitions: string[] }).__transitions,
        ),
      )
      .toContain("flex-grow");

    const artifactsPanel = page.locator("#artifacts");
    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(artifactsPanel).toBeVisible();
    await handle.hover();

    const transitionDuringDrag = await (async () => {
      const box = await handle.boundingBox();
      const mouse = page.mouse;
      await mouse.down();
      await mouse.move(box!.x - 120, box!.y + box!.height / 2, { steps: 5 });
      const transition = await page.evaluate(() => {
        // `[data-panel]` is the element the library sizes; the child that
        // `className` lands on is not the flex item.
        const panel = document
          .querySelector("#artifacts")
          ?.closest("[data-panel]");
        return panel
          ? window.getComputedStyle(panel).transitionProperty
          : "missing";
      });
      await mouse.up();
      return transition;
    })();

    expect(transitionDuringDrag).not.toContain("flex-grow");
  });

  test("reduced motion completes opening and reopening without pinning or drag transitions", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openArtifact(page);

    const panel = page.locator("#artifacts");
    const handle = page.locator('[data-slot="resizable-handle"]');
    const group = page.locator('[data-slot="resizable-panel-group"]');
    const openWidth = await settledArtifactWidth(panel);
    const availableWidth =
      (await panelWidth(group)) - (await panelWidth(handle));
    expect(Math.abs(openWidth - availableWidth * 0.4)).toBeLessThanOrEqual(1);
    expect(
      await panel.evaluate(
        (element) =>
          getComputedStyle(element.closest("[data-panel]")!).transitionProperty,
      ),
    ).not.toContain("flex-grow");

    await widenPanel(handle, 200);
    await expect.poll(() => panelWidth(panel)).toBeGreaterThan(openWidth + 100);
    const draggedWidth = await settledArtifactWidth(panel);

    await panel.getByRole("button", { name: /close/i }).first().click();
    await expect(panel).toHaveAttribute("aria-hidden", "true");
    await expect(panel.getByText("report.html")).toHaveCount(0);
    await openArtifact(page);
    expect(
      Math.abs((await settledArtifactWidth(panel)) - draggedWidth),
    ).toBeLessThanOrEqual(1);
  });

  test("rapid reopen cancels stale closing completion and retains the current artifact", async ({
    page,
  }) => {
    // The header's native ArtifactTrigger requires the thread artifact catalog;
    // a write_file message alone only renders a clickable (non-keyboard) step.
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Artifact panel resize",
          messages: writeFileMessages(),
          artifacts: [ARTIFACT_PATH],
        },
      ],
    });
    await page.reload();
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await openArtifact(page);
    const panel = page.locator("#artifacts");
    const openWidth = await settledArtifactWidth(panel);
    await expect(page.getByTestId("artifact-trigger")).toBeVisible();
    const group = page.locator('[data-slot="resizable-panel-group"]');
    const selector = await group.evaluate(
      (element) => `#${CSS.escape(element.id)}`,
    );
    // A longer real transition keeps the interruption observable on loaded CI;
    // there is no timed sleep or alteration of the original resize cases.
    await page.addStyleTag({
      content: `${selector} > [data-panel] { transition-duration: 900ms !important; }`,
    });
    const probe = await group.evaluateHandle((element) => {
      const state = {
        activeAtReopen: false,
        cancellations: 0,
      };
      const trigger = document.querySelector(
        '[data-testid="artifact-trigger"]',
      )!;
      const onReopen = () => {
        state.activeAtReopen = Array.from(element.children).some((child) =>
          child
            .getAnimations()
            .some(
              (animation) =>
                animation instanceof CSSTransition &&
                animation.transitionProperty === "flex-grow" &&
                animation.playState === "running",
            ),
        );
      };
      const onCancel = (event: Event) => {
        if ((event as TransitionEvent).propertyName === "flex-grow") {
          state.cancellations += 1;
        }
      };
      trigger.addEventListener("click", onReopen, true);
      element.addEventListener("transitioncancel", onCancel);
      return {
        state,
        dispose: () => {
          trigger.removeEventListener("click", onReopen, true);
          element.removeEventListener("transitioncancel", onCancel);
        },
      };
    });

    try {
      await panel.getByRole("button", { name: /close/i }).first().click();
      await expect(panel).toHaveAttribute("aria-hidden", "true");
      await expect
        .poll(() =>
          group.evaluate((element) =>
            element
              .getAnimations({ subtree: true })
              .some(
                (animation) =>
                  animation instanceof CSSTransition &&
                  animation.transitionProperty === "flex-grow" &&
                  animation.playState === "running",
              ),
          ),
        )
        .toBe(true);
      // Native keyboard activation avoids waiting for a moving mouse target.
      await page.getByTestId("artifact-trigger").press("Enter");
      expect(
        Math.abs((await settledArtifactWidth(panel)) - openWidth),
      ).toBeLessThanOrEqual(1);
      const interruption = await probe.evaluate(({ state }) => state);
      expect(interruption.activeAtReopen).toBe(true);
      expect(interruption.cancellations).toBeGreaterThan(0);
      await expect(panel.getByText("report.html")).toBeVisible();
    } finally {
      await probe.evaluate(({ dispose }) => dispose());
      await probe.dispose();
    }
  });
});

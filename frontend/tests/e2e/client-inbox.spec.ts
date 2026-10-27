import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const json = (body: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(body),
});

async function portal(
  page: Page,
  staff = false,
  beforeResponse?: () => Promise<void>,
) {
  mockLangGraphAPI(page, { scheduledTasks: [] });
  let row: Record<string, unknown> | null = null;
  let published = false;
  const drafts: Record<string, unknown>[] = [];
  await page.route("**/api/client-portal/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/client-portal",
      "",
    );
    if (path.endsWith("/work-plan"))
      return route.fulfill({
        json: {
          schema: "internal_work_plan.v1",
          revision: 0,
          plan: null,
          recorded_by_user_id: null,
          recorded_at: null,
          verification: "staff_recorded_unverified",
          source: { table: "board_portal", id: path.split("/")[2] },
        },
      });
    const input = route.request().postDataJSON() as Record<
      string,
      unknown
    > | null;
    if (path === "/clients")
      return route.fulfill(
        json({
          workspace_id: "synthetic-workspace",
          clients: [{ id: "alpha", name: "Synthetic Alpha" }],
          can_review: staff,
          can_draft: staff,
        }),
      );
    if (route.request().method() === "POST") {
      if (path === "/threads")
        row ??= {
          id: "weekly",
          client_id: "alpha",
          subject: input?.subject,
          revision: 0,
          state: "pending",
          publish_receipt: null,
          can_review: staff,
          can_draft: staff,
          messages: [
            {
              id: "request",
              author: "You",
              body: input?.body,
              created_at: "2026-10-21T12:00:00Z",
              attachments: [],
            },
          ],
        };
      else if (path.endsWith("/draft") && row && input) {
        drafts.push(input);
        row = {
          ...row,
          revision: Number(row.revision) + 1,
          approval_id: "exact-version",
          state: "needs_approval",
          draft: { body: input.body, attachments: input.attachments },
        };
      } else if (path.endsWith("/publish") && row) {
        if (!published)
          row = {
            ...row,
            state: "published",
            publish_receipt: "receipt-one",
            messages: [
              ...(row.messages as unknown[]),
              {
                id: "published",
                author: "MomoBot",
                body: (row.draft as { body: string }).body,
                attachments: [
                  { name: "weekly-report.md", sha256: "synthetic" },
                ],
                created_at: "2026-10-21T13:00:00Z",
              },
            ],
          };
        published = true;
      }
      await beforeResponse?.();
      return route.fulfill(json(row));
    }
    if (path === "/threads")
      return route.fulfill(
        json({ threads: row ? [row] : [], has_more: false }),
      );
    return route.fulfill(json(row));
  });
  return { drafts };
}

for (const width of [390, 768, 1440]) {
  test(`client can submit and reopen a durable request at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await portal(page);
    await page.goto("/workspace/inbox");
    await page
      .getByRole("button", { name: "New request", exact: true })
      .click();
    await page.getByLabel("Subject", { exact: true }).fill("Weekly report");
    await page
      .getByLabel("Your request", { exact: true })
      .fill("Please prepare this week's source-backed report.");
    await page
      .getByRole("button", { name: "Submit request", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Weekly report", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Internal reply draft", { exact: true }),
    ).toHaveCount(0);
    await page.reload();
    await page.getByRole("button", { name: /Weekly report/ }).click();
    await expect(
      page.getByText("Please prepare this week's source-backed report.", {
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`inbox-${width}.png`),
      fullPage: true,
    });
  });
}

test("staff saves then publishes only the unchanged exact draft", async ({
  page,
}) => {
  await portal(page, true);
  await page.goto("/workspace/inbox");
  await page.getByRole("button", { name: "New request", exact: true }).click();
  await page.getByLabel("Subject", { exact: true }).fill("Weekly report");
  await page.getByLabel("Your request", { exact: true }).fill("Report please");
  await page
    .getByRole("button", { name: "Submit request", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Internal reply draft", exact: true })
    .fill("Your report is ready. Three synthetic settings were corrected.");
  await page
    .getByRole("button", { name: "Add deliverable", exact: true })
    .click();
  await page
    .getByLabel("Deliverable filename", { exact: true })
    .fill("weekly-report.md");
  await page
    .getByRole("textbox", { name: "Deliverable content", exact: true })
    .fill("# Weekly report\nThree synthetic settings corrected.");
  await page
    .getByRole("button", { name: "Save draft for review", exact: true })
    .click();
  const publish = page.getByRole("button", {
    name: "Approve exact draft and publish",
    exact: true,
  });
  await expect(publish).toBeEnabled();
  await page
    .getByRole("textbox", { name: "Internal reply draft", exact: true })
    .fill("Unsaved change");
  await expect(publish).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Internal reply draft", exact: true })
    .fill("Your report is ready. Three synthetic settings were corrected.");
  await publish.click();
  await expect(page.getByText(/Receipt receipt-one/)).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Download weekly-report.md",
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /Weekly report/ }).click();
  await expect(page.getByText(/Receipt receipt-one/)).toBeVisible();
});

test("editing a saved reply preserves both deliverables through save and reopen", async ({
  page,
}) => {
  const { drafts } = await portal(page, true);
  await page.goto("/workspace/inbox");
  await page.getByRole("button", { name: "New request", exact: true }).click();
  await page.getByLabel("Subject", { exact: true }).fill("Two deliverables");
  await page
    .getByLabel("Your request", { exact: true })
    .fill("Report and data please");
  await page
    .getByRole("button", { name: "Submit request", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Internal reply draft", exact: true })
    .fill("Original reply");
  await page
    .getByRole("button", { name: "Add deliverable", exact: true })
    .click();
  await page
    .getByLabel("Deliverable filename", { exact: true })
    .fill("report.md");
  await page
    .getByRole("textbox", { name: "Deliverable content", exact: true })
    .fill("# Weekly report");
  await page
    .getByRole("button", { name: "Add deliverable", exact: true })
    .click();
  await page
    .getByLabel("Deliverable filename 2", { exact: true })
    .fill("metrics.csv");
  await page
    .getByRole("textbox", { name: "Deliverable content 2", exact: true })
    .fill("setting,status\nthree,corrected");
  await page
    .getByRole("button", { name: "Save draft for review", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Approve exact draft and publish",
      exact: true,
    }),
  ).toBeEnabled();
  await page
    .getByRole("textbox", { name: "Internal reply draft", exact: true })
    .fill("Updated reply only");
  await page
    .getByRole("button", { name: "Save draft for review", exact: true })
    .click();
  await expect.poll(() => drafts.length).toBe(2);
  expect(drafts[1]).toMatchObject({
    expected_revision: 1,
    body: "Updated reply only",
    attachments: [
      { name: "report.md", content: "# Weekly report" },
      { name: "metrics.csv", content: "setting,status\nthree,corrected" },
    ],
  });
  await page.reload();
  await page.getByRole("button", { name: /Two deliverables/ }).click();
  await expect(
    page.getByRole("textbox", { name: "Internal reply draft", exact: true }),
  ).toHaveValue("Updated reply only");
  await expect(
    page.getByLabel("Deliverable filename 2", { exact: true }),
  ).toHaveValue("metrics.csv");
  await expect(
    page.getByRole("textbox", { name: "Deliverable content 2", exact: true }),
  ).toHaveValue("setting,status\nthree,corrected");
  await expect(
    page.getByRole("button", {
      name: "Approve exact draft and publish",
      exact: true,
    }),
  ).toBeEnabled();
});

test("pending saves preserve request and deliverable inputs", async ({
  page,
}) => {
  let pending = Promise.resolve();
  let release: () => void = () => undefined;
  const pause = () => {
    pending = new Promise<void>((resolve) => {
      release = resolve;
    });
  };
  await portal(page, true, () => pending);
  await page.goto("/workspace/inbox");
  const newRequest = page.getByRole("button", {
    name: "New request",
    exact: true,
  });
  await newRequest.click();
  const subject = page.getByLabel("Subject", { exact: true });
  const request = page.getByRole("textbox", {
    name: "Your request",
    exact: true,
  });
  await subject.fill("Delayed request");
  await request.fill("Preserve my request");
  pause();
  await page
    .getByRole("button", { name: "Submit request", exact: true })
    .click();
  try {
    await expect(subject).toBeDisabled();
    await expect(request).toBeDisabled();
    await expect(
      page.getByRole("combobox", { name: "Client", exact: true }),
    ).toBeDisabled();
    await expect(newRequest).toBeDisabled();
    await expect(request).toHaveValue("Preserve my request");
  } finally {
    release();
  }
  await expect(
    page.getByRole("heading", { name: "Delayed request", exact: true }),
  ).toBeVisible();
  const reply = page.getByRole("textbox", {
    name: "Internal reply draft",
    exact: true,
  });
  await reply.fill("Saved reply");
  await page
    .getByRole("button", { name: "Add deliverable", exact: true })
    .click();
  const filename = page.getByLabel("Deliverable filename", { exact: true });
  const content = page.getByRole("textbox", {
    name: "Deliverable content",
    exact: true,
  });
  await filename.fill("report.md");
  await content.fill("Saved deliverable");
  pause();
  await page
    .getByRole("button", { name: "Save draft for review", exact: true })
    .click();
  try {
    await expect(reply).toBeDisabled();
    await expect(filename).toBeDisabled();
    await expect(content).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Remove deliverable 1", exact: true }),
    ).toBeDisabled();
    await expect(newRequest).toBeDisabled();
  } finally {
    release();
  }
  await expect(reply).toBeEnabled();
  await expect(filename).toBeEnabled();
  await expect(content).toBeEnabled();
  await expect(reply).toHaveValue("Saved reply");
  await expect(content).toHaveValue("Saved deliverable");
  await page.reload();
  await page.getByRole("button", { name: /Delayed request/ }).click();
  await expect(reply).toHaveValue("Saved reply");
  await expect(filename).toHaveValue("report.md");
  await expect(content).toHaveValue("Saved deliverable");
});

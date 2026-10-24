import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

for (const width of [390, 768, 1440]) {
  test(`staff records an independent work plan and resolves conflict at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const externalRequests: string[] = [];
    const origin = new URL(
      String(test.info().project.use.baseURL ?? "http://localhost:3000"),
    ).origin;
    await page.route("**/*", (route) => {
      if (new URL(route.request().url()).origin !== origin) {
        externalRequests.push(route.request().url());
        return route.abort();
      }
      return route.fallback();
    });
    mockLangGraphAPI(page, { scheduledTasks: [] });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const writes: {
      expected_revision: number;
      plan: Record<string, unknown>;
    }[] = [];
    let otherWrites = 0;
    let revision = 2;
    let stored: Record<string, unknown> | null = null;
    let nextPageAttempts = 0;
    const teammates = [
      { user_id: "default", email: "default@test.local", role: "owner" },
      {
        user_id: "synthetic-teammate",
        email: "teammate@synthetic.invalid",
        role: "account_manager",
      },
    ];
    const row = (id: string) => ({
      id,
      client_id: "synthetic-alpha",
      subject:
        id === "one"
          ? "Synthetic planning request"
          : "Synthetic dependency request",
      state: "pending",
      portal_state: "pending",
      status: "pending",
      updated_at: null,
      revision: 47,
      publish_receipt: null,
      can_draft: true,
      can_review: true,
      messages: [],
      draft: { body: "Synthetic reply draft", attachments: [] },
    });
    const record = (id: string) => ({
      schema: "internal_work_plan.v1",
      revision,
      plan: stored,
      recorded_by_user_id: stored ? "synthetic-owner" : null,
      recorded_at: stored ? "2026-10-24T16:20:00Z" : null,
      verification: "staff_recorded_unverified",
      source: { table: "board_portal", id },
    });
    await page.route("**/api/projects?status=active", (route) =>
      route.fulfill({ json: { projects: [] } }),
    );
    await page.route("**/api/client-portal/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace("/api/client-portal", "");
      if (path === "/clients")
        return route.fulfill({
          json: {
            workspace_id: "synthetic-workspace",
            clients: [{ id: "synthetic-alpha", name: "Synthetic Alpha" }],
            can_draft: true,
            can_review: true,
          },
        });
      if (path === "/threads")
        return route.fulfill({
          json: { threads: [row("one"), row("two")], has_more: false },
        });
      if (path.endsWith("/context"))
        return route.fulfill({
          json: {
            schema: "client_operating_context.v1",
            workspace_id: "synthetic-workspace",
            client: {
              id: "synthetic-alpha",
              name: "Synthetic Alpha",
              source: { updated_at: null },
            },
            requests: { items: [row("one"), row("two")], has_more: true },
            current_request: {
              ...row(url.searchParams.get("thread_id") ?? "one"),
              timeline: [],
              timeline_truncated: false,
              current_draft: { revision: 47 },
            },
            domains: {
              internal_work_planning: {
                status: "available",
                scope: "current_request",
              },
            },
            freshness: "Stored synthetic portal evidence",
            limits: { requests: 25, messages: 40 },
          },
        });
      const id = path.split("/")[2]!;
      if (path.endsWith("/work-plan/participants")) {
        expect(request.method()).toBe("GET");
        expect(request.headers()["x-portal-workspace"]).toBe(
          "synthetic-workspace",
        );
        expect(url.searchParams.get("limit")).toBe("50");
        const cursor = url.searchParams.get("cursor");
        if (cursor !== null) {
          expect(cursor).toBe("synthetic-next+/=");
          nextPageAttempts++;
          if (nextPageAttempts === 1)
            return route.fulfill({ status: 503, json: {} });
        }
        return route.fulfill({
          json: {
            schema: "work_plan_participants.v1",
            source: { thread_id: id },
            plan_revision: revision,
            items: cursor === null ? [teammates[0]] : [teammates[1]],
            selected_items: teammates.filter(
              (item) =>
                item.user_id === stored?.assignee_user_id ||
                item.user_id === stored?.verifier_user_id,
            ),
            limit: 50,
            has_more: cursor === null,
            next_cursor: cursor === null ? "synthetic-next+/=" : null,
          },
        });
      }
      if (path.endsWith("/work-plan")) {
        expect(request.headers()["x-portal-workspace"]).toBe(
          "synthetic-workspace",
        );
        if (request.method() === "GET")
          return route.fulfill({ json: record(id) });
        expect(request.method()).toBe("PUT");
        const input = request.postDataJSON() as (typeof writes)[number];
        writes.push(input);
        if (writes.length === 1) {
          revision = 3;
          return route.fulfill({
            status: 409,
            json: {
              detail: "Internal work plan changed; reload before saving",
            },
          });
        }
        expect(input.expected_revision).toBe(revision);
        revision++;
        stored = input.plan;
        return route.fulfill({ json: record(id) });
      }
      if (request.method() !== "GET") otherWrites++;
      return route.fulfill({ json: row(id) });
    });
    await page.goto("/workspace/inbox");
    await page
      .getByRole("complementary", { name: "Inbox conversations" })
      .getByRole("button", { name: /Synthetic planning request/ })
      .click();
    const editor = page.getByRole("region", {
      name: "Internal work plan",
      exact: true,
    });
    await expect(editor.getByText("No recorded plan yet.")).toBeVisible();
    await expect(
      page.getByText("Internal work planning", { exact: true }),
    ).toBeVisible();
    await editor
      .getByRole("textbox", { name: "Outcome", exact: true })
      .fill("Prepare the synthetic review package");
    await editor
      .getByRole("combobox", { name: "Owner", exact: true })
      .selectOption("default");
    await editor
      .getByRole("combobox", { name: "Verifier", exact: true })
      .selectOption("default");
    await editor
      .getByRole("button", { name: "Load more teammates", exact: true })
      .click();
    await expect(editor.getByRole("alert")).toContainText(
      "eligibility could not be checked",
    );
    await expect(
      editor.getByRole("textbox", { name: "Outcome", exact: true }),
    ).toHaveValue("Prepare the synthetic review package");
    await expect(
      editor.getByRole("combobox", { name: "Owner", exact: true }),
    ).toHaveValue("default");
    await editor
      .getByRole("button", { name: "Retry teammates", exact: true })
      .click();
    await expect(
      editor.getByRole("button", { name: "Retry teammates", exact: true }),
    ).toHaveCount(0);
    await editor
      .getByRole("combobox", { name: "Owner", exact: true })
      .selectOption("synthetic-teammate");
    await expect(
      editor.getByRole("combobox", { name: "Owner", exact: true }),
    ).toHaveValue("synthetic-teammate");
    await editor
      .getByLabel("Due date", { exact: true })
      .fill("2026-11-02T09:30");
    await editor
      .getByLabel("Synthetic dependency request", { exact: true })
      .check();
    await editor
      .getByRole("combobox", { name: "Status", exact: true })
      .selectOption("reported_complete");
    await editor
      .getByRole("textbox", { name: "Next action", exact: true })
      .fill("Ask the verifier to inspect the recorded source");
    await editor
      .getByRole("button", { name: "Add evidence reference", exact: true })
      .click();
    await editor
      .getByRole("combobox", { name: "Evidence kind 1", exact: true })
      .selectOption("delivery");
    await editor
      .getByRole("textbox", { name: "Evidence reference 1", exact: true })
      .fill("synthetic-delivery-receipt");
    const save = editor.getByRole("button", {
      name: "Save work plan",
      exact: true,
    });
    await editor
      .getByRole("heading", { name: "Internal work plan", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test
        .info()
        .outputPath(`internal-work-plan-filled-top-${width}.png`),
    });
    await save.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test
        .info()
        .outputPath(`internal-work-plan-filled-bottom-${width}.png`),
    });
    await save.click();
    await expect(editor.getByRole("alert")).toContainText(
      "Your edits are retained",
    );
    await expect(
      editor.getByRole("textbox", { name: "Outcome", exact: true }),
    ).toHaveValue("Prepare the synthetic review package");
    expect(writes).toHaveLength(1);
    expect(writes[0]!.expected_revision).toBe(2);
    expect(writes[0]!.plan.dependency_thread_ids).toEqual(["two"]);
    expect(writes[0]!.plan.assignee_user_id).toBe("synthetic-teammate");
    expect(writes[0]!.plan.verifier_user_id).toBe("default");
    await expect(editor.getByRole("status")).toHaveCount(0);
    await editor
      .getByRole("button", { name: "Reload plan", exact: true })
      .click();
    await expect(
      editor.getByRole("textbox", { name: "Outcome", exact: true }),
    ).toHaveValue("");
    await editor
      .getByRole("textbox", { name: "Outcome", exact: true })
      .fill("Record a synthetic planning outcome");
    await editor
      .getByRole("textbox", { name: "Next action", exact: true })
      .fill("Review the source");
    await save.click();
    await expect(editor.getByText(/Saved work plan revision 4/)).toBeVisible();
    expect(writes).toHaveLength(2);
    expect(writes[1]!.expected_revision).toBe(3);
    expect(otherWrites).toBe(0);
    await expect(
      page.getByRole("textbox", { name: "Internal reply draft", exact: true }),
    ).toHaveValue("Synthetic reply draft");
    await editor.scrollIntoViewIfNeeded();
    for (const label of ["Owner", "Verifier", "Due date", "Status"])
      expect(
        (await (
          label === "Due date"
            ? editor.getByLabel(label, { exact: true })
            : editor.getByRole("combobox", { name: label, exact: true })
        ).boundingBox())!.height,
      ).toBeGreaterThanOrEqual(44);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await editor
      .getByRole("heading", { name: "Internal work plan", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test.info().outputPath(`internal-work-plan-saved-${width}.png`),
    });
    expect(errors).toEqual([]);
    expect(externalRequests).toEqual([]);
    await page
      .getByRole("complementary", { name: "Inbox conversations" })
      .getByRole("button", { name: /Synthetic dependency request/ })
      .click();
    await expect(
      editor.getByRole("textbox", { name: "Outcome", exact: true }),
    ).toHaveValue("Record a synthetic planning outcome");
    // A different request loads its own record instead of inheriting unsaved local edits.
    await editor
      .getByRole("textbox", { name: "Outcome", exact: true })
      .fill("Unsaved second request edits");
    await page
      .getByRole("complementary", { name: "Inbox conversations" })
      .getByRole("button", { name: /Synthetic planning request/ })
      .click();
    await expect(
      editor.getByRole("textbox", { name: "Outcome", exact: true }),
    ).toHaveValue("Record a synthetic planning outcome");
  });
}

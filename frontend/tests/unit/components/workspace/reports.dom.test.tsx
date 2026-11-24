import { beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ReportsBody } from "@/components/workspace/reports/reports";
import type {
  ConnectorHealth,
  LeadRecord,
  ReportingPeriod,
  ReportSummary,
  ReviewDoc,
} from "@/core/reports";

const mocks = {
  summary: null as ReportSummary | null,
  summaryError: false,
  leads: [] as LeadRecord[],
  leadsDataState: "verified" as
    | "verified"
    | "partial"
    | "pending"
    | "unavailable",
  connectors: [] as ConnectorHealth[],
  reviewDocs: [] as ReviewDoc[],
  requestedPeriods: [] as ReportingPeriod[],
  createDoc: rs.fn(async () => undefined as unknown as ReviewDoc),
  updateDoc: rs.fn(async () => undefined as unknown as ReviewDoc),
};

rs.mock("@/components/workspace/command-center/appearance-provider", () => ({
  useWorkspaceAppearance: () => ({ motionOn: false }),
}));

rs.mock("@/core/reports", () => ({
  useReportSummary: (period: ReportingPeriod) => {
    mocks.requestedPeriods.push(period);
    return {
      data: mocks.summary,
      isLoading: false,
      isError: mocks.summaryError,
      error: mocks.summaryError ? new Error("Gateway error") : null,
      refetch: rs.fn(),
    };
  },
  useReportLeads: () => ({
    data: {
      workspace_id: "ws-synthetic",
      period: "last_30d",
      data_state: mocks.leadsDataState,
      total_count: mocks.leads.length,
      leads: mocks.leads,
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: rs.fn(),
  }),
  useReportConnectors: () => ({
    data: {
      workspace_id: "ws-synthetic",
      connectors: mocks.connectors,
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: rs.fn(),
  }),
  useReviewDocs: () => ({
    data: {
      workspace_id: "ws-synthetic",
      review_docs: mocks.reviewDocs,
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: rs.fn(),
  }),
  useCreateReviewDoc: () => ({
    mutateAsync: mocks.createDoc,
    isPending: false,
  }),
  useUpdateReviewDoc: () => ({
    mutateAsync: mocks.updateDoc,
    isPending: false,
  }),
}));

function seedConnectedWorkspace() {
  mocks.summary = {
    workspace_id: "ws-synthetic",
    workspace_name: "Sample Workspace",
    period: "last_30d",
    window_start: "2026-10-25T00:00:00Z",
    window_end: "2026-11-24T00:00:00Z",
    kpis: {
      total_leads: 14,
      forms: 6,
      calls: 5,
      appointments: 3,
      appointment_label: "Booked consultations",
      matched_leads: 11,
      data_state: "partial",
      connected_lead_sources: ["google_ads", "whatconverts"],
      pending_lead_sources: ["meta_ads", "ga4", "google_sheets"],
      unavailable_lead_sources: [],
      excluded_non_lead_signals: [
        "clicks",
        "impressions",
        "sessions",
        "pageviews",
      ],
    },
    connectors_summary: { connected: 2, stale: 0, pending: 4, unavailable: 0 },
    review_docs_summary: {
      total: 1,
      pending_review: 1,
      approved: 0,
      needs_edits: 0,
    },
  };
  mocks.leadsDataState = "partial";
  mocks.leads = [
    {
      id: "lead-1",
      workspace_id: "ws-synthetic",
      lead_name: "Synthetic Lead One",
      lead_type: "form",
      channel: "google_ads",
      source_connector: "google_ads",
      campaign_name: "Core Search",
      external_lead_id: "ext-1",
      match_status: "matched",
      match_confidence: "high",
      occurred_at: "2026-11-20T14:30:00Z",
      notes: "Confirmed in intake log",
      created_at: "2026-11-20T14:35:00Z",
    },
  ];
  mocks.connectors = [
    {
      connector_key: "google_ads",
      display_name: "Google Ads",
      status: "connected",
      provides_leads: true,
      capability_summary: "Verified form and call conversions",
      external_account_ref: "acct-synthetic-1",
      last_synced_at: "2026-11-24T10:00:00Z",
      detail: "Read-only feed connected.",
      required_credential_refs: ["GOOGLE_ADS_OAUTH_REF"],
    },
    {
      connector_key: "meta_ads",
      display_name: "Meta Ads",
      status: "pending",
      provides_leads: true,
      capability_summary: "Lead form submissions",
      external_account_ref: null,
      last_synced_at: null,
      detail: "Awaiting workspace account and credential binding.",
      required_credential_refs: ["META_ADS_TOKEN_REF"],
    },
  ];
  mocks.reviewDocs = [
    {
      id: "doc-1",
      workspace_id: "ws-synthetic",
      title: "November Summary Draft",
      doc_url: "https://docs.google.com/document/d/synthetic-doc-001/edit",
      period_key: "last_30d",
      status: "pending_review",
      created_by: "user-a",
      decided_by: null,
      decided_at: null,
      comments: [
        {
          id: "c-1",
          author_id: "user-a",
          author_label: "Account Manager",
          body: "Ready for QA pass.",
          created_at: "2026-11-23T15:00:00Z",
        },
      ],
      created_at: "2026-11-23T14:00:00Z",
      updated_at: "2026-11-23T15:00:00Z",
    },
  ];
}

beforeEach(() => {
  cleanup();
  mocks.summary = null;
  mocks.summaryError = false;
  mocks.leads = [];
  mocks.leadsDataState = "pending";
  mocks.connectors = [];
  mocks.reviewDocs = [];
  mocks.requestedPeriods = [];
  mocks.createDoc.mockReset();
  mocks.updateDoc.mockReset();
});

describe("ReportsBody", () => {
  it("renders integer KPI totals, named-lead match-back table, and connector health", () => {
    seedConnectedWorkspace();
    render(<ReportsBody />);

    expect(screen.getByTestId("reports-workspace").textContent).toContain(
      "Sample Workspace",
    );
    expect(screen.getByTestId("kpi-total-leads").textContent).toBe("14");
    expect(screen.getByTestId("kpi-forms").textContent).toBe("6");
    expect(screen.getByTestId("kpi-calls").textContent).toBe("5");
    expect(screen.getByTestId("kpi-appointments").textContent).toBe("3");
    expect(screen.getByText("Booked consultations")).toBeDefined();

    // Named-lead table uses accessible region wrapper and row header.
    const tableRegion = screen.getByRole("region", {
      name: /Verified lead records for Last 30d/i,
    });
    expect(tableRegion.getAttribute("tabindex")).toBe("0");
    expect(
      screen.getByRole("rowheader", { name: /Synthetic Lead One/i }),
    ).toBeDefined();

    // Connector health badges show connected vs pending honestly.
    expect(screen.getByTestId("connector-google_ads").textContent).toContain(
      "Connected",
    );
    expect(screen.getByTestId("connector-meta_ads").textContent).toContain(
      "Pending",
    );
  });

  it("displays Pending instead of 0 when feeds are not connected yet", () => {
    mocks.summary = {
      workspace_id: "ws-empty",
      workspace_name: "New Workspace",
      period: "last_30d",
      window_start: "2026-10-25T00:00:00Z",
      window_end: "2026-11-24T00:00:00Z",
      kpis: {
        total_leads: null,
        forms: null,
        calls: null,
        appointments: null,
        appointment_label: "Booked appointments",
        matched_leads: null,
        data_state: "pending",
        connected_lead_sources: [],
        pending_lead_sources: ["google_ads", "whatconverts"],
        unavailable_lead_sources: [],
        excluded_non_lead_signals: [
          "clicks",
          "impressions",
          "sessions",
          "pageviews",
        ],
      },
      connectors_summary: {
        connected: 0,
        stale: 0,
        pending: 6,
        unavailable: 0,
      },
      review_docs_summary: {
        total: 0,
        pending_review: 0,
        approved: 0,
        needs_edits: 0,
      },
    };
    mocks.leadsDataState = "pending";
    mocks.leads = [];

    render(<ReportsBody />);

    expect(screen.getByTestId("kpi-total-leads").textContent).toBe("Pending");
    expect(screen.getByTestId("kpi-forms").textContent).toBe("Pending");
    expect(screen.getByTestId("kpi-calls").textContent).toBe("Pending");
    expect(screen.getByTestId("kpi-appointments").textContent).toBe("Pending");
    expect(screen.getByText("Lead connectors are pending setup")).toBeDefined();
  });

  it("switches the global reporting period when clicking period controls", () => {
    seedConnectedWorkspace();
    render(<ReportsBody />);

    fireEvent.click(screen.getByRole("button", { name: "Last 7d" }));
    expect(mocks.requestedPeriods).toContain("last_7d");

    fireEvent.click(screen.getByRole("button", { name: "Last Month" }));
    expect(mocks.requestedPeriods).toContain("last_month");
  });

  it("validates Google Doc links after interaction and runs review approval transitions", async () => {
    seedConnectedWorkspace();
    render(<ReportsBody />);

    const titleInput = screen.getByLabelText("Report title");
    const urlInput = screen.getByLabelText("Google Doc URL");

    // No premature aria-invalid before interaction.
    expect(titleInput.getAttribute("aria-invalid")).toBe("false");
    expect(urlInput.getAttribute("aria-invalid")).toBe("false");

    // Invalid third-party URL shows accessible error after blur and blocks submit.
    fireEvent.change(titleInput, { target: { value: "Weekly Recap" } });
    fireEvent.change(urlInput, {
      target: { value: "https://example.invalid/not-a-google-doc" },
    });
    fireEvent.blur(urlInput);
    expect(urlInput.getAttribute("aria-invalid")).toBe("true");
    expect(
      screen.getByText(/Link must point to docs\.google\.com/i),
    ).toBeDefined();

    // Valid Google Doc URL submits cleanly.
    fireEvent.change(urlInput, {
      target: {
        value: "https://docs.google.com/document/d/synthetic-doc-999/edit",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Attach for review" }));

    await waitFor(() => {
      expect(mocks.createDoc).toHaveBeenCalledWith({
        title: "Weekly Recap",
        doc_url: "https://docs.google.com/document/d/synthetic-doc-999/edit",
        period_key: "last_30d",
      });
    });

    // Review doc card supports timestamped comments and Approve / Request edits.
    const noteBox = screen.getByLabelText("Review note");
    fireEvent.change(noteBox, {
      target: { value: "Looks accurate across form and call counts." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(mocks.updateDoc).toHaveBeenCalledWith({
        docId: "doc-1",
        input: {
          status: "approved",
          comment: "Looks accurate across form and call counts.",
        },
      });
    });
  });
});

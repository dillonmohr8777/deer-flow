import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import {
  EmptyState,
  ErrorState,
  FilterGroup,
  StatusTag,
  WorkingState,
} from "@/components/workspace/page-body";

afterEach(cleanup);

it("says loading in words beside decorative working squares", () => {
  render(<WorkingState label="Loading agents" />);
  const status = screen.getByRole("status");
  expect(status.textContent).toBe("Loading agents");
  const squares = status.querySelector('[aria-hidden="true"]');
  expect(squares?.children).toHaveLength(3);
});

it("gives an error a red-thread tag, plain text and a next step", () => {
  const retry = rs.fn();
  render(
    <ErrorState
      message="Could not load skills."
      detail="502 Bad Gateway"
      action={<button onClick={retry}>Try again</button>}
    />,
  );
  const alert = screen.getByRole("alert");
  expect(
    alert.querySelector("svg[data-error-tag]")?.getAttribute("aria-hidden"),
  ).toBe("true");
  expect(screen.getByText("Could not load skills.")).toBeDefined();
  expect(screen.getByText("502 Bad Gateway")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledTimes(1);
});

it("draws an empty state with a decorative canon Momo and one sentence", () => {
  render(<EmptyState momo="builder">No agents yet.</EmptyState>);
  const img = document.querySelector("[data-empty-state] img");
  expect(img?.getAttribute("src")).toBe("/momentum/momos/builder.svg");
  expect(img?.getAttribute("alt")).toBe("");
  expect(screen.getByText("No agents yet.")).toBeDefined();
  // Decorative: the Momo never reaches the accessibility tree.
  expect(screen.queryByRole("img")).toBeNull();
});

it("pairs every status colour with a word and a shape hook", () => {
  render(<StatusTag tone="unknown">Status unavailable</StatusTag>);
  const tag = screen.getByText("Status unavailable");
  expect(tag.getAttribute("data-tone")).toBe("unknown");
});

it("exposes filters as pressed toggle buttons in a named group, not tabs", () => {
  const onChange = rs.fn();
  render(
    <FilterGroup
      label="Status"
      value="all"
      onChange={onChange}
      options={[
        { value: "all", label: "All" },
        { value: "paused", label: "Paused" },
      ]}
    />,
  );
  const group = screen.getByRole("group", { name: "Status" });
  expect(group).toBeDefined();
  expect(screen.queryByRole("tab")).toBeNull();
  expect(
    screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Paused" }));
  expect(onChange).toHaveBeenCalledWith("paused");
});

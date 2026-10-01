import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, within } from "@testing-library/react";

import {
  PluginActionButton,
  PluginDirectory,
  type PluginDirectoryEntry,
} from "@/components/workspace/capabilities/plugin-directory";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: enUS, locale: "en-US" }),
}));

afterEach(cleanup);

function entry(
  id: string,
  category: PluginDirectoryEntry["category"],
  installed: boolean,
  guide = false,
): PluginDirectoryEntry {
  return {
    id,
    category,
    installed,
    guide,
    search: id,
    node: <article>{id}</article>,
  };
}

const entries = [
  entry("firecrawl", "research", false, true),
  entry("exa", "research", false, true),
  entry("tavily", "research", false),
  entry("wecom", "office", false),
  entry("github", "development", true),
  entry("notion", "knowledge", true),
];

it("puts connected tools first, in their own section", () => {
  render(<PluginDirectory entries={entries} />);
  const headings = screen
    .getAllByRole("heading", { level: 2 })
    .map((node) => node.textContent);
  expect(headings[0]).toBe("Connected");
  const connected = screen.getByTestId("plugin-connected");
  expect(
    within(connected)
      .getAllByRole("article")
      .map((node) => node.textContent),
  ).toEqual(["notion", "github"]);
  // A connected tool is not repeated under its category.
  expect(
    screen.queryByRole("heading", { name: "Development & operations" }),
  ).toBeNull();
  expect(screen.getByText("Available to connect")).toBeDefined();
});

it("lists integrations MomoBot can configure before setup guides", () => {
  render(<PluginDirectory entries={entries} />);
  const research = screen
    .getByRole("heading", { name: "Search & research" })
    .closest("section")!;
  expect(
    within(research)
      .getAllByRole("article")
      .map((node) => node.textContent),
  ).toEqual(["tavily", "firecrawl", "exa"]);
});

it("drops the Connected section and its divider when nothing is connected", () => {
  render(<PluginDirectory entries={entries.filter((e) => !e.installed)} />);
  expect(screen.queryByRole("heading", { name: "Connected" })).toBeNull();
  expect(screen.queryByText("Available to connect")).toBeNull();
});

it("shows only the Connected section under the connected filter", () => {
  render(<PluginDirectory entries={entries} installedOnly />);
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
  expect(screen.queryByText("Available to connect")).toBeNull();
});

it("gives Connect, Configure and Details different weights", () => {
  render(
    <>
      <PluginActionButton action="connect">Connect</PluginActionButton>
      <PluginActionButton action="configure">Configure</PluginActionButton>
      <PluginActionButton action="details">Details</PluginActionButton>
    </>,
  );
  const connect = screen.getByRole("button", { name: "Connect" });
  const configure = screen.getByRole("button", { name: "Configure" });
  const details = screen.getByRole("button", { name: "Details" });
  expect(connect.className).toContain("text-primary");
  expect(configure.className).not.toContain("text-primary");
  expect(details.getAttribute("data-variant")).toBe("ghost");
  expect(configure.getAttribute("data-variant")).toBe("outline");
});

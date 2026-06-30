import { describe, expect, it } from "vitest";

import { buildBreadcrumbs } from "@/components/shell/breadcrumbs";

describe("buildBreadcrumbs", () => {
  it("maps the root to the Overview landing page", () => {
    expect(buildBreadcrumbs("/")).toEqual([{ label: "Overview" }]);
  });

  it("maps the redirected /overview path to Overview too", () => {
    expect(buildBreadcrumbs("/overview")).toEqual([{ label: "Overview" }]);
  });

  it("maps the prompt list to a plain Prompts crumb", () => {
    expect(buildBreadcrumbs("/prompts")).toEqual([{ label: "Prompts" }]);
  });

  it("maps the new-prompt page", () => {
    expect(buildBreadcrumbs("/prompts/new")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "New prompt" },
    ]);
  });

  it("maps a per-prompt page and decodes the name", () => {
    expect(buildBreadcrumbs("/prompts/my%20prompt/versions")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "my prompt", to: "/prompts/my%20prompt/edit" },
      { label: "Versions" },
    ]);
  });

  it("maps the prompt editor page to a full Editor-leaf trail", () => {
    expect(buildBreadcrumbs("/prompts/greet/edit")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "greet", to: "/prompts/greet/edit" },
      { label: "Editor" },
    ]);
  });

  it("maps a deep version leaf (playground)", () => {
    expect(buildBreadcrumbs("/prompts/greet/versions/3/playground")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "greet", to: "/prompts/greet/versions" },
      { label: "Version 3" },
      { label: "Playground" },
    ]);
  });

  it("maps the traces page to a Traces leaf", () => {
    expect(buildBreadcrumbs("/prompts/greet/traces")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "greet", to: "/prompts/greet/edit" },
      { label: "Traces" },
    ]);
  });

  it("maps the version runs page to a Runs leaf", () => {
    expect(buildBreadcrumbs("/prompts/greet/versions/3/runs")).toEqual([
      { label: "Prompts", to: "/prompts" },
      { label: "greet", to: "/prompts/greet/versions" },
      { label: "Version 3" },
      { label: "Runs" },
    ]);
  });

  it("maps the golden-sets list to a plain crumb", () => {
    expect(buildBreadcrumbs("/datasets")).toEqual([{ label: "Golden sets" }]);
  });

  it("maps the new-golden-set page", () => {
    expect(buildBreadcrumbs("/datasets/new")).toEqual([
      { label: "Golden sets", to: "/datasets" },
      { label: "New golden set" },
    ]);
  });

  it("maps a golden-set edit page, decoding the name as a plain (non-linked) crumb", () => {
    // No /datasets/:name detail route exists, so the name must not be a link (would render blank).
    expect(buildBreadcrumbs("/datasets/my%20set/edit")).toEqual([
      { label: "Golden sets", to: "/datasets" },
      { label: "my set" },
      { label: "Edit" },
    ]);
  });

  it("maps the blocks list to a plain crumb", () => {
    expect(buildBreadcrumbs("/blocks")).toEqual([{ label: "Blocks" }]);
  });

  it("maps the new-block page", () => {
    expect(buildBreadcrumbs("/blocks/new")).toEqual([
      { label: "Blocks", to: "/blocks" },
      { label: "New block" },
    ]);
  });

  it("maps a block detail page to a plain leaf name (the current page)", () => {
    expect(buildBreadcrumbs("/blocks/intro")).toEqual([
      { label: "Blocks", to: "/blocks" },
      { label: "intro" },
    ]);
  });

  it("maps a block new-version page with the name as a linked parent", () => {
    expect(buildBreadcrumbs("/blocks/intro/versions/new")).toEqual([
      { label: "Blocks", to: "/blocks" },
      { label: "intro", to: "/blocks/intro" },
      { label: "New version" },
    ]);
  });

  it("maps the users page", () => {
    expect(buildBreadcrumbs("/users")).toEqual([{ label: "Users" }]);
  });

  it("maps the activity (audit log) page", () => {
    expect(buildBreadcrumbs("/activity")).toEqual([{ label: "Audit log" }]);
  });

  it("falls back to Overview for an unknown route", () => {
    expect(buildBreadcrumbs("/something-else")).toEqual([{ label: "Overview" }]);
  });
});

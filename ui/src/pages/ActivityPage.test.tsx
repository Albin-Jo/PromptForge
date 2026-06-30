import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ActivityPage } from "./ActivityPage";
import { useAuditEvents } from "../lib/audit/api";
import type { AuditEvent, AuditPage } from "../lib/audit/types";

vi.mock("../lib/audit/api", () => ({ useAuditEvents: vi.fn() }));
const mockedUseAuditEvents = vi.mocked(useAuditEvents);

function makeEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: "evt-1",
    actor: "alice@example.com",
    action: "promote",
    target: "prompt:greet",
    timestamp: "2026-06-30T10:00:00Z",
    ...overrides,
  };
}

function setQuery(state: { isPending?: boolean; isError?: boolean; error?: { message?: string } | null; data?: AuditPage }) {
  mockedUseAuditEvents.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useAuditEvents>);
}

function renderPage() {
  render(
    <MemoryRouter>
      <ActivityPage />
    </MemoryRouter>,
  );
}

describe("ActivityPage", () => {
  it("renders the page heading", () => {
    setQuery({ isPending: true });
    renderPage();
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
  });

  it("shows a loading state while pending", () => {
    setQuery({ isPending: true });
    renderPage();
    expect(screen.getByRole("status", { name: /loading activity/i })).toBeInTheDocument();
  });

  it("surfaces an error when the query fails", () => {
    setQuery({ isError: true, error: { message: "forbidden" } });
    renderPage();
    expect(screen.getByText(/Could not load activity/i)).toBeInTheDocument();
  });

  it("shows the empty state when no events exist", () => {
    setQuery({ data: { events: [], total: 0 } });
    renderPage();
    expect(screen.getByText("No activity yet")).toBeInTheDocument();
  });

  it("renders actor, action, target, and timestamp for each event", () => {
    setQuery({
      data: {
        events: [
          makeEvent({ actor: "alice@example.com", action: "promote", target: "prompt:greet" }),
          makeEvent({ id: "evt-2", actor: "bob@example.com", action: "create_version", target: "prompt:farewell" }),
        ],
        total: 2,
      },
    });
    renderPage();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("promote")).toBeInTheDocument();
    expect(screen.getByText("prompt:greet")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
    expect(screen.getByText("create_version")).toBeInTheDocument();
    expect(screen.getByText("prompt:farewell")).toBeInTheDocument();
  });
});

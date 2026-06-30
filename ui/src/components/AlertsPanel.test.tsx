import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AlertsPanel } from "./AlertsPanel";
import { useAlertPolicy, usePromptAlerts } from "../lib/alerts/api";
import type { Alert, AlertPolicy, PromptAlerts } from "../lib/alerts/types";

vi.mock("../lib/alerts/api", () => ({ usePromptAlerts: vi.fn(), useAlertPolicy: vi.fn() }));
const mockedUseAlerts = vi.mocked(usePromptAlerts);
const mockedUsePolicy = vi.mocked(useAlertPolicy);

function setAlerts(state: Partial<ReturnType<typeof usePromptAlerts>>) {
  mockedUseAlerts.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof usePromptAlerts>);
}

function setPolicy(state: Partial<ReturnType<typeof useAlertPolicy>>) {
  mockedUsePolicy.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useAlertPolicy>);
}

function response(alerts: Alert[]): PromptAlerts {
  return { name: "p", window: "7d", alerts };
}

const POLICY: AlertPolicy = {
  thresholds: [
    { key: "min_quality", label: "Minimum quality", value: 0.7, unit: "score" },
    { key: "max_error_rate", label: "Max error rate", value: 0.1, unit: "ratio" },
    { key: "max_cost_per_request_usd", label: "Max cost per request", value: 0.05, unit: "usd" },
    { key: "min_requests", label: "Minimum requests", value: 20, unit: "count" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  // Default: policy not yet loaded, so the thresholds line is absent unless a test opts in.
  setPolicy({ data: undefined });
});

describe("AlertsPanel", () => {
  it("renders each firing alert's severity label, scope, and message", () => {
    setAlerts({
      data: response([
        {
          kind: "error_rate_high",
          scope: "overall",
          observed: 0.12,
          threshold: 0.05,
          message: "error rate 12.0% exceeds 5.0% over 200 requests",
        },
        {
          kind: "quality_below_threshold",
          scope: "version:3",
          observed: 0.6,
          threshold: 0.7,
          message: "version 3 quality 0.60 below minimum 0.70",
        },
      ]),
    });

    render(<AlertsPanel name="p" window="7d" />);

    expect(screen.getByText("2 active alerts")).toBeInTheDocument();
    expect(screen.getByText("Error rate")).toBeInTheDocument();
    expect(screen.getByText("Prompt-wide")).toBeInTheDocument();
    expect(screen.getByText(/error rate 12.0% exceeds 5.0%/)).toBeInTheDocument();
    expect(screen.getByText("Quality floor")).toBeInTheDocument();
    expect(screen.getByText("Version 3")).toBeInTheDocument();
  });

  it("shows the healthy empty state when nothing is firing", () => {
    setAlerts({ data: response([]) });

    render(<AlertsPanel name="p" window="7d" />);

    expect(screen.getByText(/No drift detected/)).toBeInTheDocument();
    expect(screen.queryByText(/active alert/)).not.toBeInTheDocument();
  });

  it("orders the most-urgent alert first regardless of API order", () => {
    setAlerts({
      data: response([
        { kind: "cost_per_request_high", scope: "overall", observed: 1, threshold: 0.5, message: "cost high" },
        { kind: "error_rate_high", scope: "overall", observed: 0.2, threshold: 0.05, message: "errors high" },
      ]),
    });

    render(<AlertsPanel name="p" window="7d" />);

    const badges = screen.getAllByText(/Error rate|Cost/);
    expect(badges[0]).toHaveTextContent("Error rate");
  });

  describe("thresholds line", () => {
    it("renders each threshold from the fetched policy, formatted by unit", () => {
      setAlerts({ data: response([]) });
      setPolicy({ data: POLICY });

      render(<AlertsPanel name="p" window="7d" />);

      // unit-driven formatting: score → 0.70, ratio → 10.0%, usd → $0.05, count → 20.
      expect(screen.getByText(/Minimum quality 0\.70/)).toBeInTheDocument();
      expect(screen.getByText(/Max error rate 10\.0%/)).toBeInTheDocument();
      expect(screen.getByText(/Max cost per request \$0\.05/)).toBeInTheDocument();
      expect(screen.getByText(/Minimum requests 20/)).toBeInTheDocument();
    });

    it("omits the thresholds line until the policy has loaded", () => {
      setAlerts({ data: response([]) });
      setPolicy({ data: undefined });

      render(<AlertsPanel name="p" window="7d" />);

      expect(screen.queryByText(/Thresholds:/)).not.toBeInTheDocument();
    });
  });

  describe("dismiss / acknowledge", () => {
    const alert: Alert = {
      kind: "error_rate_high",
      scope: "overall",
      observed: 0.12,
      threshold: 0.05,
      message: "error rate high",
    };

    it("hides an alert after clicking Acknowledge", () => {
      setAlerts({ data: response([alert]) });
      render(<AlertsPanel name="p" window="7d" />);

      fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));

      expect(screen.queryByText("1 active alert")).not.toBeInTheDocument();
      expect(screen.getByText(/1 acknowledged alert/i)).toBeInTheDocument();
    });

    it("shows all-acknowledged state when every alert is dismissed", () => {
      setAlerts({ data: response([alert]) });
      render(<AlertsPanel name="p" window="7d" />);

      fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));

      expect(screen.getByText(/will reappear if the breach changes/i)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /acknowledge/i })).not.toBeInTheDocument();
    });

    it("reappears when observed value changes (breach shifted)", () => {
      setAlerts({ data: response([alert]) });
      const { rerender } = render(<AlertsPanel name="p" window="7d" />);
      fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));
      expect(screen.queryByText("1 active alert")).not.toBeInTheDocument();

      // breach worsens — same kind/scope, different observed
      const shifted: Alert = { ...alert, observed: 0.25 };
      setAlerts({ data: response([shifted]) });
      rerender(<AlertsPanel name="p" window="7d" />);

      expect(screen.getByText("1 active alert")).toBeInTheDocument();
    });

    it("persists dismissal to localStorage so it survives re-mount", () => {
      setAlerts({ data: response([alert]) });
      const { unmount } = render(<AlertsPanel name="p" window="7d" />);
      fireEvent.click(screen.getByRole("button", { name: /acknowledge/i }));
      unmount();

      render(<AlertsPanel name="p" window="7d" />);
      expect(screen.queryByText("1 active alert")).not.toBeInTheDocument();
      expect(screen.getByText(/1 acknowledged alert/i)).toBeInTheDocument();
    });
  });
});

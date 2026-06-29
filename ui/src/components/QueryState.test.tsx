import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryState } from "./QueryState";

// A minimal stand-in for a useQuery result, with only the fields QueryState reads.
function query<T>(overrides: Partial<{ isPending: boolean; isError: boolean; error: { message?: string } | null; data: T; refetch: () => void }>) {
  return { isPending: false, isError: false, error: null, data: undefined, ...overrides };
}

describe("QueryState", () => {
  it("renders Skeletons (not text) while pending", () => {
    const { container } = render(
      <QueryState query={query({ isPending: true })} label="metrics">
        {() => <span>loaded</span>}
      </QueryState>,
    );
    // Skeletons, with an accessible label standing in for the old visible text.
    expect(screen.getByRole("status", { name: /loading metrics…/i })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
    expect(screen.queryByText("loaded")).not.toBeInTheDocument();
  });

  it("shows the error message on failure, not the children", () => {
    render(
      <QueryState query={query({ isError: true, error: { message: "boom" } })} label="metrics">
        {() => <span>loaded</span>}
      </QueryState>,
    );
    expect(screen.getByText(/could not load metrics: boom/i)).toBeInTheDocument();
    expect(screen.queryByText("loaded")).not.toBeInTheDocument();
  });

  it("renders a Retry button that calls refetch on click", () => {
    const refetch = vi.fn();
    render(
      <QueryState query={query({ isError: true, error: { message: "boom" }, refetch })} label="metrics">
        {() => <span>loaded</span>}
      </QueryState>,
    );
    const button = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(button);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("omits the Retry button when no refetch is provided", () => {
    render(
      <QueryState query={query({ isError: true, error: { message: "boom" } })} label="metrics">
        {() => <span>loaded</span>}
      </QueryState>,
    );
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("renders the empty slot when isEmpty(data) is true", () => {
    render(
      <QueryState
        query={query({ data: [] as number[] })}
        isEmpty={(d) => d.length === 0}
        empty={<span>nothing here</span>}
      >
        {() => <span>loaded</span>}
      </QueryState>,
    );
    expect(screen.getByText("nothing here")).toBeInTheDocument();
    expect(screen.queryByText("loaded")).not.toBeInTheDocument();
  });

  it("calls children with the data on success", () => {
    render(
      <QueryState query={query({ data: { value: 42 } })}>
        {(d) => <span>value is {d.value}</span>}
      </QueryState>,
    );
    expect(screen.getByText(/value is 42/i)).toBeInTheDocument();
  });

  it("treats undefined data as still-loading even when not pending", () => {
    render(
      <QueryState query={query({ isPending: false, data: undefined })} label="scan">
        {() => <span>loaded</span>}
      </QueryState>,
    );
    expect(screen.getByRole("status", { name: /loading scan…/i })).toBeInTheDocument();
    expect(screen.queryByText("loaded")).not.toBeInTheDocument();
  });

  it("uses a caller-supplied loading slot over the default skeleton", () => {
    render(
      <QueryState
        query={query({ isPending: true })}
        label="metrics"
        loading={<span>custom loader</span>}
      >
        {() => <span>loaded</span>}
      </QueryState>,
    );
    expect(screen.getByText("custom loader")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

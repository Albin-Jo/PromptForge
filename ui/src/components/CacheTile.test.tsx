import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CacheTile } from "./CacheTile";
import { useCacheStats } from "../lib/cache/api";
import type { CacheStats } from "../lib/cache/types";

vi.mock("../lib/cache/api", () => ({ useCacheStats: vi.fn() }));
const mockedUseCacheStats = vi.mocked(useCacheStats);

function setStats(state: Partial<ReturnType<typeof useCacheStats>>) {
  mockedUseCacheStats.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...state,
  } as unknown as ReturnType<typeof useCacheStats>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CacheTile", () => {
  it("renders the hit-rate and the served/total + TTL when stats are present", () => {
    const stats: CacheStats = {
      prompt: "p",
      hits: 17,
      misses: 3,
      total: 20,
      hit_rate: 0.85,
      ttl_seconds: 30,
    };
    setStats({ data: stats });

    render(<CacheTile name="p" isAdmin={true} />);

    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText(/17\/20 served from cache · TTL 30s/)).toBeInTheDocument();
  });

  it("shows a no-traffic state when nothing has rendered yet", () => {
    setStats({
      data: { prompt: "p", hits: 0, misses: 0, total: 0, hit_rate: null, ttl_seconds: 30 },
    });

    render(<CacheTile name="p" isAdmin={true} />);

    expect(screen.getByText(/No render traffic yet/)).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders nothing for a non-admin (and never fetches)", () => {
    setStats({ data: undefined });

    const { container } = render(<CacheTile name="p" isAdmin={false} />);

    expect(container).toBeEmptyDOMElement();
  });
});

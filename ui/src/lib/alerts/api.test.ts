import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  apiFetch: vi.fn(),
}));
import { apiFetch } from "../api";
import { alertKeys, getPromptAlerts } from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

describe("getPromptAlerts", () => {
  it("GETs the windowed alerts endpoint, encoding the prompt name", async () => {
    mockedFetch.mockResolvedValue({ name: "my prompt", window: "7d", alerts: [] } as never);
    await getPromptAlerts("my prompt", "7d");
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/my%20prompt/alerts?window=7d", {
      signal: undefined,
    });
  });
});

describe("alertKeys", () => {
  it("keys per prompt and window so windows cache independently", () => {
    expect(alertKeys.detail("p", "24h")).toEqual(["alerts", "p", "24h"]);
    expect(alertKeys.detail("p", "30d")).toEqual(["alerts", "p", "30d"]);
  });
});

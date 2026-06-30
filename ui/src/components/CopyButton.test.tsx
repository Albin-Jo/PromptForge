import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CopyButton } from "./CopyButton";

const success = vi.fn();
const error = vi.fn();
vi.mock("../lib/toast", () => ({
  toast: { success: (...a: unknown[]) => success(...a) },
  toastError: (...a: unknown[]) => error(...a),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("CopyButton", () => {
  it("writes the text to the clipboard and confirms", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    // Override *after* setup() — userEvent installs its own clipboard stub on the navigator.
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    render(<CopyButton text="hello world" label="Copy prompt" />);
    await user.click(screen.getByRole("button", { name: "Copy prompt" }));

    expect(writeText).toHaveBeenCalledWith("hello world");
    expect(success).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Copy prompt" })).toHaveTextContent("Copied");
  });

  it("reports an error when the clipboard write fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    render(<CopyButton text="x" />);
    await user.click(screen.getByRole("button", { name: "Copy" }));

    expect(error).toHaveBeenCalled();
  });
});

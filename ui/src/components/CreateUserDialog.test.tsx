import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CreateUserDialog } from "./CreateUserDialog";
import { ApiError } from "../lib/api";
import { useCreateUser } from "../lib/users/api";

// Keep userCreateFieldErrors real (it's the mapping under test); stub only the mutation hook.
vi.mock("../lib/users/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/users/api")>()),
  useCreateUser: vi.fn(),
}));
vi.mock("../lib/toast", () => ({ toast: { success: vi.fn() }, toastError: vi.fn() }));

const mockedUseCreateUser = vi.mocked(useCreateUser);

// A mutate that drives onSuccess or onError so we can exercise both paths without a real network.
function stubMutation(behaviour: "success" | { error: unknown }) {
  const mutate = vi.fn((vars, opts) => {
    if (behaviour === "success") opts?.onSuccess?.({ email: vars.email, ...vars }, vars, undefined);
    else opts?.onError?.(behaviour.error, vars, undefined);
  });
  mockedUseCreateUser.mockReturnValue({ mutate, isPending: false } as never);
  return mutate;
}

beforeEach(() => vi.clearAllMocks());

async function openAndFill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /new user/i }));
  await user.type(screen.getByLabelText(/email/i), "taken@example.com");
  await user.type(screen.getByLabelText(/password/i), "pw-12345678");
}

describe("CreateUserDialog", () => {
  it("submits the typed values to the create mutation", async () => {
    const mutate = stubMutation("success");
    const user = userEvent.setup();
    render(<CreateUserDialog />);

    await openAndFill(user);
    await user.click(screen.getByRole("button", { name: /create user/i }));

    expect(mutate).toHaveBeenCalledWith(
      { email: "taken@example.com", password: "pw-12345678", role: "editor" },
      expect.anything(),
    );
  });

  it("pins a duplicate-email (409) to the email field", async () => {
    stubMutation({ error: new ApiError(409, "exists", { detail: "…" }) });
    const user = userEvent.setup();
    render(<CreateUserDialog />);

    await openAndFill(user);
    await user.click(screen.getByRole("button", { name: /create user/i }));

    expect(await screen.findByText("A user with this email already exists.")).toBeInTheDocument();
  });
});

import { describe, expect, it, vi, beforeEach } from "vitest";

// Replace apiFetch but keep the real ApiError so userCreateFieldErrors' instanceof checks work.
import { ApiError } from "../api";
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  apiFetch: vi.fn(),
}));
import { apiFetch } from "../api";
import {
  createUser,
  listUsers,
  updateUser,
  userCreateFieldErrors,
  userUpdateFieldErrors,
} from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

describe("listUsers / createUser", () => {
  it("GETs the admin user-list endpoint", async () => {
    mockedFetch.mockResolvedValue([] as never);
    await listUsers();
    expect(mockedFetch).toHaveBeenCalledWith("/auth/users", { signal: undefined });
  });

  it("POSTs the new user to the create endpoint", async () => {
    mockedFetch.mockResolvedValue({} as never);
    await createUser({ email: "a@example.com", password: "pw-12345678", role: "editor" });
    expect(mockedFetch).toHaveBeenCalledWith("/auth/users", {
      method: "POST",
      body: { email: "a@example.com", password: "pw-12345678", role: "editor" },
    });
  });

  it("PATCHes a role change to the update endpoint", async () => {
    mockedFetch.mockResolvedValue({} as never);
    await updateUser("u1", { role: "admin" });
    expect(mockedFetch).toHaveBeenCalledWith("/auth/users/u1", {
      method: "PATCH",
      body: { role: "admin" },
    });
  });

  it("PATCHes an active-flag change to the update endpoint", async () => {
    mockedFetch.mockResolvedValue({} as never);
    await updateUser("u1", { is_active: false });
    expect(mockedFetch).toHaveBeenCalledWith("/auth/users/u1", {
      method: "PATCH",
      body: { is_active: false },
    });
  });
});

describe("userCreateFieldErrors", () => {
  it("maps a 409 to the email field (duplicate)", () => {
    const err = new ApiError(409, "user 'a@example.com' already exists", { detail: "…" });
    expect(userCreateFieldErrors(err)).toEqual({
      email: "A user with this email already exists.",
    });
  });

  it("maps a 422 validation error to the offending field via loc", () => {
    const err = new ApiError(422, "unprocessable", {
      detail: [
        { loc: ["body", "password"], msg: "String should have at least 8 characters" },
        { loc: ["body", "email"], msg: "String should have at least 3 characters" },
      ],
    });
    expect(userCreateFieldErrors(err)).toEqual({
      password: "String should have at least 8 characters",
      email: "String should have at least 3 characters",
    });
  });

  it("falls back to a form-level message for anything else", () => {
    expect(userCreateFieldErrors(new ApiError(500, "boom", null))).toEqual({ form: "boom" });
    expect(userCreateFieldErrors(new Error("network"))).toEqual({
      form: "Could not create the user. Please try again.",
    });
  });
});

describe("userUpdateFieldErrors", () => {
  it("surfaces a 409 self-lockout as the API's reason (form-level)", () => {
    const err = new ApiError(409, "cannot remove the last active admin", { detail: "…" });
    expect(userUpdateFieldErrors(err)).toEqual({
      form: "cannot remove the last active admin",
    });
  });

  it("maps a 404 to a 'user gone' form message", () => {
    expect(userUpdateFieldErrors(new ApiError(404, "not found", null))).toEqual({
      form: "That user no longer exists.",
    });
  });

  it("falls back to a form-level message for anything else", () => {
    expect(userUpdateFieldErrors(new Error("network"))).toEqual({
      form: "Could not update the user. Please try again.",
    });
  });
});

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "../api";
import type { User, UserCreate, UserUpdate } from "./types";

export const userKeys = {
  all: ["users"] as const,
};

export function listUsers(signal?: AbortSignal): Promise<User[]> {
  return apiFetch<User[]>("/auth/users", { signal });
}

export function createUser(body: UserCreate): Promise<User> {
  return apiFetch<User>("/auth/users", { method: "POST", body });
}

export function updateUser(id: string, body: UserUpdate): Promise<User> {
  return apiFetch<User>(`/auth/users/${id}`, { method: "PATCH", body });
}

/** Server-state hook for the user list (admin-only endpoint). */
export function useUsers() {
  return useQuery({
    queryKey: userKeys.all,
    queryFn: ({ signal }) => listUsers(signal),
  });
}

/** Create a user; refreshes the list on success so the new row appears. */
export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.all });
    },
  });
}

/** Update a user's role and/or active flag; refreshes the list so the row reflects the change. */
export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UserUpdate }) => updateUser(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.all });
    },
  });
}

// Field-level errors for the create-user form. `form` is the catch-all for anything not tied to a
// specific input. Keeping the API→field mapping here (not in the component) makes it unit-testable.
export interface UserCreateFieldErrors {
  email?: string;
  password?: string;
  form?: string;
}

/**
 * Translate a failed create into messages the form can pin to the right input:
 *  - 409 (UserAlreadyExistsError) → the email is taken
 *  - 422 (Pydantic validation, e.g. password < 8 chars) → mapped to the offending field by `loc`
 *  - anything else → a single form-level message
 */
export function userCreateFieldErrors(err: unknown): UserCreateFieldErrors {
  if (!(err instanceof ApiError)) {
    return { form: "Could not create the user. Please try again." };
  }
  if (err.status === 409) {
    return { email: "A user with this email already exists." };
  }
  if (err.status === 422) {
    const detail = (err.body as { detail?: unknown } | null)?.detail;
    const out: UserCreateFieldErrors = {};
    if (Array.isArray(detail)) {
      for (const item of detail) {
        const loc = (item as { loc?: unknown }).loc;
        const field = Array.isArray(loc) ? String(loc[loc.length - 1]) : "";
        const msg = String((item as { msg?: unknown }).msg ?? "Invalid value");
        if (field === "password") out.password = msg;
        else if (field === "email") out.email = msg;
        else out.form = msg;
      }
    }
    return Object.keys(out).length > 0 ? out : { form: "Please check the fields and try again." };
  }
  return { form: err.message || "Could not create the user. Please try again." };
}

// Field-level errors for a user update (role / deactivate). `form` is the catch-all.
export interface UserUpdateFieldErrors {
  form?: string;
}

/**
 * Translate a failed update into a form-level message:
 *  - 409 (LastAdminError) → the change would leave no active admin; show the API's reason
 *  - 404 → the user was deleted out from under us
 *  - anything else → a single fallback message
 * There are no per-input errors (role is a closed select, is_active a toggle), so everything maps
 * to `form` — kept as its own shape so callers stay symmetric with userCreateFieldErrors.
 */
export function userUpdateFieldErrors(err: unknown): UserUpdateFieldErrors {
  if (!(err instanceof ApiError)) {
    return { form: "Could not update the user. Please try again." };
  }
  if (err.status === 409) {
    return { form: err.message || "This change would leave no active admin." };
  }
  if (err.status === 404) {
    return { form: "That user no longer exists." };
  }
  return { form: err.message || "Could not update the user. Please try again." };
}

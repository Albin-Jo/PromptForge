// The user-management data layer (Sprint 16g). A listed user is exactly the API's UserRead, which
// the auth layer already models as `User` — reuse it rather than declaring a parallel shape.
import type { User } from "../auth/types";

export type { User };

// Request body for POST /auth/users. Role is the same admin/editor pair the API accepts (UserCreate).
export interface UserCreate {
  email: string;
  password: string;
  role: "admin" | "editor";
}

// Request body for PATCH /auth/users/{id} (Sprint 31). Both fields optional — a caller changes
// role, active flag, or both; the API rejects an empty patch. Email/password aren't editable here.
export interface UserUpdate {
  role?: "admin" | "editor";
  is_active?: boolean;
}

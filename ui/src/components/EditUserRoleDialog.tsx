import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useUpdateUser, userUpdateFieldErrors } from "../lib/users/api";
import type { UserUpdateFieldErrors } from "../lib/users/api";
import type { User } from "../lib/users/types";
import { toast } from "../lib/toast";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

// Same restyled native <select> as CreateUserDialog — one dense-control convention across forms.
const selectClasses =
  "mt-1 w-full rounded-md border border-input bg-background text-foreground shadow-sm px-3 py-2 " +
  "text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

interface EditUserRoleDialogProps {
  /** The user whose role is being edited, or null when the dialog is closed. */
  user: User | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Change a user's role (admin ↔ editor). A 409 (`LastAdminError`) — demoting the last active
 * admin — is *state, not failure*: we keep the dialog open and show the reason as a form error,
 * mirroring the guarded block/dataset deletes (ADR 0023). A role change revokes the user's
 * outstanding tokens server-side (ADR 0029), so they must sign in again to pick up the new role.
 */
export function EditUserRoleDialog({ user, onOpenChange }: EditUserRoleDialogProps) {
  const [role, setRole] = useState<"admin" | "editor">("editor");
  const [errors, setErrors] = useState<UserUpdateFieldErrors>({});
  const updateUser = useUpdateUser();

  // Seed the select with the user's current role each time the dialog opens on a new row.
  useEffect(() => {
    if (user) {
      setRole(user.role === "admin" ? "admin" : "editor");
      setErrors({});
    }
  }, [user]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    setErrors({});
    updateUser.mutate(
      { id: user.id, body: { role } },
      {
        onSuccess: () => {
          toast.success(`Updated ${user.email} to ${role}`);
          onOpenChange(false);
        },
        onError: (err) => setErrors(userUpdateFieldErrors(err)),
      },
    );
  }

  return (
    <Dialog open={user !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit role</DialogTitle>
          <DialogDescription>
            Change the role for {user?.email}. They’ll be signed out and must log in again for it to
            take effect.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm font-medium text-foreground">
            Role
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "editor")}
              className={cn(selectClasses)}
            >
              <option value="editor">Editor — can author and run</option>
              <option value="admin">Admin — full access, incl. user management</option>
            </select>
          </label>

          {errors.form && (
            <p role="alert" className="text-destructive text-sm">
              {errors.form}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={updateUser.isPending}>
              {updateUser.isPending ? "Saving…" : "Save role"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

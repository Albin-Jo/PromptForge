import { useState } from "react";

import { ApiError } from "../lib/api";
import { useUpdateUser } from "../lib/users/api";
import type { User } from "../lib/users/types";
import { toast, toastError } from "../lib/toast";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

interface SetUserActiveDialogProps {
  /** The user to deactivate/reactivate, or null when the dialog is closed. */
  user: User | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Confirm-then-toggle a user's active flag. Deactivating revokes their outstanding tokens
 * (ADR 0029) — they're signed out everywhere — which is why it's a confirm step, not a one-click
 * toggle. A 409 (`LastAdminError`, deactivating the last active admin) is *state, not failure*: we
 * keep the dialog open and show the reason, like the guarded block delete (ADR 0023/0027).
 */
export function SetUserActiveDialog({ user, onOpenChange }: SetUserActiveDialogProps) {
  const updateUser = useUpdateUser();
  const [blockedMessage, setBlockedMessage] = useState<string | null>(null);

  // Fix the direction from the user's current state when the dialog opens.
  const deactivating = user?.is_active ?? true;

  function handleConfirm() {
    if (!user) return;
    setBlockedMessage(null);
    updateUser.mutate(
      { id: user.id, body: { is_active: !user.is_active } },
      {
        onSuccess: () => {
          toast.success(`${deactivating ? "Deactivated" : "Reactivated"} ${user.email}`);
          onOpenChange(false);
        },
        onError: (err) => {
          // 409 = would remove the last active admin; the detail says so. Stay open.
          if (err instanceof ApiError && err.status === 409) {
            setBlockedMessage(err.message);
            return;
          }
          toastError(err, "Could not update the user.");
        },
      },
    );
  }

  function handleOpenChange(open: boolean) {
    if (!open) setBlockedMessage(null);
    onOpenChange(open);
  }

  return (
    <Dialog open={user !== null} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{deactivating ? "Deactivate user" : "Reactivate user"}</DialogTitle>
          <DialogDescription>
            {deactivating
              ? `Deactivate ${user?.email}? They’ll be signed out everywhere and can’t log in until reactivated.`
              : `Reactivate ${user?.email}? They’ll be able to sign in again.`}
          </DialogDescription>
        </DialogHeader>

        {blockedMessage && <p className="text-sm text-destructive">{blockedMessage}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={deactivating ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={updateUser.isPending}
          >
            {updateUser.isPending
              ? "Saving…"
              : deactivating
                ? "Deactivate"
                : "Reactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

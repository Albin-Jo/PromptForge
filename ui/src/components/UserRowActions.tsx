import { useState } from "react";
import { MoreHorizontal } from "lucide-react";

import type { User } from "../lib/users/types";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { EditUserRoleDialog } from "./EditUserRoleDialog";
import { SetUserActiveDialog } from "./SetUserActiveDialog";

/**
 * Per-row admin actions for a user: a ⋯ menu opening "Edit role" and "Deactivate/Reactivate".
 * The whole Users page is behind RequireAdmin, so these need no further role gate. Each menu item
 * opens a controlled dialog (open when its user state is non-null) — the same null-prop pattern as
 * DeleteBlockDialog.
 */
export function UserRowActions({ user }: { user: User }) {
  const [editRoleUser, setEditRoleUser] = useState<User | null>(null);
  const [activeUser, setActiveUser] = useState<User | null>(null);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={`Actions for ${user.email}`}>
            <MoreHorizontal className="size-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuItem onSelect={() => setEditRoleUser(user)}>Edit role</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setActiveUser(user)}>
            {user.is_active ? "Deactivate" : "Reactivate"}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <EditUserRoleDialog
        user={editRoleUser}
        onOpenChange={(open) => !open && setEditRoleUser(null)}
      />
      <SetUserActiveDialog
        user={activeUser}
        onOpenChange={(open) => !open && setActiveUser(null)}
      />
    </>
  );
}

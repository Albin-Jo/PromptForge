import { Users } from "lucide-react";

import { useUsers } from "../lib/users/api";
import { QueryState } from "../components/QueryState";
import { EmptyState } from "../components/EmptyState";
import { CreateUserDialog } from "../components/CreateUserDialog";
import { UserRowActions } from "../components/UserRowActions";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { cn } from "../lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";

// Admin gets a stronger badge than editor so the table scans at a glance.
function RoleBadge({ role }: { role: string }) {
  return <Badge variant={role === "admin" ? "default" : "outline"}>{role}</Badge>;
}

// Active users get no badge (the norm); deactivated ones get a muted "inactive" marker so a
// disabled account is obvious at a glance without reading every row.
function StatusBadge({ active }: { active: boolean }) {
  return active ? (
    <span className="text-muted-foreground text-sm">Active</span>
  ) : (
    <Badge variant="secondary">Inactive</Badge>
  );
}

// Admin-only user management (Sprint 16g): list users and create new ones. The route is gated by
// RequireAdmin and the nav entry is hidden for non-admins, so a non-admin never reaches this page.
export function UsersPage() {
  const query = useUsers();

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <CreateUserDialog />
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        Everyone who can sign in. Editors can author and run; admins can also manage users.
      </p>

      <div className="mt-6">
        <QueryState
          query={query}
          label="users"
          isEmpty={(users) => users.length === 0}
          empty={
            <EmptyState
              icon={Users}
              title="No users yet"
              description="Create the first teammate to give them access."
            />
          }
        >
          {(users) => (
            <Card className="py-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id} className={cn(!user.is_active && "opacity-60")}>
                      <TableCell className="font-medium">{user.email}</TableCell>
                      <TableCell>
                        <RoleBadge role={user.role} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge active={user.is_active} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(user.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <UserRowActions user={user} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </QueryState>
      </div>
    </div>
  );
}

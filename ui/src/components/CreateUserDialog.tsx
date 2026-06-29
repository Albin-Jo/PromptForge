import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";

import { useCreateUser, userCreateFieldErrors } from "../lib/users/api";
import type { UserCreateFieldErrors } from "../lib/users/api";
import { toast } from "../lib/toast";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";

// Native <select> restyled onto tokens — same dense-control pattern as EvalPanel.
const selectClasses =
  "mt-1 w-full rounded-md border border-input bg-background text-foreground shadow-sm px-3 py-2 " +
  "text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

// One field-level message under an input, tied to it for assistive tech.
function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="text-destructive mt-1 text-xs">
      {message}
    </p>
  );
}

// Admin-only create-user dialog (Sprint 16g). Owns its open state + a trigger button. Validation
// failures from the API are pinned to the offending field (duplicate email, weak password) via
// userCreateFieldErrors; anything unmapped shows as a single form-level message.
export function CreateUserDialog() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "editor">("editor");
  const [errors, setErrors] = useState<UserCreateFieldErrors>({});

  const createUser = useCreateUser();

  function reset() {
    setEmail("");
    setPassword("");
    setRole("editor");
    setErrors({});
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) reset(); // clear the form (and any errors) whenever the dialog closes
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setErrors({});
    createUser.mutate(
      { email: email.trim(), password, role },
      {
        onSuccess: (user) => {
          toast.success(`Created ${user.email}`);
          setOpen(false);
          reset();
        },
        onError: (err) => setErrors(userCreateFieldErrors(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="size-4" aria-hidden />
          New user
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
          <DialogDescription>
            Add a teammate. They sign in with this email and password.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="block text-sm font-medium text-foreground">
            Email
            <Input
              type="email"
              required
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@example.com"
              aria-invalid={errors.email ? true : undefined}
              aria-describedby={errors.email ? "create-user-email-error" : undefined}
              className="mt-1"
            />
            <FieldError id="create-user-email-error" message={errors.email} />
          </label>

          <label className="block text-sm font-medium text-foreground">
            Password
            <Input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? "create-user-password-error" : undefined}
              className="mt-1"
            />
            <FieldError id="create-user-password-error" message={errors.password} />
          </label>

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

          {errors.form && <p className="text-destructive text-sm">{errors.form}</p>}

          <DialogFooter>
            <Button type="submit" disabled={createUser.isPending}>
              {createUser.isPending ? "Creating…" : "Create user"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

import { useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useCan } from "../lib/auth/AuthContext";
import { toast } from "../lib/toast";

// Route guard for admin-only sections (Sprint 16g). It nests *inside* RequireAuth, so the user is
// already known to be authenticated; here we only check the role. A non-admin is sent to the
// overview rather than shown a page with nothing they can use (hide, don't disable) — but we fire a
// toast first (Sprint 19) so the bounce isn't a silent, disorienting teleport.
export function RequireAdmin() {
  const isAdmin = useCan("admin");
  // Toast from an effect, not during render: toast() schedules a state update in the toast library,
  // and triggering that mid-render warns ("cannot update a component while rendering another").
  useEffect(() => {
    if (!isAdmin) toast.error("Admin access required");
  }, [isAdmin]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}

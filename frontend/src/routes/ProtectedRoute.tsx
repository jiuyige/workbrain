import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export function ProtectedRoute() {
  const location = useLocation();
  const { currentUser, isLoading } = useAuth();

  if (isLoading) {
    return (
      <main className="session-loading" role="status">
        正在恢复登录状态…
      </main>
    );
  }

  if (!currentUser) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

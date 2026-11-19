import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useSelector } from "react-redux";

import { selectAuth } from "./authSlice";

export default function RequireAuth() {
  const { accessToken } = useSelector(selectAuth);
  const location = useLocation();
  if (!accessToken) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <Outlet />;
}

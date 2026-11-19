import { Navigate } from "react-router-dom";

/** Pure role gate so both the app route and tests use one decision point. */
export default function RoleGate({ roles = [], allowed, redirect = "/dashboard", children }) {
  if (!roles.includes(allowed)) {
    return <Navigate to={redirect} replace />;
  }
  return children;
}

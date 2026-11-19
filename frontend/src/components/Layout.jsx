import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";

import { useGetMeQuery } from "../app/api";
import { logout, selectAuth, selectRoles, setMember } from "../features/auth/authSlice";
import { useEffect } from "react";

export default function Layout() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { member } = useSelector(selectAuth);
  const roles = useSelector(selectRoles);
  const { data } = useGetMeQuery();

  useEffect(() => {
    if (data) dispatch(setMember(data));
  }, [data, dispatch]);

  function signOut() {
    dispatch(logout());
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/dashboard" className="brand">
          Pay<span>Plan</span>
        </Link>
        <nav className="nav">
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/history">History</NavLink>
          {roles.includes("support") ? <NavLink to="/ops">Ops</NavLink> : null}
        </nav>
        <div className="account">
          <span>{member?.display_name || "Member"}</span>
          <button className="button button-ghost" type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
      <footer className="footer muted small">
        PayPlan · interest-free installments · demo environment
      </footer>
    </div>
  );
}

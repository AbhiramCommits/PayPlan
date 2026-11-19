import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";

import { useLazyGetMeQuery, useLoginMutation } from "../../app/api";
import { setMember } from "./authSlice";

export default function LoginPage() {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const [login, { isLoading }] = useLoginMutation();
  const [loadMe] = useLazyGetMeQuery();
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo12345");
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    try {
      await login({ username, password }).unwrap();
      const me = await loadMe().unwrap();
      dispatch(setMember(me));
      navigate("/dashboard");
    } catch (err) {
      setError(
        err?.data?.error?.message ||
          err?.data?.detail ||
          "Could not sign in. Check your credentials.",
      );
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card card">
        <p className="brand brand-large">
          Pay<span>Plan</span>
        </p>
        <h1>Welcome back</h1>
        <p className="muted">
          Sign in to see your spending power, installment plans, and repayment history.
        </p>
        <form onSubmit={handleSubmit} className="form">
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <button className="button button-primary" type="submit" disabled={isLoading}>
            {isLoading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted small">
          Demo member: <code>demo / demo12345</code> · Support:{" "}
          <code>support / support12345</code>
        </p>
      </div>
    </div>
  );
}

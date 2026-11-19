import { useState } from "react";
import { useSelector } from "react-redux";

import {
  useOpsAdjustLimitMutation,
  useOpsGetAuditQuery,
  useOpsGetMemberQuery,
  useOpsRescheduleInstallmentMutation,
  useOpsSearchMembersQuery,
  useOpsWaiveInstallmentMutation,
} from "../../app/api";
import RoleGate from "../../components/RoleGate";
import StatusChip from "../../components/StatusChip";
import { useGetMeQuery } from "../../app/api";
import { selectRoles } from "../auth/authSlice";
import { formatDate, formatMoney } from "../../utils";

export function OpsRoute() {
  const roles = useSelector(selectRoles);
  const { data: me, isLoading } = useGetMeQuery();
  if (isLoading) return <p className="muted">Checking role…</p>;
  return (
    <RoleGate roles={roles.length ? roles : me?.roles || []} allowed="support">
      <OpsPage />
    </RoleGate>
  );
}

export default function OpsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rescheduleDates, setRescheduleDates] = useState({});
  const [limitDollars, setLimitDollars] = useState("");

  const { data: searchResults, isFetching: searching } = useOpsSearchMembersQuery(search);
  const { data: member, isLoading: memberLoading } = useOpsGetMemberQuery(selectedId, {
    skip: !selectedId,
  });
  const { data: audit } = useOpsGetAuditQuery(selectedId, { skip: !selectedId });
  const [waiveInstallment, { isLoading: waiving }] = useOpsWaiveInstallmentMutation();
  const [rescheduleInstallment] = useOpsRescheduleInstallmentMutation();
  const [adjustLimit, { isLoading: adjusting }] = useOpsAdjustLimitMutation();

  function resetFeedback() {
    setMessage("");
    setError("");
  }

  async function handleWaive(installment) {
    resetFeedback();
    try {
      const result = await waiveInstallment({
        id: installment.id,
        reason: "support waiver",
      }).unwrap();
      setMessage(`Waived installment #${installment.sequence} (audit #${result.audit_id}).`);
    } catch (err) {
      setError(err?.data?.error?.message || "Could not waive installment.");
    }
  }

  async function handleReschedule(installment) {
    resetFeedback();
    const dueDate = rescheduleDates[installment.id];
    if (!dueDate) {
      setError("Choose a new due date first.");
      return;
    }
    try {
      const result = await rescheduleInstallment({
        id: installment.id,
        dueDate,
        reason: "support reschedule",
      }).unwrap();
      setMessage(
        `Moved installment #${installment.sequence} to ${result.installment.due_date} (audit #${result.audit_id}).`,
      );
    } catch (err) {
      setError(err?.data?.error?.message || "Could not reschedule installment.");
    }
  }

  async function handleLimit(event) {
    event.preventDefault();
    resetFeedback();
    const cents = Math.round(Number(limitDollars) * 100);
    if (!Number.isFinite(cents) || cents < 0) {
      setError("Enter a valid dollar amount.");
      return;
    }
    try {
      const result = await adjustLimit({
        id: member.id,
        limitCents: cents,
        reason: "support adjustment",
      }).unwrap();
      setMessage(
        `Limit set to ${formatMoney(result.limit.limit_cents)} (audit #${result.audit_id}).`,
      );
      setLimitDollars("");
    } catch (err) {
      setError(err?.data?.error?.message || "Could not adjust the limit.");
    }
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Support operations</p>
          <h1>Member lookup</h1>
          <p className="muted">Search by external id, username, or email. Every action is audited.</p>
        </div>
      </div>

      <form
        className="search-row"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(query.trim());
        }}
      >
        <input
          placeholder="Search members…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search members"
        />
        <button className="button button-primary" type="submit">
          Search
        </button>
      </form>

      <section className="card">
        {searching ? <p className="muted">Searching…</p> : null}
        {(searchResults?.results || []).map((result) => (
          <button
            type="button"
            key={result.id}
            className={`member-row ${selectedId === result.id ? "selected" : ""}`}
            onClick={() => {
              setSelectedId(result.id);
              resetFeedback();
            }}
          >
            <span>
              <strong>{result.display_name}</strong>
              <span className="muted small"> · {result.email}</span>
            </span>
            <span className="muted small">
              {formatMoney(result.available_cents)} available · <StatusChip status={result.status} />
            </span>
          </button>
        ))}
        {search && !searching && !(searchResults?.results || []).length ? (
          <p className="muted">No members matched “{search}”.</p>
        ) : null}
        {!search ? <p className="muted">Search to load a member.</p> : null}
      </section>

      {message ? <p className="form-success">{message}</p> : null}
      {error ? <p className="form-error">{error}</p> : null}

      {memberLoading ? <p className="muted">Loading member…</p> : null}
      {member ? (
        <>
          <section className="card">
            <div className="plan-head">
              <div>
                <p className="eyebrow">Member</p>
                <h2>{member.display_name}</h2>
                <p className="muted small">
                  {member.email} · {member.external_id} · {member.risk_tier}
                </p>
              </div>
              <div className="stats-inline">
                <span>
                  Limit <strong>{formatMoney(member.limit_cents)}</strong>
                </span>
                <span>
                  Available <strong>{formatMoney(member.available_cents)}</strong>
                </span>
                <span>
                  Base <strong>{formatMoney(member.base_limit_cents)}</strong>
                </span>
              </div>
            </div>
            <form className="inline-form" onSubmit={handleLimit}>
              <label>
                Set manual limit ($)
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={limitDollars}
                  onChange={(event) => setLimitDollars(event.target.value)}
                  placeholder="1500.00"
                />
              </label>
              <button className="button button-primary" type="submit" disabled={adjusting}>
                {adjusting ? "Saving…" : "Adjust limit"}
              </button>
            </form>
          </section>

          {(member.plans || []).map((plan) => (
            <section className="card" key={plan.id}>
              <div className="plan-head">
                <div>
                  <p className="eyebrow">Plan #{plan.id}</p>
                  <h3>{plan.product_name}</h3>
                  <p className="muted small">
                    {formatMoney(plan.principal_cents)} · {plan.paid_count}/{plan.num_installments}{" "}
                    paid · next due {formatDate(plan.next_due_date)}
                  </p>
                </div>
                <StatusChip status={plan.status} />
              </div>
              <div className="table-wrap">
                <table className="data-table" aria-label={`Plan ${plan.id} installments`}>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Due</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Waive</th>
                      <th>Reschedule</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.installments.map((installment) => (
                      <tr key={installment.id}>
                        <td>{installment.sequence}</td>
                        <td>{formatDate(installment.due_date)}</td>
                        <td>{formatMoney(installment.amount_cents)}</td>
                        <td>
                          <StatusChip status={installment.status} />
                        </td>
                        <td>
                          {["PAID", "WAIVED"].includes(installment.status) ? (
                            <span className="muted small">—</span>
                          ) : (
                            <button
                              type="button"
                              className="button button-ghost"
                              onClick={() => handleWaive(installment)}
                              disabled={waiving}
                            >
                              Waive
                            </button>
                          )}
                        </td>
                        <td>
                          <div className="inline-form tight">
                            <input
                              type="date"
                              aria-label={`New due date for installment ${installment.sequence}`}
                              value={rescheduleDates[installment.id] || ""}
                              onChange={(event) =>
                                setRescheduleDates((current) => ({
                                  ...current,
                                  [installment.id]: event.target.value,
                                }))
                              }
                            />
                            <button
                              type="button"
                              className="button button-ghost"
                              onClick={() => handleReschedule(installment)}
                            >
                              Move
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}

          <section className="card">
            <div className="section-head">
              <h3>Audit trail</h3>
              <span className="muted small">Latest actions</span>
            </div>
            {(audit?.results || []).length === 0 ? (
              <p className="muted">No support actions recorded for this member.</p>
            ) : (
              <ul className="audit-list">
                {(audit?.results || []).map((entry) => (
                  <li key={entry.id}>
                    <StatusChip status="WAIVED" />
                    <strong>{entry.action}</strong>
                    <span className="muted small">
                      by {entry.actor_username} · {new Date(entry.created_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

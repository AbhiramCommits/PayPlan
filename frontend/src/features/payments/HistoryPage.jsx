import { useState } from "react";

import { useGetPaymentsQuery } from "../../app/api";
import StatusChip from "../../components/StatusChip";
import { formatDate, formatMoney } from "../../utils";

const PAGE_SIZE = 25;

export default function HistoryPage() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading, error } = useGetPaymentsQuery({ status, page });

  const count = data?.count || 0;
  const pages = Math.max(Math.ceil(count / PAGE_SIZE), 1);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Repayments</p>
          <h1>Payment history</h1>
          <p className="muted">Every charge attempt, including declined and recovered payments.</p>
        </div>
        <label className="inline-field">
          Status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="SUCCEEDED">Succeeded</option>
            <option value="FAILED">Failed</option>
            <option value="PENDING">Pending</option>
            <option value="REFUNDED">Refunded</option>
          </select>
        </label>
      </div>

      {isLoading ? <p className="muted">Loading payments…</p> : null}
      {error ? <p className="form-error">Could not load payment history.</p> : null}

      {data ? (
        <>
          <div className="table-wrap">
            <table className="data-table" aria-label="Repayment history">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Product</th>
                  <th>Amount</th>
                  <th>Attempt</th>
                  <th>Status</th>
                  <th>Gateway ref</th>
                </tr>
              </thead>
              <tbody>
                {(data.results || []).map((payment) => (
                  <tr key={payment.id}>
                    <td>{formatDate(payment.created_at?.slice(0, 10))}</td>
                    <td>{payment.product_name || "—"}</td>
                    <td>{formatMoney(payment.amount_cents)}</td>
                    <td>{payment.attempt_no}</td>
                    <td>
                      <StatusChip status={payment.status} />
                      {payment.failure_code ? (
                        <span className="muted small"> {payment.failure_code}</span>
                      ) : null}
                    </td>
                    <td className="muted small">{payment.gateway_ref || "—"}</td>
                  </tr>
                ))}
                {data.results?.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      No payments match this filter.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <button
              type="button"
              className="button button-ghost"
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(value - 1, 1))}
            >
              Previous
            </button>
            <span className="muted small">
              Page {page} of {pages} · {count} payments
            </span>
            <button
              type="button"
              className="button button-ghost"
              disabled={page >= pages}
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

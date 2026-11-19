import { Link } from "react-router-dom";

import StatusChip from "./StatusChip";
import { formatDate, formatMoney } from "../utils";

export default function PlanCard({ plan }) {
  const total = plan.total_count || plan.num_installments || 0;
  const paid = plan.paid_count || 0;
  const pct = total ? Math.round((paid / total) * 100) : 0;
  return (
    <article className="card plan-card" data-testid="plan-card">
      <div className="plan-head">
        <div>
          <p className="eyebrow">Plan #{plan.id}</p>
          <h3>{plan.product_name}</h3>
        </div>
        <StatusChip status={plan.status} />
      </div>
      <p className="muted">
        {formatMoney(plan.principal_cents)} · {plan.num_installments} payments ·{" "}
        {plan.cadence.toLowerCase()}
      </p>
      <div className="progress" aria-label={`Installment progress ${paid} of ${total}`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="muted small">
        {paid} of {total} paid · next due {formatDate(plan.next_due_date)}
      </p>
      <Link className="button button-ghost" to={`/plans/${plan.id}`}>
        View schedule
      </Link>
    </article>
  );
}

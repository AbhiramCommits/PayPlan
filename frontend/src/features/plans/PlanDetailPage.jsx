import { Link, useParams } from "react-router-dom";

import { useCreatePaymentMutation, useGetPlanQuery } from "../../app/api";
import ScheduleTable from "../../components/ScheduleTable";
import StatusChip from "../../components/StatusChip";
import { formatDate, formatMoney } from "../../utils";

export default function PlanDetailPage() {
  const { id } = useParams();
  const { data: plan, isLoading, error } = useGetPlanQuery(id);
  const [createPayment] = useCreatePaymentMutation();

  if (isLoading) return <p className="muted">Loading schedule…</p>;
  if (error || !plan) return <p className="form-error">Plan not found.</p>;

  async function payInstallment(installment, idempotencyKey) {
    return createPayment({ installment: installment.id, idempotencyKey }).unwrap();
  }

  const paidCount = plan.installments.filter((item) => item.status === "PAID").length;

  return (
    <div className="stack">
      <Link to="/dashboard" className="muted small">
        ← Back to dashboard
      </Link>
      <div className="page-head">
        <div>
          <p className="eyebrow">Plan #{plan.id}</p>
          <h1>{plan.product_name}</h1>
          <p className="muted">
            {formatMoney(plan.principal_cents)} across {plan.num_installments} payments ·{" "}
            {plan.cadence.toLowerCase()} · started {formatDate(plan.start_date)}
          </p>
        </div>
        <StatusChip status={plan.status} />
      </div>

      <div className="stat-row">
        <div className="card stat">
          <span className="muted small">Paid</span>
          <strong>
            {paidCount} / {plan.num_installments}
          </strong>
        </div>
        <div className="card stat">
          <span className="muted small">Next due</span>
          <strong>{formatDate(plan.next_due_date)}</strong>
        </div>
        <div className="card stat">
          <span className="muted small">Principal</span>
          <strong>{formatMoney(plan.principal_cents)}</strong>
        </div>
      </div>

      <section>
        <div className="section-head">
          <h2>Installment schedule</h2>
          <span className="muted small">
            Interest-free. Pay early at any time — the button reuses one idempotency key.
          </span>
        </div>
        <ScheduleTable installments={plan.installments} onPay={payInstallment} />
      </section>
    </div>
  );
}

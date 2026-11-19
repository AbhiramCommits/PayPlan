import { formatDate, formatMoney } from "../utils";

export default function SpendingPowerCard({ member }) {
  if (!member) return null;
  const used = Math.max(member.limit_cents - member.available_cents, 0);
  const pct = member.limit_cents
    ? Math.min((used / member.limit_cents) * 100, 100)
    : 0;
  return (
    <section className="card power-card" data-testid="spending-power">
      <div className="power-top">
        <div>
          <p className="eyebrow">Available spending power</p>
          <p className="power-value">{formatMoney(member.available_cents)}</p>
          <p className="muted">
            of {formatMoney(member.limit_cents)} limit · next due{" "}
            {formatDate(member.next_due_date)}
          </p>
        </div>
        <div className="power-meta">
          <span className="muted">Base limit</span>
          <strong>{formatMoney(member.base_limit_cents)}</strong>
          <span className="muted">Risk tier</span>
          <strong>{member.risk_tier.replace("_", " ")}</strong>
        </div>
      </div>
      <div className="meter" aria-label="Spending power used">
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="muted small">
        {formatMoney(used)} currently reserved across active plans.
      </p>
    </section>
  );
}

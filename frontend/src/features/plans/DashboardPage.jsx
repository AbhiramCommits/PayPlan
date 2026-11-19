import { useGetPlansQuery, useGetMeQuery } from "../../app/api";
import PlanCard from "../../components/PlanCard";
import SpendingPowerCard from "../../components/SpendingPowerCard";

export default function DashboardPage() {
  const { data: member, isLoading: meLoading, error: meError } = useGetMeQuery();
  const { data: plans, isLoading: plansLoading, error: plansError } = useGetPlansQuery();

  if (meLoading || plansLoading) return <p className="muted">Loading your dashboard…</p>;
  if (meError) return <p className="form-error">Could not load your profile.</p>;

  const activePlans = (plans?.results || []).filter((plan) =>
    ["ACTIVE", "DELINQUENT"].includes(plan.status),
  );
  const completed = (plans?.results || []).filter((plan) => plan.status === "COMPLETED");

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Member dashboard</p>
          <h1>Hi, {member?.display_name?.split(" ")[0] || "there"}.</h1>
        </div>
      </div>

      <SpendingPowerCard member={member} />

      <section>
        <div className="section-head">
          <h2>Active plans</h2>
          <span className="muted small">{activePlans.length} open</span>
        </div>
        {plansError ? <p className="form-error">Could not load plans.</p> : null}
        {activePlans.length === 0 ? (
          <p className="card muted">No active plans yet.</p>
        ) : (
          <div className="grid">
            {activePlans.map((plan) => (
              <PlanCard key={plan.id} plan={plan} />
            ))}
          </div>
        )}
      </section>

      {completed.length > 0 ? (
        <section>
          <div className="section-head">
            <h2>Completed</h2>
          </div>
          <div className="grid">
            {completed.map((plan) => (
              <PlanCard key={plan.id} plan={plan} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

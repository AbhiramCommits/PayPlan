import PayNowButton from "./PayNowButton";
import StatusChip from "./StatusChip";
import { formatDate, formatMoney } from "../utils";

const PAYABLE = new Set(["SCHEDULED", "DUE", "FAILED", "LATE"]);

export default function ScheduleTable({ installments = [], onPay }) {
  return (
    <div className="table-wrap">
      <table className="data-table" aria-label="Installment schedule">
        <thead>
          <tr>
            <th>#</th>
            <th>Due date</th>
            <th>Amount</th>
            <th>Paid</th>
            <th>Status</th>
            <th aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {installments.map((installment) => {
            const payable =
              onPay && PAYABLE.has(installment.status) && installment.remaining_cents > 0;
            return (
              <tr key={installment.id} data-testid="schedule-row">
                <td>{installment.sequence}</td>
                <td>{formatDate(installment.due_date)}</td>
                <td>{formatMoney(installment.amount_cents)}</td>
                <td>{formatMoney(installment.amount_paid_cents)}</td>
                <td>
                  <StatusChip status={installment.status} />
                </td>
                <td>
                  {payable ? (
                    <PayNowButton onPay={(key) => onPay(installment, key)} />
                  ) : null}
                </td>
              </tr>
            );
          })}
          {installments.length === 0 ? (
            <tr>
              <td colSpan={6} className="muted">
                No installments scheduled.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

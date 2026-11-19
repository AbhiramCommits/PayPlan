import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ScheduleTable from "../components/ScheduleTable";

const installments = [
  {
    id: 1,
    sequence: 1,
    due_date: "2026-01-01",
    amount_cents: 10000,
    amount_paid_cents: 10000,
    remaining_cents: 0,
    status: "PAID",
  },
  {
    id: 2,
    sequence: 2,
    due_date: "2026-01-15",
    amount_cents: 10000,
    amount_paid_cents: 0,
    remaining_cents: 10000,
    status: "SCHEDULED",
  },
];

describe("ScheduleTable", () => {
  it("renders the full installment schedule with money and statuses", () => {
    render(<ScheduleTable installments={installments} onPay={vi.fn()} />);

    expect(screen.getByRole("table", { name: /installment schedule/i })).toBeInTheDocument();
    expect(screen.getAllByTestId("schedule-row")).toHaveLength(2);
    expect(screen.getByText("Jan 1, 2026")).toBeInTheDocument();
    expect(screen.getByText("Jan 15, 2026")).toBeInTheDocument();
    expect(screen.getAllByText("$100.00")).toHaveLength(3);
    expect(screen.getByText("PAID")).toBeInTheDocument();
    expect(screen.getByText("SCHEDULED")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /pay now/i })).toHaveLength(1);
  });

  it("renders an empty state", () => {
    render(<ScheduleTable installments={[]} />);
    expect(screen.getByText(/no installments scheduled/i)).toBeInTheDocument();
  });
});

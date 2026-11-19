import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import PayNowButton from "../components/PayNowButton";

describe("PayNowButton", () => {
  it("issues exactly one request for a double-click and reuses one idempotency key", async () => {
    let resolvePayment;
    const onPay = vi.fn(
      () =>
        new Promise((resolve) => {
          resolvePayment = resolve;
        }),
    );
    const user = userEvent.setup();
    render(<PayNowButton onPay={onPay} />);

    const button = screen.getByRole("button", { name: /pay now/i });
    await user.dblClick(button);

    expect(onPay).toHaveBeenCalledTimes(1);
    expect(onPay.mock.calls[0][0]).toMatch(/[0-9a-f-]{8,}/i);
    expect(button).toBeDisabled();

    resolvePayment({ status: "SUCCEEDED" });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("surfaces a declined payment and allows a retry", async () => {
    const onPay = vi
      .fn()
      .mockRejectedValueOnce({ data: { error: { message: "Card declined" } } })
      .mockResolvedValueOnce({ status: "SUCCEEDED" });
    const user = userEvent.setup();
    render(<PayNowButton onPay={onPay} />);

    const button = screen.getByRole("button", { name: /pay now/i });
    await user.click(button);
    expect(await screen.findByText("Card declined")).toBeInTheDocument();

    await user.click(button);
    await waitFor(() => expect(onPay).toHaveBeenCalledTimes(2));
    // The same mounted button keeps the same idempotency key for safe retries.
    expect(onPay.mock.calls[0][0]).toBe(onPay.mock.calls[1][0]);
  });
});

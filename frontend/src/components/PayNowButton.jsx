import { useRef, useState } from "react";

import { newIdempotencyKey } from "../utils";

/**
 * One idempotency key is generated once per mounted installment button.  The
 * synchronous ref guard means a double-click cannot issue two requests even
 * before React re-renders the disabled state.
 */
export default function PayNowButton({ onPay, disabled = false, label = "Pay now" }) {
  const idempotencyKey = useRef(newIdempotencyKey());
  const inFlight = useRef(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleClick() {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setLoading(true);
    setError("");
    try {
      await onPay(idempotencyKey.current);
    } catch (err) {
      setError(err?.data?.error?.message || err?.message || "Payment failed");
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  return (
    <span className="pay-now">
      <button
        type="button"
        className="button button-primary"
        onClick={handleClick}
        disabled={disabled || loading}
      >
        {loading ? "Paying…" : label}
      </button>
      {error ? <span className="form-error">{error}</span> : null}
    </span>
  );
}

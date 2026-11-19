# PayPlan API

Base URL in local development: `http://localhost:8000/api` (the Vite dev server
proxies `/api` from `http://localhost:5173`).

All member and ops endpoints require a JWT:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

Money is always integer cents (`amount_cents`). Errors use a consistent envelope:

```json
{
  "error": {
    "code": "insufficient_spending_power",
    "message": "Order requires 180000 cents but only 100000 cents are available"
  }
}
```

## Health

### `GET /api/health/` (public)

```bash
curl http://localhost:8000/api/health/
```

```json
{ "status": "ok", "db": true, "redis": true }
```

Returns `503` with `"status":"degraded"` if Postgres or the Redis-backed cache
is unavailable.

## Authentication

### `POST /api/auth/token/`

```bash
curl -X POST http://localhost:8000/api/auth/token/ \
  -H 'content-type: application/json' \
  -d '{"username":"demo","password":"demo12345"}'
```

```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### `POST /api/auth/token/refresh/`

```bash
curl -X POST http://localhost:8000/api/auth/token/refresh/ \
  -H 'content-type: application/json' \
  -d '{"refresh":"<refresh_token>"}'
```

```json
{ "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." }
```

Access tokens live 30 minutes by default. The React app keeps both tokens in
Redux memory (never `localStorage`) and retries a `401` once after refreshing.

## Member

### `GET /api/members/me/`

```bash
curl http://localhost:8000/api/members/me/ -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": 5,
  "external_id": "da587a18-105a-4bad-a5d2-82074e8c5e35",
  "display_name": "Demo Member",
  "email": "demo@payplan.local",
  "status": "ACTIVE",
  "risk_tier": "PRIME",
  "base_limit_cents": 250000,
  "limit_cents": 250000,
  "available_cents": 235825,
  "next_due_date": "2026-11-26",
  "roles": ["member"]
}
```

`roles` includes `support` for users in the `support` group and `staff` for
staff users. `available_cents` is the current limit minus outstanding principal
across active and delinquent plans.

## Checkout

### `POST /api/checkout/`

Creates an order, plan, and schedule atomically, reserving spending power.

```bash
curl -X POST http://localhost:8000/api/checkout/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"product":1,"qty":1,"num_installments":4,"cadence":"BIWEEKLY"}'
```

`201 Created`:

```json
{
  "order": { "id": 17, "status": "APPROVED", "total_cents": 40000 },
  "plan": {
    "id": 12,
    "product_name": "Studio Headphones",
    "principal_cents": 40000,
    "num_installments": 4,
    "cadence": "BIWEEKLY",
    "status": "ACTIVE",
    "start_date": "2026-11-19",
    "paid_count": 0,
    "total_count": 4,
    "next_due_date": "2026-12-03",
    "installments": [
      {
        "id": 45,
        "sequence": 1,
        "due_date": "2026-12-03",
        "amount_cents": 10000,
        "amount_paid_cents": 0,
        "remaining_cents": 10000,
        "status": "SCHEDULED",
        "paid_at": null,
        "days_late": 0
      }
    ],
    "order": { "id": 17, "qty": 1, "total_cents": 40000, "status": "APPROVED" }
  },
  "member": {
    "id": 5,
    "limit_cents": 250000,
    "available_cents": 210000
  }
}
```

`402 Payment Required` when the order total exceeds available spending power:

```json
{
  "error": {
    "code": "insufficient_spending_power",
    "message": "Order requires 180000 cents but only 100000 cents are available",
    "required_cents": 180000,
    "available_cents": 100000
  }
}
```

Other responses: `400` invalid terms (installments must be 4–8, valid cadence,
active product), `401` unauthenticated.

## Plans and installments

### `GET /api/plans/`

Optional filters: `status=ACTIVE|COMPLETED|DELINQUENT|CANCELLED`,
`cadence=BIWEEKLY|MONTHLY`. Paginated by 25.

```bash
curl "http://localhost:8000/api/plans/?status=ACTIVE" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3,
      "product_name": "Studio Headphones",
      "principal_cents": 18900,
      "num_installments": 4,
      "cadence": "BIWEEKLY",
      "status": "ACTIVE",
      "start_date": "2026-10-29",
      "paid_count": 1,
      "total_count": 4,
      "next_due_date": "2026-11-26"
    }
  ]
}
```

### `GET /api/plans/{id}/`

Returns the plan plus its full `installments` array and `order`. Another
member's plan is `404` (never `403`), so ids cannot be enumerated.

### `GET /api/installments/?status=`

Statuses: `SCHEDULED`, `DUE`, `PAID`, `LATE`, `FAILED`, `WAIVED`.
Also supports `plan=<id>`, `ordering=due_date|-due_date`, and `page`.

```bash
curl "http://localhost:8000/api/installments/?status=DUE&ordering=due_date" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 45,
      "sequence": 1,
      "due_date": "2026-12-03",
      "amount_cents": 10000,
      "amount_paid_cents": 0,
      "remaining_cents": 10000,
      "status": "DUE",
      "paid_at": null,
      "days_late": 0
    }
  ]
}
```

## Payments

### `POST /api/payments/`

Requires `Idempotency-Key`. `amount_cents` is optional; omit it to pay the full
remaining balance, or send a smaller value for a partial payment.

```bash
curl -X POST http://localhost:8000/api/payments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: 5d0f9b6a-6f7e-4c47-9f36-2a7f4a0c9b11' \
  -d '{"installment":45}'
```

`201 Created` (first charge):

```json
{
  "payment": {
    "id": 88,
    "installment": 45,
    "amount_cents": 10000,
    "status": "SUCCEEDED",
    "gateway_ref": "fake_9a0d0a6c2d4d4e0fb5a62f3f",
    "attempt_no": 1,
    "failure_code": "",
    "created_at": "2026-11-19T10:00:00+00:00"
  },
  "replayed": false
}
```

Repeating the same key and body returns the original response with `200` and
`"replayed": true`; no second gateway charge is made. Reusing the key with a
different body is `409`:

```json
{
  "error": {
    "code": "idempotency_conflict",
    "message": "Idempotency-Key was already used with a different request body",
    "existing_payment_id": 88
  }
}
```

A decline is `402` (the attempt is still recorded):

```json
{
  "payment": {
    "id": 89,
    "installment": 45,
    "amount_cents": 10000,
    "status": "FAILED",
    "gateway_ref": "fake_fail_1c2d...",
    "attempt_no": 2,
    "failure_code": "card_declined",
    "created_at": "2026-11-19T10:01:00+00:00"
  },
  "replayed": false,
  "error": {
    "code": "payment_failed",
    "message": "The gateway declined this charge.",
    "failure_code": "card_declined"
  }
}
```

Other statuses: `400` missing header / amount outside `1..remaining`,
`404` installment not owned by the caller, `409` installment already settled,
`502` gateway raised unexpectedly (recorded as `gateway_error`).

### `GET /api/payments/?status=`

Repayment history for the signed-in member, newest first.

```bash
curl "http://localhost:8000/api/payments/?status=FAILED&page=1" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 89,
      "installment": 45,
      "plan_id": 12,
      "product_name": "Studio Headphones",
      "amount_cents": 10001,
      "status": "FAILED",
      "gateway_ref": "fake_fail_1c2d...",
      "attempt_no": 2,
      "failure_code": "card_declined",
      "created_at": "2026-11-19T10:01:00+00:00"
    }
  ]
}
```

## Stripe webhook

### `POST /api/webhooks/stripe/` (public, signature-protected)

```bash
curl -X POST http://localhost:8000/api/webhooks/stripe/ \
  -H 'content-type: application/json' \
  -H 'stripe-signature: t=1700000000,v1=...' \
  -d '{
    "id": "evt_1Q2w3E4r",
    "type": "payment_intent.succeeded",
    "data": {"object": {"id": "pi_3Q2w3E4r", "metadata": {"payment_id": "88"}}}
  }'
```

```json
{ "status": "processed", "event_id": "evt_1Q2w3E4r" }
```

Replaying the same event returns `{ "status": "duplicate", ... }` and applies
nothing. If `STRIPE_WEBHOOK_SECRET` is configured, an invalid signature is
`400 invalid_signature`. `payment_intent.succeeded`/`charge.succeeded` settle
the matching payment; `payment_intent.payment_failed`/`charge.failed` mark it
failed without ever downgrading a successful payment.

## Support operations

All `/api/ops/` endpoints require the `support` role (group `support`, or a
staff user). A normal member receives `403 {"error":{"code":"permission_denied"}}`.

### `GET /api/ops/members/?q=`

Search by external id, username, email, or name (max 25 results).

```bash
curl "http://localhost:8000/api/ops/members/?q=demo" \
  -H "Authorization: Bearer $SUPPORT_TOKEN"
```

```json
{
  "results": [
    {
      "id": 5,
      "external_id": "da587a18-105a-4bad-a5d2-82074e8c5e35",
      "display_name": "Demo Member",
      "email": "demo@payplan.local",
      "status": "ACTIVE",
      "risk_tier": "PRIME",
      "base_limit_cents": 250000,
      "limit_cents": 250000,
      "available_cents": 235825
    }
  ]
}
```

### `GET /api/ops/members/{id}/`

Member plus `plans` (same summaries as `/api/plans/`) and the latest 20 limit
rows in `limits`.

### `GET /api/ops/members/{id}/audit/`

```json
{
  "results": [
    {
      "id": 3,
      "actor": 2,
      "actor_username": "support",
      "member": 5,
      "action": "WAIVE_INSTALLMENT",
      "before": { "status": "SCHEDULED", "amount_cents": 10000 },
      "after": { "status": "WAIVED", "reason": "goodwill", "plan_status": "ACTIVE" },
      "created_at": "2026-11-19T12:00:00+00:00"
    }
  ]
}
```

### `POST /api/ops/installments/{id}/waive/`

```bash
curl -X POST http://localhost:8000/api/ops/installments/45/waive/ \
  -H "Authorization: Bearer $SUPPORT_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"reason":"goodwill"}'
```

```json
{
  "installment": {
    "installment_id": 45,
    "plan_id": 12,
    "sequence": 1,
    "due_date": "2026-12-03",
    "amount_cents": 10000,
    "amount_paid_cents": 0,
    "status": "WAIVED",
    "remaining_cents": 0,
    "reason": "goodwill",
    "plan_status": "ACTIVE"
  },
  "audit_id": 3
}
```

### `POST /api/ops/installments/{id}/reschedule/`

```bash
curl -X POST http://localhost:8000/api/ops/installments/45/reschedule/ \
  -H "Authorization: Bearer $SUPPORT_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"due_date":"2026-12-17","reason":"hardship"}'
```

Returns the updated installment and `audit_id`. A `LATE`/`FAILED` installment
moved to today or later becomes `SCHEDULED` again.

### `POST /api/ops/members/{id}/limit/`

Appends a new `SpendingLimit` row with reason `MANUAL`; existing rows are never
edited.

```bash
curl -X POST http://localhost:8000/api/ops/members/5/limit/ \
  -H "Authorization: Bearer $SUPPORT_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"limit_cents":150000,"reason":"verified income"}'
```

```json
{
  "limit": {
    "id": 9,
    "limit_cents": 150000,
    "available_cents": 110000,
    "reason": "MANUAL"
  },
  "audit_id": 4
}
```

Every ops mutation writes an `OpsAuditLog` row with actor, member, action,
`before`, `after`, and timestamp.

## Django admin

The admin is mounted at `/admin/` and registers every model: member and
append-only limit inline, products, orders, plans with inline installments,
installments, rollups, payments, webhook events, notifications, and a read-only
audit log.

# Contributing to PayPlan

## Local development loop

```bash
cp .env.example .env
docker compose up -d db redis

python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

make migrate
make seed
make test
```

For the full container stack (API + worker + beat + web):

```bash
docker compose up -d --build
# dashboard http://localhost:5173, API http://localhost:8000/api/health/
```

Demo member: `demo / demo12345`. Support console user: `support / support12345`.

Frontend:

```bash
cd frontend
npm ci
npm run dev
npm test
npm run lint
```

## Before opening a PR

1. **Backend lint + format:** `make lint` (ruff + black).
2. **Backend tests:** `make test`. For coverage:
   `.venv/bin/python -m pytest -q --cov=apps --cov-report=term-missing`.
   The configured floor is 91%; if you add meaningful code, add tests rather
   than lowering the threshold.
3. **Frontend checks:** `cd frontend && npm run lint && npm test && npm run build`.
4. **Migrations:** run `make makemigrations` and commit generated files. Never
   edit an applied migration.
5. If your change affects the simulation or coverage headline, re-run
   `make simulate` or the coverage command and update `results/` and the README
   numbers from the actual output.

## Engineering rules

- **Money is cents.** Use integer fields and arithmetic. Never introduce a
  float into a money path. Percentages may use `Decimal` with explicit rounding.
- **No outbound network in tests.** Stripe sits behind `PaymentGateway`; tests
  use `FakeGateway` or monkeypatched Stripe methods. No test may call a real
  gateway or external HTTP service.
- **Idempotency is sacred.** Any new charge path needs a deterministic key and
  must survive being called twice with the same key.
- **Limit history is append-only.** Write a new `SpendingLimit` row; never
  mutate `limit_cents` in place. `available_cents` is a maintained snapshot.
- **Every ops action writes an audit row.** Actor, member, action, before, and
  after are mandatory.
- **Tasks must be rerunnable.** Anything scheduled by beat should be safe to run
  twice on the same day (dedupe keys, derived idempotency keys, rollup
  `update_or_create`).
- **Keep member data scoped.** Every member-facing queryset filters by
  `request.user.member`; cross-member access returns 404.

## Testing conventions

- pytest + pytest-django, factories in `backend/tests/factories.py`.
- Use `freezegun` to move across due dates and dunning windows.
- Use `FakeGateway(failures=[...])` for scripted declines; use `fail_all=` for
  exhaustion scenarios.
- The 10-thread concurrency proof runs only on PostgreSQL (it needs real
  row-level locking). CI supplies a `postgres:16` service.
- Prefer domain tests of the pure services first, then API tests for status
  codes and permissions.

## Commit style

Use a scoped prefix such as `feat:`, `fix:`, `test:`, `docs:`, or `chore:`.
Keep behavior changes and migrations in the same commit. Do not push secrets or
real Stripe keys; only `sk_test_` keys are accepted by the adapter.

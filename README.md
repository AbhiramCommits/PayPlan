# PayPlan

PayPlan is an interest-free installment checkout and repayment service. A member
gets a spending-power limit, splits an order into 4–8 scheduled payments, and
repays on a biweekly or monthly cadence. On-time repayment raises the limit;
serious delinquency lowers it. Nothing in the product charges interest — the
business earns from merchant fees, so the engineering is about trustworthy
scheduling, exact money, and reliable collections.

The repo contains a Django + DRF API, Celery workers on Redis, a React + Redux
Toolkit member dashboard, a role-gated support console with an append-only audit
trail, and a reproducible portfolio simulation.

---

## 1. What PayPlan does

1. **Checkout.** A member picks a product and a plan length (4, 6, or 8
   payments). PayPlan splits the total across the schedule and immediately
   reserves that principal against their available spending power.
2. **Repayment.** On each due date a Celery job charges the installment through
   a gateway abstraction, records the attempt, and releases spending power as
   principal is paid. Members can also pay early or partly from the dashboard.
3. **Recovery.** A declined charge is retried on a 1-day / 3-day / 7-day backoff.
   After the third failed retry the installment becomes `LATE`, the plan becomes
   `DELINQUENT`, and the limit is recalculated.
4. **Limit growth.** Every four consecutive on-time installments raises the
   limit by 10% of the member's base limit, capped at 2.5× base. Any installment
   that is (or was) 15+ days late cuts the computed limit by 25%, never below
   0.5× base.

Why those rules:

- **Base limit** is the underwriting anchor. It is set once per member (risk
  tier + income in a real system) and everything else is a deterministic
  function of repayment behaviour.
- **+10% per four on-time payments, capped at 2.5×** rewards reliability without
  letting a young account grow faster than its observed history can support.
  Four periods is roughly two months of biweekly behaviour — long enough to be
  signal, short enough to feel earned.
- **−25% on a 15+ day delinquency** is a material step down that reflects real
  default risk, while the **0.5× floor** avoids a death spiral that makes it
  impossible to recover.
- **Append-only limit history** matters for disputes and audits: every change has
  a reason (`INITIAL`, `ON_TIME_INCREASE`, `DELINQUENCY_DECREASE`, `MANUAL`) and
  an effective timestamp. Rows are never edited.
- **4–8 installments** keeps the schedule legible and the exposure per order
  small; biweekly aligns with payroll for many members.

---

## 2. Architecture

```
                        ┌────────────────────────────────────────────┐
                        │  React 18 + Redux Toolkit + RTK Query       │
                        │  login · dashboard · plan · history · ops   │
                        │  JWT access/refresh held in memory          │
                        └───────────────┬────────────────────────────┘
                                        │ HTTPS /api (Bearer JWT)
                    ┌───────────────────▼───────────────────┐
                    │ Nginx (compose) or ALB (AWS)           │
                    └───────────────────┬───────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │ Django 5 + DRF + SimpleJWT             │
                    │ checkout · plans · payments · ops      │
                    └───────┬───────────────────────┬───────┘
                            │                       │
                  ┌─────────▼─────────┐   ┌─────────▼────────────────┐
                  │ PostgreSQL 16     │   │ Redis 7                  │
                  │ money, schedules  │   │ Celery broker/results,   │
                  │ audit, rollups    │   │ cache + health checks    │
                  └───────────────────┘   └─────────┬────────────────┘
                                                    │
                              ┌─────────────────────▼─────────────────────┐
                              │ Celery worker + Celery beat                │
                              │ due reminders · scheduled charges ·        │
                              │ dunning retries · nightly rollups          │
                              └─────────────────────┬─────────────────────┘
                                                    │ PaymentGateway
                              ┌─────────────────────▼─────────────────────┐
                              │ FakeGateway (dev/tests, zero network)      │
                              │ StripeGateway (test mode) ── webhooks ────▶│
                              │                            /api/webhooks/stripe/
                              └────────────────────────────────────────────┘
```

| App | Responsibilities |
| --- | --- |
| `accounts` | `Member`, append-only `SpendingLimit` history, `/members/me/`, JWT token routes |
| `catalog` | `Product` catalog and integer-cent prices |
| `plans` | `Order`, `InstallmentPlan`, `Installment`, `PlanRollup`; schedule generation, checkout, limit engine, rollups |
| `payments` | `Payment`, `WebhookEvent`, `Notification`; gateway boundary, idempotent payment service, webhooks, Celery tasks |
| `ops` | Support permission, waive/reschedule/limit actions, append-only `OpsAuditLog` |

### Money is integer cents

`amount_cents`, `principal_cents`, `price_cents`, `available_cents`, and
`limit_cents` are `BigIntegerField`s. There is no `FloatField` anywhere in the
money path. `generate_schedule` uses integer division and distributes the
remainder one cent at a time across the earliest installments, so the schedule
sums to the principal for every input. The property test checks every principal
from 1 to 5,000 cents and every term from 2 to 12. `Decimal` is used only for
percentage policy math (rounded half-up to an integer cent) and for display
rates. The frontend formats cents for display and never sends floats.

### Idempotency

`POST /api/payments/` requires an `Idempotency-Key` header. The server computes
a SHA-256 fingerprint over `(member, installment, amount_cents)` and stores it
on the `Payment` row alongside a **unique** `idempotency_key`. The first lookup
replays a committed row only when the fingerprint matches; a different body on
the same key is `409`. Inside a transaction the service locks the installment
with `select_for_update()`, then performs a **second** key lookup. Concurrent
duplicates therefore serialise behind the installment row, and the unique
constraint is the final backstop. The test suite fires 10 parallel HTTP
requests with the same key and asserts exactly one `Payment` row and one
gateway charge (see RESULTS). Failed attempts are still recorded, so a retry is
a new key (`inst:{id}:attempt:{n}`) and is never confused with the original.

### Dunning backoff

A failed attempt is one `Payment` row with `attempt_no = n`. `retry_failed_payment`
backs off 1 day after attempt 1, 3 days after attempt 2, and 7 days after attempt
3. `run_dunning` runs daily from beat, finds the newest failed attempt per
installment, and is safe to run repeatedly: if the backoff has not elapsed it
defers, and the derived key `inst:{id}:attempt:{n}` makes a repeat charge a
no-op. After attempt 4 fails, the installment becomes `LATE`, the plan becomes
`DELINQUENT`, the limit is recalculated, and no further retries are scheduled.

---

## 3. How to run

Prerequisites: Docker Desktop, Python 3.11, Node 20 (Node 26 also works).

```bash
git clone <your-fork> PayPlan
cd PayPlan
cp .env.example .env
```

### Full stack with Docker

```bash
docker compose up -d --build
# API      http://localhost:8000/api/health/
# Dashboard http://localhost:5173
# Admin    http://localhost:8000/admin/
```

The API container waits for Postgres and Redis, runs migrations, and (with
`SEED_DEMO=1` in `.env`) seeds demo data. Postgres and Redis are published on
host ports **15432** and **16379** so they do not collide with other local
databases. Change those mappings in `docker-compose.yml` if you prefer.

Demo logins:

| Role | Username | Password |
| --- | --- | --- |
| Member | `demo` | `demo12345` |
| Support | `support` | `support12345` |

### Local Python loop (tests, migrations, simulation)

The `.env.example` host URLs point at `localhost:15432` / `localhost:16379`,
which match the compose port mappings.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
docker compose up -d db redis

make migrate
make seed
make test        # backend pytest suite
make cov         # pytest + coverage (results/coverage.txt is a saved run)
make lint        # ruff + black --check
```

`make test` uses `payplan.settings.test`, the fake gateway, an in-memory cache,
and eager Celery — no external network calls. Set `DATABASE_URL` if you want
the suite to run against a different Postgres; without it (and without a `.env`)
the test settings fall back to SQLite, although the 10-thread concurrency proof
is skipped there.

If you prefer to keep everything in containers:

```bash
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed_demo
docker compose exec api python manage.py simulate_portfolio --members 500 --days 120 --seed 42
```

### Frontend dev server

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to localhost:8000
npm test           # Vitest + React Testing Library
npm run lint
npm run build
```

### Simulation

```bash
make simulate
# or
.venv/bin/python backend/manage.py simulate_portfolio --members 500 --days 120 --seed 42
```

The command seeds 500 members and products, places orders across 120 days, and
runs the real reminder/charge/dunning/rollup functions in-process with a seeded
gateway. It writes `results/simulation.txt` and `results/rollups.csv`, then rolls
the database transaction back so your dev data is untouched.

### Flipping to Stripe test mode

The entire suite and local development use `FakeGateway`, so no key is needed.
To exercise the Stripe adapter:

```dotenv
PAYMENT_GATEWAY=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

```bash
docker compose up -d --build api worker beat
stripe login
stripe listen --forward-to localhost:8000/api/webhooks/stripe/
# copy the printed whsec_... into .env and restart api
```

`StripeGateway` refuses anything that is not an `sk_test_` key. The webhook
endpoint verifies `Stripe-Signature` whenever `STRIPE_WEBHOOK_SECRET` is set and
dedupes on the Stripe event id.

---

## 4. Deploying to AWS

### Images

Both Dockerfiles are production-capable:

```bash
docker build -t payplan-api ./backend
docker build -t payplan-web ./frontend
```

`docker-compose.prod.yml` runs `api`, `worker`, `beat`, and `web` with
`payplan.settings.prod`, migrations + `collectstatic` on the API container, and
no bundled database. Postgres and Redis are expected to be RDS and
ElastiCache.

### ECR push

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr create-repository --repository-name payplan-api --region "$AWS_REGION"
aws ecr create-repository --repository-name payplan-web --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR"

docker build -t payplan-api ./backend
docker tag payplan-api:latest "$ECR/payplan-api:latest"
docker push "$ECR/payplan-api:latest"

docker build -t payplan-web ./frontend
docker tag payplan-web:latest "$ECR/payplan-web:latest"
docker push "$ECR/payplan-web:latest"
```

### RDS Postgres 16 and ElastiCache Redis 7

```bash
export SG=sg-xxxxxxxxxxxxxxxxx   # security group allowing 5432/6379 from ECS

aws rds create-db-instance \
  --db-instance-identifier payplan-prod \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 16.4 \
  --allocated-storage 20 \
  --master-username payplan \
  --master-user-password "$DB_PASSWORD" \
  --vpc-security-group-ids "$SG" \
  --no-publicly-accessible \
  --backup-retention-period 7

aws elasticache create-cache-cluster \
  --cache-cluster-id payplan-redis \
  --engine redis \
  --cache-node-type cache.t4g.micro \
  --num-cache-nodes 1 \
  --security-group-ids "$SG"
```

Use the RDS endpoint and ElastiCache primary endpoint for `DATABASE_URL` and
`REDIS_URL`.

### Secrets in SSM Parameter Store

```bash
aws ssm put-parameter --name /payplan/prod/DJANGO_SECRET_KEY \
  --type SecureString --value "$(openssl rand -hex 32)"
aws ssm put-parameter --name /payplan/prod/DATABASE_URL \
  --type SecureString --value "postgres://payplan:$DB_PASSWORD@payplan-prod.xxxx.$AWS_REGION.rds.amazonaws.com:5432/payplan"
aws ssm put-parameter --name /payplan/prod/REDIS_URL \
  --type SecureString --value "redis://payplan-redis.xxxx.0001.$AWS_REGION.cache.amazonaws.com:6379/0"
aws ssm put-parameter --name /payplan/prod/STRIPE_SECRET_KEY \
  --type SecureString --value "sk_test_..."
aws ssm put-parameter --name /payplan/prod/STRIPE_WEBHOOK_SECRET \
  --type SecureString --value "whsec_..."
```

Reference them in the ECS task definition as `secrets` with
`valueFrom: arn:aws:ssm:$AWS_REGION:$AWS_ACCOUNT_ID:parameter/payplan/prod/...`
and grant the task execution role `ssm:GetParameters` + KMS decrypt. Set
`PAYMENT_GATEWAY=stripe`, `DJANGO_SETTINGS_MODULE=payplan.settings.prod`, and
sensible `ALLOWED_HOSTS`.

### ECS Fargate services

Create one cluster and three backend services from the same image:

```bash
aws ecs create-cluster --cluster-name payplan

# register task definitions payplan-api / payplan-worker / payplan-beat with the
# ECR image, command from docker-compose.prod.yml, and the SSM secrets above
aws ecs register-task-definition --cli-input-json file://ecs/api-task.json
aws ecs register-task-definition --cli-input-json file://ecs/worker-task.json
aws ecs register-task-definition --cli-input-json file://ecs/beat-task.json

# one-off migration task (preferred over every API task racing on migrate)
aws ecs run-task --cluster payplan --launch-type FARGATE \
  --task-definition payplan-api --network-configuration "$NETWORK_CONFIG" \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","manage.py","migrate","--noinput"]}]}'
```

API service with a load balancer and two tasks; worker and beat with one task
each and no load balancer:

```bash
aws ecs create-service --cluster payplan --service-name payplan-api \
  --task-definition payplan-api --desired-count 2 --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG" \
  --load-balancers "targetGroupArn=$API_TG,containerName=api,containerPort=8000"

aws ecs create-service --cluster payplan --service-name payplan-worker \
  --task-definition payplan-worker --desired-count 1 --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG"

aws ecs create-service --cluster payplan --service-name payplan-beat \
  --task-definition payplan-beat --desired-count 1 --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG"
```

### ALB health check and routing

```bash
aws elbv2 create-target-group --name payplan-api \
  --protocol HTTP --port 8000 --vpc-id "$VPC_ID" --target-type ip \
  --health-check-path /api/health/ \
  --health-check-interval-seconds 15 --healthy-threshold-count 2

aws elbv2 create-target-group --name payplan-web \
  --protocol HTTP --port 80 --vpc-id "$VPC_ID" --target-type ip \
  --health-check-path /

aws elbv2 create-load-balancer --name payplan \
  --subnets "$PUBLIC_SUBNET_A" "$PUBLIC_SUBNET_B" \
  --security-groups "$ALB_SG"

# listener 443 (ACM cert) with rules:
#   /api/*     -> payplan-api target group
#   /admin/*   -> payplan-api target group
#   /static/*  -> payplan-api target group
#   default    -> payplan-web target group
```

The API health endpoint returns `{"status":"ok","db":true,"redis":true}` and is
exempt from `SECURE_SSL_REDIRECT`, so plain ALB health checks stay green while
user traffic is forced to HTTPS.

For the web service, build the frontend image from `frontend/Dockerfile` and run
it as a fourth Fargate service behind the `payplan-web` target group. In
compose, nginx proxies `/api` to the `api` service; on ECS the ALB path rules
above send `/api/*` straight to the API target group, so no service discovery is
required.

---

## 5. RESULTS

Everything below was produced by the commands shown, in this repository.

### Test suite and coverage

```bash
cd PayPlan
.venv/bin/python -m pytest -q --cov=apps --cov-report=term-missing --cov-report=xml --color=no
```

From `results/coverage.txt`:

| Metric | Value |
| --- | --- |
| Backend tests | **87 passed** |
| Backend failures / skips | 0 / 0 |
| Coverage (statement + branch) | **91.59%** (threshold `fail_under = 91.0`) |
| Suite runtime | **8.50 s** |
| Frontend Vitest tests | **6 passed** in 3 files |

Frontend command:

```bash
cd frontend && npm test
```

### Portfolio simulation — 500 members / 120 days / seed 42

```bash
make simulate
```

From `results/simulation.txt` (window 2026-07-23 → 2026-11-19):

| Metric | Value |
| --- | --- |
| Plans created | **669** |
| Installments billed | **2,231** |
| Total billed | **$262,096.43** |
| Total collected | **$257,769.04** |
| On-time payment rate | **91.16%** |
| Delinquency rate | **1.64%** |
| Dunning recovery rate | **60.44%** |
| Average spending-limit change | **+$90.83 (+1.63%)** |
| Simulation wall-clock runtime | **58.93 s** |
| Gateway attempts | **2,534** |

Per-day rollups are in `results/rollups.csv` (120 data rows plus header).

### Idempotency proof — 10 concurrent duplicates → 1 charge

```bash
.venv/bin/python -m pytest backend/apps/payments/tests/test_concurrency.py -q -s --create-db
```

From `results/idempotency.txt`:

```
PROOF: 10 concurrent duplicate requests -> 1 Payment row, 1 gateway charge
1 passed, 2 warnings in 6.73s
```

The ten requests are real HTTP requests through DRF with the same
`Idempotency-Key`; the assertions also require exactly one `SUCCEEDED` row and
that the installment was charged once.

---

## 6. Trade-offs and what I'd build next

- **Credit bureau reporting.** Limits and delinquency should eventually flow to
  a bureau (Metro 2) with an outbox and reconciliation. Today the member and
  limit history are local-only.
- **ACH and richer partial payments.** The payment API supports partial
  amounts, but production should add ACH (lower cost, slower settlement),
  payment-method vaulting, and refund/dispute flows. Card-only is a demo choice.
- **A real risk model for the initial limit.** `base_limit_cents` is seeded or
  manually set. The next step is an underwriting service using income,
  obligations, and bureau data, with the policy engine reading its output rather
  than hard-coding risk tiers.
- **Gateway calls outside the row lock.** The idempotency design currently holds
  the installment lock during the gateway call to guarantee one charge. At
  higher volume I would use a payment-attempt state machine plus an outbox, so
  network latency does not hold database locks.
- **Notification delivery.** `Notification` rows are the durable contract;
  plugging in SES/Twilio with retries is a worker concern.
- **Operational tooling.** The ops console covers waive/reschedule/limit with an
  audit trail. Next: dispute cases, bulk actions, and a read-only audit export.

---

## Repository layout

```
backend/            Django project (settings/{base,dev,test,prod}.py), apps, tests
frontend/           Vite + React 18 + Redux Toolkit + RTK Query
results/            measured coverage, simulation, rollups, idempotency proof
docs/api.md         every endpoint with sample request/response
docker-compose.yml  local db, redis, api, worker, beat, web
docker-compose.prod.yml  production-shaped services (external RDS/ElastiCache)
.github/workflows/ci.yml backend + frontend + docker jobs
```

## License

MIT © 2026 PayPlan contributors. See [LICENSE](LICENSE).

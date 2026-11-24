# KankkuPro ERP

KankkuPro is a multi-tenant business workspace built as a Django modular monolith. It provides email identity flows, business onboarding and teams, customer/catalog management, India V1 invoice drafts and issuance, PDF downloads, linked correction notes, payment recording/reversals, and financial dashboard totals.

## Requirements

- Python 3.12+
- PostgreSQL 15+ (Neon PostgreSQL is the hosted target)
- Node.js 22+ and npm
- Pango native libraries for WeasyPrint PDFs (`brew install pango` on macOS)

The application deliberately uses PostgreSQL for development and tests. It does not configure SQLite as a fallback.

## Local setup on macOS

1. Create and activate a virtual environment, then install the Python dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.lock
   ```

2. Copy `.env.example` to `.env` and set `SECRET_KEY` and `DATABASE_URL`. For local PostgreSQL, create a database named `kanakkupro` and use a URL such as:

   ```text
   postgresql://postgres:postgres@localhost:5432/kanakkupro
   ```

   For Neon, use the connection string from the Neon console and retain `sslmode=require`. A pooled Neon hostname includes `-pooler`; pooled application settings disable server-side cursors.

3. Export the variables from `.env` into the current shell (or load them with your preferred environment manager). Then apply migrations and build frontend assets:

   ```bash
   set -a
   source .env
   set +a
   python manage.py migrate
   npm ci
   npm run build
   ```

4. Start the development server:

   ```bash
   python manage.py runserver
   ```

Visit <http://127.0.0.1:8000/>. Authentication pages are provided by django-allauth at `/accounts/`; the protected foundation dashboard is at `/dashboard/`.

Local verification and password-reset messages are printed by Django's console email backend. Account signup requires a confirmed email before login; confirmation links expire after three days. Password-reset links expire after one hour. Allauth rate limits cover login, failed login, signup, email confirmation, and password-reset requests.

### Frontend development

Use `npm run watch:css` in a second terminal while editing templates and styles. HTMX is installed from npm and copied into `static/vendor` by `npm run build`.

The shared shell provides keyboard skip navigation, responsive workspace navigation, accessible form error links, live status messages, and a loading indicator for HTMX requests. HTMX writes must use Django CSRF protection and server-side validation. Partial responses should update only the requested component, preserve useful empty/error states, and expose updated content through `aria-live` regions. Use `hx-push-url` only when browser navigation should represent the new state; protect write requests against duplicates on the server.

### Health probes and logs

- `GET /health/live/` confirms the Django process can answer requests without contacting PostgreSQL.
- `GET /health/ready/` runs `SELECT 1` against PostgreSQL and returns only a generic 503 status on failure.
- Application logs are JSON on stdout and include timestamp, severity, environment, request ID, and safe tenant ID context. Framework log text is suppressed to avoid leaking URLs or request data.

These probes do not verify migration state, email delivery, backups, or restore readiness. Configure host-level monitoring, alert routing, database backup retention, and isolated restore drills before production.

See [Production Operations Readiness](docs/operations.md) for the pre-pilot decisions, deployment checklist, backup/restore drill, and incident runbooks.

## Checks and tests

```bash
ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

Tests use the PostgreSQL URL in `DATABASE_URL`. GitHub Actions starts PostgreSQL and runs these checks alongside the asset build.

CI also runs production deployment checks and Python/npm vulnerability audits. The production check uses synthetic configuration; live provider delivery, HTTPS, monitoring, and recovery still require deployment verification.

### Catalog pricing and GST classification

Catalog forms require a nonnegative unit price (up to four decimal places), a numeric HSN/SAC code, and a selected tax treatment. Taxable items require a positive rate; exempt items store a zero rate. Rates and codes must be selected by the business; the application checks their format and consistency, not their legal applicability. Prices use the workspace currency, which defaults to INR for new workspaces.

Apply all migrations with `python manage.py migrate` before using this update. The additive catalog migration leaves existing items with empty pricing/classification fields; it does not assign prices, codes, or rates. Edit those items to complete their setup. Catalog CSV exports include price, currency, HSN/SAC, tax treatment, and tax rate, preserving four-decimal precision.

### Invoices and payments

Open `/invoices/` and complete **Invoice settings** as an Owner/Admin. Complete the customer's Indian billing address/country and catalog tax details, then create and issue a draft. Issued details are immutable; linked credit/debit notes preserve corrections. Partial/final payments and append-only reversals reconcile with dashboard balances. PDF downloads use stored snapshots and totals. See [Financial workflow](docs/financial-workflow.md) for the supported India V1 scope, calculation order, roles, numbering, migrations, deployment steps, and limitations.

## Settings and deployment

For Render staging, use the repository-root `render.yaml` Blueprint and follow [Render staging](docs/render-staging.md). The Docker image includes Gunicorn, compiled assets, and native PDF dependencies. Releases serialize migrations against a direct Neon endpoint and verify the shared authentication cache. Runtime-only dependencies are pinned in `requirements.runtime.lock`; regenerate it from `requirements.txt` constrained by `requirements.lock` when updating dependencies.

Use `.env.production.example` as a configuration reference in the deployment's secret manager. Production requires an explicit TLS PostgreSQL URL, a strong generated `SECRET_KEY`, real email configuration, and separate `MFA_ENCRYPTION_KEYS`. Forwarded HTTPS headers are trusted only when `TRUST_X_FORWARDED_PROTO=True` is explicitly enabled after reviewing the proxy.

Platform staff must verify their email, enroll TOTP under `/accounts/2fa/`, retain recovery codes securely, and complete MFA before using `/admin/`. Admin access requires MFA within the last 15 minutes, including sessions created outside allauth. MFA secrets are encrypted at rest; back up the encryption keys separately from PostgreSQL. Apply migrations and create the shared cache table before enabling logins. See [Production security](docs/production-security.md) for rollout, key rotation, verification, and remaining release gates.

- `config.settings.dev` is used by `manage.py` for local work.
- `config.settings.test` uses PostgreSQL and an in-memory email backend.
- `config.settings.production` requires `SECRET_KEY` and `ALLOWED_HOSTS`, enforces HTTPS and secure cookies, and enables Neon TLS.

Set `DJANGO_SETTINGS_MODULE=config.settings.production` in the deployment environment. Production settings require a non-console `EMAIL_BACKEND` and use Django's shared database cache for allauth throttling. After applying migrations, create the cache table with `python manage.py createcachetable` (or set `DATABASE_CACHE_TABLE` to a different table name). Configure real SMTP/provider credentials, trusted hosts, HTTPS termination, static asset builds, backups, and a production Neon plan before onboarding users. HSTS is off until `SECURE_HSTS_SECONDS` is explicitly set after validating HTTPS deployment. Configure allauth's trusted client IP header only after selecting a proxy and confirming which header it controls.

## Implemented phases

Phases 1–4 provide the foundation, email authentication, shared UI, and tenant onboarding/memberships/invitations. Phase 5 provides tenant-scoped customers and catalog, invoice drafts and transactional issuance, immutable snapshots and PDFs, linked credit/debit notes, payment posting/reversals, customer invoice history, and financial dashboard/report totals under the supported India V1 scope.

Phase 6 groundwork includes append-only audit events, operational reports, bounded CSV exports, health probes, structured logs, and secure production settings. Provider-specific monitoring, recovery verification, performance/security review, and pilot readiness remain outstanding. Subscription billing and inventory remain later phases.

The active tenant is resolved from current membership on every request. Financial writes revalidate permissions, protect duplicate requests, and commit audit events atomically. See [ADR-001](docs/decisions/ADR-001-india-launch.md), [Financial workflow](docs/financial-workflow.md), and [Operations](docs/operations.md) for scope and deployment requirements.

# KankkuPro ERP

KankkuPro is a multi-tenant business workspace built as a Django modular monolith. The repository contains the project foundation, email identity flows, tenant onboarding and team invitations, a shared responsive UI shell, tenant-scoped customer management, and basic product/service catalog records. Financial workflows are not enabled yet.

## Requirements

- Python 3.12+
- PostgreSQL 15+ (Neon PostgreSQL is the hosted target)
- Node.js 22+ and npm

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

### Catalog pricing and GST classification

Catalog forms require a nonnegative unit price (up to four decimal places), a numeric HSN/SAC code, and a selected tax treatment. Taxable items require a positive rate; exempt items store a zero rate. Rates and codes must be selected by the business; the application checks their format and consistency, not their legal applicability. Prices use the workspace currency, which defaults to INR for new workspaces.

Apply `catalog.0002_item_pricing_and_tax_classification` with `python manage.py migrate` before using this update. This additive migration leaves existing items with empty pricing/classification fields; it does not assign prices, codes, or rates. Edit those items to complete their setup. Catalog CSV exports include price, currency, HSN/SAC, tax treatment, and tax rate, preserving four-decimal precision. Invoice issuance, payments, and PDFs remain the next implementation slice.

## Settings and deployment

- `config.settings.dev` is used by `manage.py` for local work.
- `config.settings.test` uses PostgreSQL and an in-memory email backend.
- `config.settings.production` requires `SECRET_KEY` and `ALLOWED_HOSTS`, enforces HTTPS and secure cookies, and enables Neon TLS.

Set `DJANGO_SETTINGS_MODULE=config.settings.production` in the deployment environment. Production settings require a non-console `EMAIL_BACKEND` and use Django's shared database cache for allauth throttling. After applying migrations, create the cache table with `python manage.py createcachetable` (or set `DATABASE_CACHE_TABLE` to a different table name). Configure real SMTP/provider credentials, trusted hosts, HTTPS termination, static asset builds, backups, and a production Neon plan before onboarding users. HSTS is off until `SECURE_HSTS_SECONDS` is explicitly set after validating HTTPS deployment. Configure allauth's trusted client IP header only after selecting a proxy and confirming which header it controls.

## Implemented phases

Phases 1–4 are implemented across `accounts`, `tenants`, and `dashboard`; Phase 5 customer management is implemented in `customers`, with foundational product/service records in `catalog`. Customer records support tenant-scoped search, pagination, billing contact details, role-checked editing, and reversible archive/restore. Catalog records support tenant-scoped search, case-insensitive tenant-unique SKUs, prices to four decimal places, per-item HSN/SAC and GST treatment/rate, plus archive/restore. Legacy catalog rows without financial classification remain non-invoice-ready. Phase 6 groundwork includes append-only audit events and tenant-scoped operational reports for customer/catalog/team counts and recent activity. CSV exports are tenant-scoped, role-restricted, protected from spreadsheet formula injection, and bounded at 10,000 rows. PostgreSQL rejects audit event updates and deletes. The UI uses Django templates, HTMX, Tailwind CSS v4, and DaisyUI 5, with a responsive workspace shell and accessible form feedback. New tenant workspaces default to India (`IN`), INR, and `Asia/Kolkata`; existing workspaces are unchanged. The approved India launch, retention, and recovery decisions are recorded in [ADR-001](docs/decisions/ADR-001-india-launch.md). A pure per-line GST calculator is implemented in `apps/sales`; invoice persistence/PDFs, payments, and financial reporting remain to be implemented. The active tenant is stored in the session but resolved from a current active membership on each request. Tenant creation and owner membership commit atomically. Owner and Admin roles can invite members; invitation links are hashed at rest, bound to the invited verified email, expire after seven days by default, and require a CSRF-protected POST to accept. Customer-specific place-of-supply data and invoice workflows remain future work. Subscription billing, inventory, and production monitoring remain later phases.

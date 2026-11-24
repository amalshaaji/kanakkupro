# Render staging deployment

The repository includes a Render Blueprint (`render.yaml`), a native Python build script, Gunicorn configuration, a serialized release entrypoint, and read-only restore-verification tooling. Neon remains the database; the Blueprint does not create or substitute a Render database.

## Simple setup

1. Create a Neon staging database and copy its **direct** connection URL with TLS enabled.
2. [Deploy to Render](https://render.com/deploy?repo=https://github.com/amalshaaji/kanakkupro), connect the repository, and fill in the database, security-key, and email fields.
3. Deploy. Render assigns the HTTPS address; startup runs the database migrations automatically.

One direct database URL is enough. The separate migration URL is optional and only needed if you later use a pooled application connection. Keep credentials in Render's environment-variable form.

## Existing Python service

Keep the existing service. In **Settings → Build & Deploy**, set:

- Runtime: **Python 3**
- Build command: `bash scripts/render_build.sh`
- Start command: `python scripts/render_start.py`
- Health check path: `/health/ready/`

Set `PYTHON_VERSION=3.12.12`, `NODE_VERSION=22`, `DJANGO_SETTINGS_MODULE=config.settings.render`, `APP_ENV=staging`, `TRUST_X_FORWARDED_PROTO=True`, and `SECURE_HSTS_SECONDS=3600` in Environment, alongside the secrets below. Deploy the latest `main` commit. The start script runs migrations and then starts `config.wsgi:application`; do not use the placeholder `your_application.wsgi`.

## Setup details

1. Create a separate Neon staging database/branch. Choose its region near the Render region and keep production credentials out of staging. Record the chosen plan and backup capability separately.
2. In Render, create a **Blueprint** from `amalshaaji/kanakkupro`, branch `main`, using the repository-root `render.yaml`. Review the service before creation. The Blueprint requests a free staging web service with automatic deploys disabled. It does not provision paid services.
3. Enter the required secrets in Render's environment-variable form:
   - `DATABASE_URL`: the staging Neon **direct** URL, with `sslmode=require` or stronger verification.
   - Optional `MIGRATION_DATABASE_URL`: add this only when using a pooled `DATABASE_URL`. It must be the same database's direct, non-pooler URL, with TLS.
   - `SECRET_KEY`: a securely generated Django secret of at least 50 characters.
   - `MFA_ENCRYPTION_KEYS`: a separately generated Fernet key. Preserve protected recovery copies outside database backups.
   - `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL`: a verified email provider. The free staging template uses STARTTLS on port 2525. Use this only with a provider that supports that port, or change the deployment to an appropriate API email backend/paid plan after a separate decision.
4. Render assigns the `onrender.com` hostname. `config.settings.render` derives allowed hosts and the HTTPS CSRF origin from `RENDER_EXTERNAL_HOSTNAME` unless explicitly configured. Set explicit host/origin lists if adding a custom domain.
5. Deploy manually. Render's managed HTTPS proxy is the transport boundary; the Blueprint opts into its forwarded-protocol header and enables one-hour HSTS for the assigned HTTPS staging hostname. HSTS preload stays disabled.

Render free services spin down when idle and restrict SMTP ports 25/465/587. They are staging previews, not the production availability or recovery baseline. The Blueprint uses Render's default region (Oregon); set a different region in `render.yaml` before creation if needed, and choose a nearby Neon region. The Blueprint does not choose a paid database or provider plan.

## Release behavior

The native build uses Render’s Node/npm tools to build CSS/HTMX, installs only the pinned runtime dependencies, and collects static files without deployment secrets. A real PDF-rendering smoke check verifies the native Pango/Harfbuzz libraries before release. Missing native libraries fail the build rather than leaving broken invoice exports. Runtime configuration uses the production security validator.

Before Gunicorn starts, `scripts/render_start.py` opens a dedicated TLS connection to the direct migration endpoint, acquires a PostgreSQL session advisory lock, and runs deployment checks, forward migrations, cache-table creation, and migration-state verification. It releases the lock even on failure. Failed checks stop startup. Application requests continue to use the original application database URL. The source and migration URLs must refer to the same Neon database; confirm this in the dashboard before deployment.

This entrypoint is for the single-instance free staging service. Before production, use a separately scheduled release/pre-deploy task and review each migration for compatibility with the currently running application. Do not use startup restarts as a substitute for migration review or backups.

The service binds to Render's `PORT`, uses one synchronous worker by default to bound PDF memory use, and serves compiled assets through WhiteNoise. Access logging is handled by the application's safe route logger; raw query strings and invitation tokens are not added to Gunicorn access logs. Tune concurrency only after load testing and selecting a production plan.

## Verify the deployment

- Both `/health/live/` and `/health/ready/` must return 200 over HTTPS. Readiness includes the shared authentication cache table.
- Confirm static CSS/HTMX load, HTTP redirects to HTTPS, allowed-host handling, secure cookies, and private/no-store authenticated responses.
- Verify actual signup/confirmation and password-reset email delivery to an operator-controlled inbox. A configured backend is not evidence of delivery.
- Create the platform administrator through an authorized operator session using the staging environment and direct Neon connection. Verify email and enroll MFA before using `/admin/`. Do not seed a default administrator or password into the repository.
- Run the customer → catalog → draft → issue → PDF → partial/final payment → reversal/correction journey. Test a separate tenant and denied cross-tenant identifiers.
- Route uptime/error alerts to a named operator before pilot. Render log availability alone is not configured external alerting.

## Isolated restore drill

Install PostgreSQL client tools compatible with the source server. Create a new empty, isolated database with no public application or outbound mail connected. Supply source and target URLs through the operator's secret environment:

```bash
export DATABASE_URL='SOURCE_DIRECT_URL_FROM_SECRET_MANAGER'
export RESTORE_DATABASE_URL='EMPTY_ISOLATED_TARGET_URL_FROM_SECRET_MANAGER'
python scripts/restore_drill.py --confirm-isolated-target
```

Use `--pg-bin /path/to/postgresql/bin` when client tools are not on PATH. Keep these placeholder URLs out of shell history when using real credentials; prefer your secret manager's environment injection.

The tool refuses populated targets, never uses `--clean`, and restores with one transaction. It compares source counts/digests before and after the dump and compares the restored critical application, financial, identity/MFA, and audit records and applied migration list. Source changes abort verification so the drill can be repeated in a quiet staging window. Backups are held in a private temporary directory and removed afterward. Reports contain counts/digests and elapsed time, not customer records, passwords, or MFA secrets. Client passwords are passed in the environment rather than command arguments.

The restored target remains for authorized inspection and manual cleanup. This is a logical pg_dump/pg_restore integrity drill; it does not measure provider point-in-time restore coverage, full incident RTO, or achieved RPO. Verify protected backup retention, MFA encryption-key recovery, and an actual isolated Neon/provider restore before paid launch.

## Validation status

The local environment can run the Django/Gunicorn configuration checks, full PostgreSQL suite, Render schema validation, and a real disposable pg_dump/pg_restore drill. The CI native-build job verifies PDF rendering, WSGI startup, and collected assets without a Docker application image. Render’s own managed environment still needs a successful deployment build. A real Render deployment and provider delivery/monitoring checks require the account and staging secret configuration above.

References: [Render Blueprints](https://render.com/docs/blueprint-spec), [Render native runtimes](https://render.com/docs/native-runtimes), [Render free-service limits](https://render.com/docs/free), [Render HTTPS](https://render.com/docs/tls).

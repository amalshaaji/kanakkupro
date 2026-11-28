# Production Operations Readiness

This runbook records the operational controls required before a KankkuPro pilot. The preview deployment uses native Python on Render, Neon PostgreSQL, and Brevo SMTP. Neon Free six-hour history, an isolated point-in-time branch drill and the hardening release checks passed. The runtime alert probe reached Gmail Spam. On 2026-11-28 manual backup run 10 verified encrypted B2 upload, readback and protected retention. That exact object now passes strict local logical-archive recovery including the Neon JWT extension, with no omissions. End-to-end provider/service recovery and a later scheduled backup remain open. See [encrypted backups](encrypted-backups.md) for evidence and the recovery procedure.

## Current application controls

- `GET /health/live/` confirms the web process answers without requiring PostgreSQL.
- `GET /health/ready/` confirms PostgreSQL can answer `SELECT 1` and the shared authentication cache can be read. Create the database cache table before production logins.
- Application logs are structured JSON on stdout. Use the response `X-Request-ID` to correlate a request with its application log. Tenant IDs are included as support context; customer payloads and invitation URLs are not.
- Django production settings enforce HTTPS redirects and secure session/CSRF cookies. The current Render endpoint returned HSTS with a 3,600-second lifetime and includeSubDomains on 2026-11-27; preload is not enabled.

A ready response tests database/cache connectivity. It does not prove migrations are current, email is working, monitoring alerts are routed, or backups can be restored. Production configuration guards, privileged MFA, encrypted secrets, private response headers, and CI security gates are documented in [Production security](production-security.md).

## Decisions required before a pilot

Record these in the deployment's decision log before creating production tenant data:

- Hosting provider, region, TLS termination, and trusted proxy behavior.
- Production Neon plan and endpoint strategy for application traffic and migrations.
- Backup retention and restore capability available on that plan.
- Provider capability for the approved RPO 24 hours and RTO 4 hours targets; verify these with an isolated restore drill before pilot.
- Email delivery provider and a monitored sender address.
- Error monitoring and alert destination, with event data retention and privacy settings reviewed.
- Support contact, incident owner, and data retention/deletion procedures. The approved financial-record baseline is at least 72 months from the annual-return due date, extended for related proceedings; see [ADR-001](decisions/ADR-001-india-launch.md). Backup retention and nonfinancial data policies still need deployment decisions.

Do not enable HSTS preload, trust forwarded client IP headers, or advertise recovery objectives until the deployment has been verified.

## Release checklist

Before deploying a release:

1. Confirm CI passed against PostgreSQL and the production asset build completed.
2. Review migrations for locks, data loss, and compatibility with the currently deployed application.
3. Confirm a recent protected backup exists before a high risk schema change.
4. Deploy the application artifact, apply reviewed migrations, and check both health endpoints.
5. Run an authenticated smoke check in a non-production tenant and inspect request IDs and logs.
6. Verify error and availability alerts reach the named operator.
7. Record the release identifier and the compatible application rollback target.

Application rollback is safe only while the deployed schema remains compatible. Prefer a forward fix when a migration has changed production data. Never reverse a destructive migration as a routine rollback.

## Backup and restore drill

A production owner must complete and record this drill after selecting the database plan and before a paid launch:

1. Confirm automated backup coverage, retention, access controls, and the restore mechanism in the selected provider's current documentation and console.
2. Restore a recent backup into a new isolated database. Never restore over the production database during a drill.
3. Restrict access to the isolated database and ensure it is not connected to public traffic or outbound email delivery.
4. Record the backup timestamp and restore completion time. Calculate observed RPO and RTO and compare them with the approved targets.
5. Verify schema migration state and reconcile tenant, customer, invoice, and payment totals when those financial modules are implemented.
6. Remove the isolated restored database and record who performed and reviewed the drill.

Do not put production connection strings, credentials, or customer exports in this repository or in CI logs. The enabled daily encrypted B2 workflow and strict local logical-archive recovery are documented in [encrypted backups](encrypted-backups.md); end-to-end provider/service recovery and successful scheduled delivery remain required.

## Incident response

### Database unavailable

- Check `/health/ready/`, the hosting status page, and the database provider status page.
- Capture the time window, release identifier, and request IDs for affected requests.
- Avoid applying migrations or changing connection settings during an active provider outage.
- Notify the incident owner through the deployment's configured channel and record recovery time.

### Suspected tenant data exposure

- Treat the report as a security incident and preserve relevant request IDs, timestamps, release identifiers, and audit events.
- Restrict the affected route or deployment if exposure may be ongoing; do not access another tenant's records to investigate without an approved support procedure.
- Identify affected tenants from authorized audit and application records, contain the path, and preserve evidence before deploying a fix.
- Follow the approved incident notification and privacy process. That process must be defined before a pilot.

### Bad deployment or migration

- Stop further rollout and capture the release and migration identifiers.
- Determine whether the application or schema change caused the issue using staging or an isolated database copy.
- Roll back application code only if it is compatible with the current schema. For incompatible schema changes, prepare a reviewed forward fix or use the provider's isolated recovery procedure.
- Verify both health endpoints and a tenant scoped smoke check after recovery.

### Email delivery failure

- Check provider status, credentials, sender verification, and delivery logs without copying message tokens into incident notes.
- Keep account flows under observation until delivery is restored; do not weaken email verification or authentication controls to bypass the outage.
- Send a test message to an operator controlled account and verify delivery before closing the incident.

## Monitoring and email recovery

The `Availability check` GitHub Actions workflow checks the public readiness endpoint every 30 minutes and supports manual execution. Configure GitHub workflow-failure notifications and verify delivery to the operator. Scheduling can be delayed; this is a baseline availability check, not a real-time error-monitoring service or an availability SLO measurement. Do not deliberately fail the production service to test it; use a controlled test URL or test workflow.

When `BACKUPS_ENABLED=true`, a separate job in that workflow checks the age of
the latest successful backup upload using read-only GitHub Actions metadata. It
requires the backup's actual **Encrypt and upload backup** step to have passed
in a successful main-branch workflow run's current attempt. Storage-only checks,
skipped upload steps and failed runs do not refresh the signal. A manual backup
can establish freshness, but does not prove scheduled delivery. The age uses the
upload step's start, before the database dump, rather than its completion time.
Older than 24 hours, no qualifying upload in the latest 20 successful runs, or an
API/verification failure fails the job through existing workflow notifications.
Readiness failure cannot skip this independent job. No database/B2 credentials or
customer data are supplied to the monitor.

This checks the uploader's recorded success, not current object accessibility,
key recovery or restored financial correctness. Both workflows share GitHub's
best-effort scheduler: a GitHub-wide outage or dropped monitor run can prevent
notification. Keep an independent operator freshness review until a separate
monitoring service and its routing are approved. No 24-hour RPO is guaranteed.

For a read-only SMTP diagnosis, run `python manage.py check_email_transport` in a trusted deployment environment. It checks TLS/authentication without sending mail or printing credentials. Inbox delivery still requires a separate authorized test.

SMTP transport/authentication failures return a private 503 recovery page with a request ID. Logs record only a safe failure category, never SMTP response text or credentials. Email attempts have a 15-second timeout. Account verification is not bypassed. Invitations already committed before delivery failure remain pending; revoke and recreate an undelivered invitation after the provider is fixed. No durable automatic retry queue is claimed.

## Operational gaps

The hardening release passed all three CI jobs and is live. Payload-free runtime
alerts are enabled; the approved probe reached Gmail but was classified as Spam.
Scheduled availability checks have passed. B2 credentials passed read-only storage
checks, and the operator approved the specific backup transfer and confirmed
independent key custody. Backups are enabled, and manual run 10 verified live encrypted upload, version/size,
SHA-256 readback and 30-day COMPLIANCE retention on 2026-11-28. The exact object
passed strict local logical-archive recovery including the Neon JWT extension;
end-to-end provider/service recovery and a later scheduled delivery remain open.
Local and CI two-tenant HTTP/PDF workloads passed. Public post-release readiness
returned 200 in 21.54 seconds after an earlier 30-second timeout; deployed latency
and cold-start objectives remain open. See [Phase 6 verification](phase-6-verification.md).
These are deployment and decision gates, not completed controls. The pilot gate
remains blocked until they are configured and verified alongside the commercial
workflow.

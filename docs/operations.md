# Production Operations Readiness

This runbook records the operational controls required before a KankkuPro pilot. It is provider independent because the hosting provider, production Neon plan, and email provider have not been selected. It does not claim that backups, alerting, or recovery are configured.

## Current application controls

- `GET /health/live/` confirms the web process answers without requiring PostgreSQL.
- `GET /health/ready/` confirms PostgreSQL can answer `SELECT 1`.
- Application logs are structured JSON on stdout. Use the response `X-Request-ID` to correlate a request with its application log. Tenant IDs are included as support context; customer payloads and invitation URLs are not.
- Django production settings enforce HTTPS redirects and secure session/CSRF cookies. HSTS remains disabled until the production domain and TLS path are verified.

A ready response only tests database connectivity. It does not prove migrations are current, email is working, monitoring alerts are routed, or backups can be restored.

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

Do not put production connection strings, credentials, or customer exports in this repository or in CI logs. No backup schedule or restore command is prescribed here because the hosting and Neon plan are still open decisions.

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

## Operational gaps

The repository currently has no provider configured for external error tracking, uptime alert routing, backup scheduling, or restore automation. Performance objectives also have not been measured against representative tenant data. These are deployment and decision gates, not completed controls. The pilot gate remains blocked until they are configured and verified alongside the commercial workflow.

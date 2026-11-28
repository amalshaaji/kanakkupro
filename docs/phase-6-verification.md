# Phase 6 verification

Status: engineering checks passed and the hardening release is deployed. Operational
gates below remain open; this document does not authorize pilot admission.

## Verified release

[CI run 38](https://github.com/amalshaaji/kanakkupro/actions/runs/46025851685)
passed all three jobs for commit `22ac7484c0a0328f24d729f72d8f27460daf89b1`:

- 201 backend tests passed. The two opt-in restore tests were skipped in that
  invocation, then both passed in the dedicated real PostgreSQL/age restore step.
- Production configuration, migrations, dependency audits and native build passed.
- Eleven desktop/mobile browser tests passed; the desktop invocation of the
  mobile-only navigation test was intentionally skipped. All audited owner screens
  passed the configured automated accessibility rules at both viewport sizes.
- The isolated single-worker HTTP workload and PDF request passed with unchanged
  financial totals and a foreign-tenant 404. The synthetic review artifact is
  retained for seven days on that run.

Render deployment `dep-dc4q7gm1egvs739ebb6g` became live at 15:39:21 UTC on
2026-11-27. Its `/health/ready/` check passed. A later public readiness check
returned HTTP 200 in 21.54 seconds after an earlier request timed out at 30 seconds.
This is not evidence of an acceptable cold-start or production latency SLO.

## Runtime error alerts

The application can use its existing email transport to send minimal runtime
alerts to explicitly configured operator inboxes. This adds no runtime dependency
or new external service account. Configure `RUNTIME_ALERT_EMAILS` with the approved
inboxes and set `RUNTIME_ALERTS_ENABLED=true` only after reviewing the destination.
Deployment checks reject enabled alerts without valid inboxes.

Alerts contain only a fixed event name, timestamp, deployment environment, generated
request ID, 5xx status and exception class. They exclude exception messages,
tracebacks, source paths, URLs, query strings, headers, cookies, request bodies,
user/customer details and tenant IDs. The original structured logs remain the
source for request-ID correlation.

The shared cache permits one alert per five minutes across all workers. Cache or
transport failures cannot replace the original response; cache failure suppresses
sending to prevent unthrottled mail. The SMTP connection timeout is three seconds.
Delivery failures use a separate console-only logger and cannot recursively send
alerts. Review/test settings disable alerts and outbound mail.

With a trusted deployment environment loaded, the following command sends a
synthetic event to the configured operator inboxes without breaking an application
route:

```bash
python manage.py check --deploy
python manage.py send_runtime_alert_test --send
```

The JSON result `provider_accepted` is not proof of inbox delivery. Verify the
request ID in the actual inbox before closing this gate. This is bounded email
notification, without error aggregation or durable retry. It shares the email
provider's availability. A dead process cannot send email; retain the independent
availability workflow and verify its failure notifications.

For a platform without interactive shell access, set `RUNTIME_ALERT_PROBE_ID` to a
new UUID for one explicitly requested release probe. After the normal release
checks, startup invokes the same command with `--probe-id UUID`. A persistent
audit claim prevents that ID from attempting mail again across cache expiry and
process restarts. Probe failure cannot block startup. Remove the variable after
checking the safe status log and matching inbox message. A retry requires a new
UUID; provider acceptance alone still does not establish inbox delivery.

Fifteen local tests passed for metadata privacy, real 500/503 request correlation,
concurrent rate limiting, cache/transport failure, the audited operator probe and
its nonblocking release boundary, and deployment checks.

The deployed Render service uses `/health/ready/` as its HTTP health check. Runtime
alerts are enabled for the operator-approved destination. At 15:39:09 UTC on
2026-11-27 the actual Gmail message matched probe request ID
`c399c557c0c44af1842730e70150d3e9`; Render logged `provider_accepted` for that same
ID. Gmail classified it as Spam despite passing SPF, DKIM and DMARC. Transport and
recipient delivery are proved; reliable operator inbox placement remains open.
The one-time probe marker was cleared using Render's Save only option for the next
deployment. Its existing audit claim prevents the running release from repeating it.

## Isolated review environment

`config.settings.review` and `scripts.pilot_review` require a localhost PostgreSQL
database whose name begins `test_pilot_review_`. They reject hosted databases and
host/service overrides. Seeding refuses existing users/businesses; it never clears
an existing database. Use a freshly created disposable database and an ephemeral
`PILOT_REVIEW_PASSWORD` of at least 16 characters. No staff/superuser is created.
Email and runtime alerts are disabled in this environment.
Only this guarded review configuration allows 100 legitimate logins per minute
from the shared localhost IP for accelerated browser runs. Failed-login limits
remain active.

```bash
# Load the new local review database URL and an ephemeral password privately.
export DJANGO_SETTINGS_MODULE=config.settings.review
python -m scripts.pilot_review --invoices 100
python manage.py runserver 127.0.0.1:8765 --noreload
```

The synthetic fixture contains two isolated businesses, owners and a viewer, 100
customers, 20 catalog items, 200 invoices and 10 credit notes, 1,010 document lines,
partial payments and reversals. It uses the application issuance/payment services.
Never load this dataset into the deployed database.

## HTTP workload evidence

In a second terminal using the same private review environment:

```bash
python -m scripts.benchmark_pilot --base-url http://127.0.0.1:8765 --output /private/tmp/pilot-benchmark.json
```

Use `--include-pdf` when native PDF libraries are installed. Four concurrent
authenticated clients exercise dashboard, customer/catalog/invoice lists, financial
reports, pilot guide and invoice detail over HTTP. Checks require the correct
business's rendered content, a 404 for a foreign invoice, and unchanged financial
totals. Redirects are rejected rather than mistaken for successful page responses.

The [2026-11-27 local report](evidence/phase6-local-benchmark-2026-11-27.json)
recorded 84 successful requests: median 32.59 ms, p95 45.67 ms, maximum 49.47 ms.
The foreign invoice returned 404. This used the threaded Django development server
on local PostgreSQL 18.7, without PDF rendering. It does not establish Render/Neon
latency, browser LCP, production capacity or a cold-start SLO.

The CI `pilot-review` job repeats the fixture and workload using one Gunicorn
worker, includes a real PDF request, and preserves aggregate benchmark and browser
reports as a seven-day artifact. No production credentials are supplied to this job.

## Browser and accessibility checks

Development-only Playwright and axe dependencies allow CI to repeat the desktop
and mobile journeys and WCAG 2.2 A/AA automated checks. The browser configuration
refuses external origins; each test also blocks nonlocal requests. Test artifacts
contain only synthetic review data.

```bash
npm run test:browser
```

The checks cover the keyboard skip link, mobile keyboard navigation, core forms
and list/report screens, contrast/labels, horizontal overflow, invoice issuance,
partial/final payments, a PDF download, foreign-tenant denial and viewer denial.
Manual local browser verification on 2026-11-27 completed an INR 118.00 invoice,
payments of 50.00 and 68.00, zero outstanding and matching dashboard changes.
The 390 px mobile view had no page-level horizontal overflow and its menu opened
from the keyboard. The review found the skip-link target could not take focus;
both application and account main landmarks now have `tabindex=-1`, with a browser
regression check. Automated findings also identified low-contrast form labels and
help links; these now use the darker shared text color.

Automated scans do not certify WCAG conformance. Screen-reader semantics, zoom,
focus order, actual device behavior and content meaning still require review.

## Recovery evidence

On 2026-11-27 both real PostgreSQL dump/restore tests passed locally, including
age encryption/decryption and equality of the critical financial/audit manifest.
The existing private recovery identity also decrypted a synthetic local canary
encrypted to the documented public recipient. No private identity was copied or
uploaded, and no deployed records were read or changed for these checks.

The operator explicitly approved the Neon → GitHub Actions → private B2 transfer
and confirmed a recovery-key copy outside this project on 2026-11-27. The enable
flag is saved. The [live encrypted upload](https://github.com/amalshaaji/kanakkupro/actions/runs/46057506524)
passed on 2026-11-28, including version/size, 30-day COMPLIANCE retention and SHA-256
readback. See [object evidence](evidence/phase6-b2-backup-2026-11-28.json).
Application recovery of that exact B2 object is now verified with the explicit
provider-extension exception below. Full provider recovery and a later scheduled
delivery remain open in [the backup runbook](encrypted-backups.md).

On 2026-11-28 the isolated encrypted-file restore verifier passed sixteen safeguard
tests and both real PostgreSQL recovery tests. It verifies the downloaded digest,
restores only into an empty local drill database, checks migrations and generates
the financial/audit manifest with mail disabled. The full financial fixture
manifest matched after actual age decryption and restoration.
[CI for the restore verifier](https://github.com/amalshaaji/kanakkupro/actions/runs/46059228932)
passed backend checks, native build and desktop/mobile review for commit `7fc25da`.

The authenticated B2 download matched the run-10 ciphertext SHA-256 and size.
The first strict restore failed atomically because local PostgreSQL lacks Neon's
`pg_session_jwt` extension; the target remained empty. Code and recovered schema
inspection found no Neon JWT function use, RLS policies or enabled row security.
The explicit `--omit-neon-session-jwt` option then omitted only its extension and
comment entries, preserving all application objects and data. It reports
`application_restored_and_verified` and `full_archive_restored: false`; this is
not evidence of full provider/authentication recovery.

On 2026-11-28 at 13:42:49 Asia/Kolkata, this application restore passed migration
checks (44 applied migrations) and generated the 18-model manifest. It took
0.927 seconds after local input validation; download, operator access and service
recovery are excluded. A read-only transaction confirmed all ten expected
financial/audit guard triggers enabled, no unvalidated public constraints, no
orphaned checked tenant relations and a zero-balance summary for the one tenant.
Mail was disabled. There are four audit records, but no invoices, payments or
reversals. No independent same-snapshot source manifest exists, so source equality,
nonempty live financial reconciliation, multi-tenant recovery behavior and
end-to-end RPO/RTO are not established. Twenty safeguard tests and both real
synthetic financial restore tests passed after the compatibility change.
[CI for the live-backup recovery change](https://github.com/amalshaaji/kanakkupro/actions/runs/46124918571)
passed backend checks, native build and desktop/mobile review for commit `e8ffd33`.
The private restored database is retained for authorized inspection/cleanup; the
local server is stopped and the read-only tool image is unmounted.

## Backup freshness monitoring

On 2026-11-28 a read-only check of actual GitHub metadata identified manual run
10 as the latest verified upload, with its upload step starting at
2026-11-27 19:33:43 UTC. Its age was below the 24-hour alert threshold. The
workflow remains active, but the latest scheduled record is still the earlier
skipped run; successful scheduled delivery is not established.

The existing availability workflow now checks backup freshness in a separate job
when backups are enabled. It uses only a read-only Actions token and requires a
successful upload step in the current attempt of a successful main-branch backup
run. Twenty-three offline tests passed, including missed/stale backups,
storage-only checks, failed/skipped steps, reruns, timestamp validation and private
failure output. An older-than-24-hour upload, no qualifying upload within the
bounded history, or unavailable verification fails the monitoring job. This does
not prove B2's current accessibility or restoration, and the shared GitHub
scheduler can delay/drop either workflow. Independent monitoring and actual
failure-notification delivery remain operator gates.

The [first live monitor run](https://github.com/amalshaaji/kanakkupro/actions/runs/46125877791)
passed both readiness and backup freshness on 2026-11-28. The
[CI run for commit `f339c5c`](https://github.com/amalshaaji/kanakkupro/actions/runs/46125877774)
passed backend checks, native build and desktop/mobile review. This is a
push-triggered monitor result; no successful scheduled backup or fresh
missing-backup alert email was observed by this check.

## Remaining operator gates

- Verify full provider recovery with `pg_session_jwt` available, and prove a later
  scheduled run. The exact B2 object's isolated application restore is verified.
  The 2026-11-28 schedule check still showed only the earlier skipped scheduled run;
  successful scheduled delivery remains unobserved.
- Resolve alert inbox placement; the approved runtime probe arrived in Gmail Spam.
- Verify real password-reset/invitation delivery and inbox placement.
- Verify deployed platform-admin MFA/recovery, credential replacement and least
  privilege for database/operator access.
- Measure representative deployed latency/cold starts and finish the manual
  accessibility review.
- Approve support/incident ownership, nonfinancial retention/deletion, privacy/terms
  and the consenting 3–5-business pilot cohort.

Keep Phase 6 open until this evidence is recorded. Phase 7 begins with the agreed
pilot cohort; Phase 8 billing follows a reviewed pilot outcome.

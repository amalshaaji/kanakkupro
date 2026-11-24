# Phase 6: security and release checks

## Implemented controls

- Production startup rejects missing/weak session secrets, wildcard/URL hosts, implicit or non-TLS database URLs, test email backends, incomplete SMTP settings, insecure CSRF origins, and invalid/missing MFA encryption keys. Configuration errors do not echo database URLs or key values.
- Database pooling and local-host detection use the parsed hostname. Password text cannot influence either. Explicit `verify-ca`/`verify-full` certificate verification is preserved.
- `X-Forwarded-Proto` is ignored unless `TRUST_X_FORWARDED_PROTO=True`. Enable this only when the controlled reverse proxy strips client-supplied values and sets the header from the actual transport.
- Django admin's password form is replaced by an allauth login requirement, preserving allauth verification, throttling, and MFA stages. A guard on every admin view additionally requires verified email, an enrolled TOTP authenticator, and a successful MFA challenge in the current session within 15 minutes. A password-only `force_login`/alternate-backend session cannot bypass this guard.
- TOTP and recovery codes are available through allauth's account-security pages. Staff cannot remove their TOTP authenticator through self-service while they retain platform access. The raw Authenticator model is not exposed in Django admin.
- MFA secrets are encrypted using versioned Fernet ciphertext. The first configured key encrypts new values; older listed keys support staged rotation. Production never derives MFA keys from the session secret or accepts plaintext fallback.
- MFA enrollment/removal/reset/use and approved admin requests write minimal append-only audit events, including actor, request correlation ID, route/method/status where relevant, and authenticator type. Secrets and authentication/recovery codes are not recorded.
- Authenticated pages and allauth login/MFA responses are private/no-store. Existing private CSV/PDF headers remain intact.
- Readiness now checks both PostgreSQL and a read against the authentication cache. With the production database-cache backend, a missing/unavailable cache table produces a generic 503. Liveness remains a separate process-only probe.

## Rollout

1. Install `requirements.lock`, build frontend assets, and configure deployment secrets using `.env.production.example` as a reference. Do not commit populated environment files.
2. Generate `SECRET_KEY` with Django's `get_random_secret_key()` and an independent encryption key with `Fernet.generate_key()`. Keep both in the deployment's secret manager. Store protected recovery copies separately from database backups.
3. Apply migrations, including the newly enabled allauth MFA migrations: `python manage.py migrate`.
4. Create the shared authentication-cache table: `python manage.py createcachetable`. All application instances must share this cache for rate limits and TOTP-code replay protection.
5. Existing platform staff sign in through `/accounts/login/`, verify their email, enroll a TOTP authenticator under `/accounts/2fa/`, and store recovery codes securely. Access to `/admin/` requires a fresh MFA challenge. Enrollment and recovery must be tested before relying on platform access.
6. Verify trusted hosts, email delivery, and HTTPS end to end. If the hosting proxy terminates TLS, confirm its header behavior before enabling `TRUST_X_FORWARDED_PROTO`.
7. Enable HSTS only after verifying the domain and HTTPS deployment, then run `python manage.py check --deploy --fail-level WARNING`. HSTS preload remains deliberately disabled. Only Django's preload suggestion (`security.W021`) is explicitly silenced; all other deployment warnings remain active. No preload submission is made.
8. Confirm `/health/live/`, `/health/ready/`, MFA/recovery, authorized tenant switching, and one commercial-workflow smoke test. Verify privileged events appear in the audit ledger without sensitive values.

Development/test encryption may derive from a persistent configured Django secret. Local enrollment refuses an ephemeral development secret. Keep the same development secret or use dedicated MFA keys across restarts; changing it without retaining the correct key prevents decryption of existing authenticators.

## Encryption-key rotation and recovery

To introduce a new key, put it first in `MFA_ENCRYPTION_KEYS` and retain existing keys after it. New enrollments use the first key; existing ciphertext remains readable with the older keys. Retaining a fallback key does not re-encrypt old records. Do not remove an old key until all affected records have been migrated or users have completed an authorized re-enrollment procedure, and a restore drill confirms readability. This release does not automate bulk re-encryption.

Loss of the encryption keys can make restored MFA records unusable. Database backups alone are insufficient. Emergency platform-account reset requires an operator procedure with identity verification and an audit trail; direct unaudited secret edits or removal of the MFA guard are not recovery mechanisms. The production owner must define custody, key-retention, and emergency access procedures before pilot.

## CI and local verification

CI runs Ruff, Django checks, migration-drift checks, PostgreSQL tests, a production configuration/security check using synthetic values, a pinned `pip-audit` tool against the complete Python lockfile, npm audit, and the frontend build. Vulnerability findings fail the pipeline; no advisory is ignored. pytest was upgraded past the vulnerable temporary-directory implementation documented in [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g).

Tests cover actual allauth TOTP login/reauthentication, denied password-only admin sessions, expired/wrong-user MFA grants, encrypted secret rotation/failure behavior, verified-email enforcement, logout audit actor preservation, private response headers, production misconfiguration rejection, proxy opt-in, TLS preservation, and cache-readiness failures.

CI validates configuration and regressions; it does not prove actual provider delivery, live infrastructure security, or achieved recovery objectives.

## Remaining Phase 6 release work

Select and configure hosting/region, production Neon plan, email delivery, external error tracking, uptime/latency alert routing, and protected backups. Perform an isolated provider restore drill, preserving MFA key access and reconciling financial/audit data. Measure performance under representative tenant data and concurrent usage, verify least-privilege database/operator roles, and complete the incident/support and privacy procedures in [Operations](operations.md). Owner/Admin MFA remains optional pending the business-account risk decision; platform-staff MFA is mandatory.

References: [allauth admin integration](https://docs.allauth.org/en/latest/common/admin.html), [Django proxy-header security](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header), [pip-audit](https://github.com/pypa/pip-audit).

# Daily encrypted backups to Backblaze B2

Status as of 2026-11-28: daily backups are enabled. The [first verified live
upload](https://github.com/amalshaaji/kanakkupro/actions/runs/46057506524) passed at
approximately 01:03 Asia/Kolkata. It checked private storage, encrypted upload,
object version/size, at least thirty days of COMPLIANCE retention, and SHA-256 of
the ciphertext downloaded back from B2. The object is 128,544 bytes. Its version
and digest are recorded in [backup evidence](evidence/phase6-b2-backup-2026-11-28.json).
The operator approved the specific transfer and confirmed independent recovery-key
custody. **Provider-backed restoration and a later scheduled delivery remain open.**
This adds independent daily logical copies; it does not extend Neon's six-hour
point-in-time history.

## Verified bucket configuration

- Private bucket: `kanakkupro-backups-29988154`.
- Endpoint: `https://s3.us-east-005.backblazeb2.com`; region `us-east-005`.
- Provider encryption at rest enabled.
- Default Object Lock retention: 30 days. A newly uploaded object's actual compliance retention is checked by the job.
- Bucket lifecycle currently keeps all versions. Retention prevents early deletion; it does **not** automatically expire old files. No deletion automation is included.

## Encryption and key custody

The job uses standard age recipient encryption, not a custom encryption format. Only a public recipient belongs in GitHub. The private recovery identity was generated locally in the ignored `.backup-keys/recovery.agekey` file with restricted permissions. Store a protected copy in a separate password manager/offline recovery location before enabling uploads. Losing it makes the backups unusable; a new key cannot decrypt older backups. Keep each old private identity while backups encrypted to it exist. Never put this private identity in GitHub Secrets, Render, B2, Git, chat, or logs.

Public recipient for the current local recovery identity:

```text
age1shzskczuqaxtkdk56aekt3tkayyenr6gpjc6js3r9l63s2xyeu7sqd6s4p
```

MFA encryption keys and application secret recovery custody remain separate requirements. They are not included in the database dump.

## Activation

The operator approved the specific Neon → GitHub Actions → private B2 transfer
and confirmed the private recovery key is saved separately on 2026-11-27.
`BACKUPS_ENABLED=true` was verified after GitHub access verification. Manual run
10 passed on 2026-11-28. The next scheduled delivery must be observed separately.

The workflow `.github/workflows/backup.yml` uses native Python/age/PostgreSQL clients on a GitHub-hosted Ubuntu runner, without Docker. Scheduling is gated by `BACKUPS_ENABLED=true` and the main branch. It runs daily at 02:17 UTC (07:47 Asia/Kolkata), plus a manual dispatch. GitHub schedules are best effort; review failures and freshness. Daily cadence alone is not a guaranteed 24-hour RPO.

1. Review/approve the new backup credential and the transfer of the Neon connection secret to GitHub Actions. Use a bucket-restricted application key, not a master key. A prepared web form selects only this bucket, read/write access and a 90-day expiry. The standard UI preset can include deletion capabilities; compliance retention blocks early deletion and this job never invokes deletion. Prefer a custom API-created key with only `listBuckets`, `readBuckets`, `listFiles`, `readFiles`, `writeFiles`, `readBucketRetentions`, and `readFileRetentions` if an authorized operator can provision it. No all-bucket listing is required. Review renewal before the key expires.
2. In repository `amalshaaji/kanakkupro`, create a GitHub Actions environment named `backups` restricted to main. Store these environment secrets privately:
   - `BACKUP_DATABASE_URL`: current TLS-protected Neon source URL, ideally a dedicated read-only backup role able to dump all required tables. Never reuse an exposed old password.
   - `B2_KEY_ID` and `B2_APPLICATION_KEY`: the restricted B2 credential pair.
3. Set `BACKUP_AGE_RECIPIENT` to the public recipient above. Confirm the private recovery identity is separately recoverable, then set repository variable `BACKUPS_ENABLED=true`.
4. Manually run **Encrypted database backup**, initially choosing `storage-check`. This read-only mode checks bucket privacy, compliance retention and versioned storage usage with the existing B2 credentials. It receives no database URL, does not dump or upload data, and can run while `BACKUPS_ENABLED` is false. After that succeeds and key custody is confirmed, choose `backup`. Check success, the B2 object version and its 30-day retention, then perform the isolated restore below. Do not mark the backup release gate complete from an upload alone.
5. Prove a later scheduled run and failure notification. Review account usage/caps and the key expiry. Repository write access can alter code that receives backup secrets: protect main and workflow changes, limit Actions/environment access, and review collaborators.

The job runs pg_dump in a consistent read-only snapshot, checks its archive listing, encrypts locally on the ephemeral runner, uploads only ciphertext, reads it back, and compares SHA-256. Plaintext temporary files have mode 0600 within a private temporary directory and are removed on normal success/failure. No plaintext backup artifact is retained by GitHub. Tool stderr is suppressed in user-visible failures. These checks do not establish successful database restoration.

Both modes log fixed stage names and allowlisted failure types/provider codes,
without printing exception messages, credentials or provider response bodies.
A live upload initially failed with `SSLError`. Removing `Expect: 100-continue`
through the SDK's before-sign request hook resolved the TLS failure while keeping
certificate validation enabled. The following `InvalidRequest` rejection was
resolved by supplying Content-MD5 for the Object Lock upload. The authoritative
readback integrity check remains SHA-256. Twelve targeted tests cover storage
policy, ciphertext verification, diagnostic privacy and actual SDK request
preparation. The backup workflow runs them without production secrets before the
upload step.

## Storage budget and free-tier limits

Backblaze advertises the first 10 GB of storage free. This job conservatively stops before its bucket exceeds 1 GiB including noncurrent versions, and refuses individual encrypted files over 25 MiB. It never deletes files or changes lifecycle/retention. These guards are **not an account billing cap**: concurrent writers, incomplete multipart uploads, other buckets, runner usage and provider terms can affect usage. Configure provider spending caps/alerts separately and keep this bucket dedicated. Review expired backups manually before the cap stops new uploads; deletion requires separate authorization. Thirty-day retention is a minimum protection period, not an automatic rolling 30-day expiration policy.

## Recovery drill

1. Download a specific encrypted object version from the private bucket to a trusted recovery host. Verify its SHA-256 against the successful job's reported value. Keep download credentials private.
2. With age installed, decrypt using the separately held private identity. Use a private scratch directory and `umask 077`. For example, with local file paths only:

   ```bash
   umask 077
   age --decrypt --identity /protected/path/recovery.agekey --output /private/scratch/database.dump /private/scratch/database.dump.age
   pg_restore --list /private/scratch/database.dump > /dev/null
   ```

3. Use a matching/newer PostgreSQL client to restore into a confirmed empty, isolated PostgreSQL target using `--exit-on-error --single-transaction --no-owner --no-privileges`. Load its connection credentials privately through PG environment variables; never pass a password in command arguments. Do not use `--clean` or restore over production.
4. Run `restore_manifest --all-tenants` on the recovered database, reconcile financial/audit records, and verify tenant isolation, login/MFA, PDF and reports with an isolated application. The backup does not include an independently captured logical manifest because live writes could race a separate manifest; use the dump's consistent snapshot and known business/audit checkpoints for recovery reconciliation.
5. Record object version, capture/restore timestamps, reconciliation and application results. Measure actual write loss and incident-to-service recovery. Remove local plaintext and dispose of the isolated target only under an authorized cleanup procedure.

Local evidence: six targeted tests passed on 2026-11-26, including real PostgreSQL 18 dump, age encryption/decryption, real pg_restore and equality of the full critical-model manifest after restoring synthetic invoices, credit note, payments, reversal and audit records. The storage client was simulated; Live B2 upload/readback/retention checks have since passed in run 10; restoration of that actual object is still required. CI repeats encryption recovery with PostgreSQL 16 and age.

Sources: [age](https://github.com/FiloSottile/age), [PostgreSQL Ubuntu packages](https://www.postgresql.org/download/linux/ubuntu/), [Backblaze pricing](https://www.backblaze.com/cloud-storage/pricing), [B2 key capabilities](https://www.backblaze.com/docs/cloud-storage-application-key-capabilities).

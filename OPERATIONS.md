# Development and operations

## Setup

Install requirements.txt in a Python virtual environment. Configure the administrator token in a protected service environment. From the project directory:

```
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Put HTTPS termination in front of the service before remote administration. Do not expose an HTTP preview to production traffic. Configuration names and examples are in .env.example; keep actual credentials outside Git. Proxmox requires a trusted certificate, a matching hostname, and an appropriately scoped API token. API access fails closed when tokens are missing.

## Current boundaries

The administration interface, SQLite state, repair queue reservations, audit journal, read-only monitoring framework, and release safety services are implemented. Builder enrollment, automated repair execution, live release publisher adapters, individual administrator accounts/roles, and production HTTPS configuration still require implementation. Queue reservations do not start VMs. Provisioning, automatic recovery, and Edge integrations remain future modules.

## Security hardening

SQLite database files are created or restricted to owner-only permissions before the engine opens them. New database directories default to owner-only access; operators must protect existing directories and backups. Request bodies are limited to 256 KiB before decoding, including streamed bodies. Malformed non-ASCII authentication headers are rejected. Source archives are compressed once per worker lifetime; deploy immutable release directories and restart workers for each release. Public source downloads exclude runtime configuration, databases, logs, private keys, and .env files.

These controls do not replace TLS, network access restrictions, rate limiting, administrator identity, dependency vulnerability review, or production testing. The migration and deployment adapters are tested with simulated infrastructure; this is not evidence that an end-to-end production deployment is ready.

## Verify

```
python -m unittest discover -s tests -v
alembic check
```

The test suite covers queue concurrency, error deduplication, migration checksum and backup gates, Final Sync shutdown ordering, expected-state observation, credential-file permissions, source exclusions/caching, request body limits, and local database permissions.

## Application reporting credentials

Open a project in the admin interface to issue a reporting credential, shown only once, and revoke older credentials. Store the token in the application's protected environment and send it as an Authorization Bearer header to POST /api/reports. The payload must identify that credential's project. Credentials cannot access administrator APIs or report for other projects. Only SHA-256 token digests are stored; generated tokens have 384 bits of random entropy. Audit records identify the credential ID, never its token. Reporting responses expose only acknowledgement fields.

The old global CONDUCTOR_REPORT_TOKEN is no longer accepted. Existing integrations must obtain a project credential. Revocation takes effect for requests that acquire the database writer lock after revocation commits. Use HTTPS for credential issuance and reporting in production; the LAN HTTP preview remains a temporary development setup.

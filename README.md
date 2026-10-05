# DenOps Conductor

DenOps Conductor is licensed under **AGPL-3.0-only**. DenOps Systems Inc. is the planned publisher (company formation pending). See [LICENSE](LICENSE) for the full license and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution terms. Existing contributors retain their rights; this notice does not assign copyright to the future company.

Internal FastAPI administration service. Conductor state stays in SQLite; production database secrets are represented by environment reference names only.

## Run

Install `requirements.txt` in a virtual environment. Set `CONDUCTOR_ADMIN_TOKEN` and a distinct `CONDUCTOR_REPORT_TOKEN` in a protected service environment. Run from this directory:

```
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use an HTTPS reverse proxy for remote administration. Open `/` and enter the administrator token. Tokens remain in browser memory; requests use Authorization headers rather than cookies, so browser ambient credentials cannot authorize CSRF requests. API access fails closed if its token is unset. `/health` retains its original public response.

The UI supports project creation/editing, dedicated builder registration, repair reporting and deduplication, queue reservation, repair details, release inspection, migration ledger inspection, and audit history. Secret reference fields contain environment variable names, never database passwords. API documentation is at `/docs`.

## Current boundary

This is the administration and persistence foundation, not a production deployment engine. Queue reservations are serialized through SQLite's single Alpha slot and ordered critical/high/medium/low, then oldest first. They never preempt an active repair and never start a VM. VM power and project health remain unverified until live integration is implemented. Release and migration views show persisted records; this version does not create or deploy releases.

The Proxmox service provides verified-TLS status, guest-agent ping, start, and graceful-shutdown calls. It is deliberately not exposed as a direct web action. No VM deletion, forced stop, shell execution, SQL execution, or production deployment is available through the UI.

Safety services include exact-commit Git checkout with dirty-workspace refusal, immutable migration checksum planning, a PostgreSQL DB-API runner with advisory locking and transactional ledger writes, mandatory checksum-bound schema approval and backup verification, and a deployment sequencing interface that confirms health and persisted release state before Final Sync shutdown. These services are not connected to live servers. The PostgreSQL runner is tested with a simulated connection, not a live PostgreSQL database. Nontransactional SQL requires a separate reviewed runner. High-risk detection is conservative and cannot prove arbitrary SQL safe.

Next implementation stages: live Alpha reconciliation; production commit discovery and trusted builder transport; authenticated builder lifecycle; concrete immutable release publisher and approval records; PostgreSQL connection provisioning; backup/WAL verification adapters; health adapters; durable release events; background scheduling and crash recovery. Do not enable automatic infrastructure execution until these gates are implemented.

## Verify

```
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/alembic check
```

## Proxmox connection

The supplied endpoint is `https://192.168.1.3:8006`; development sandbox is VM 115 (`test-node`) on node `builder` (192.168.1.13), confirmed from the supplied Proxmox screenshot. Conductor is VM 114 (`conductor-server`); VM 117 (`denops-travel-builder`) is a separate project builder. Connectivity was confirmed, but the presented certificate names `burrow-01.denops.ai`, `burrow-01`, and `192.168.0.164`, not the supplied IP. Use a certificate-matching hostname resolving to this server or update the server certificate. Set `CONDUCTOR_PROXMOX_CA_FILE` to an independently trusted Proxmox CA PEM when needed. Certificate verification stays enabled. Configure `CONDUCTOR_PROXMOX_TOKEN` in the protected service environment using Proxmox token format `user@realm!token-id=secret`; do not put it in source or chat.

Existing credentials can be loaded with `CONDUCTOR_PROXMOX_TOKEN_FILE=/opt/proxmox_secret.env`. The file uses `token_id` and `secret` keys and must have owner-only permissions; the service account must own or be able to read it. An explicit `CONDUCTOR_PROXMOX_TOKEN` takes precedence. The secret is never returned through administration APIs.

The supplied CA at `/etc/denops-conductor/certs/proxmox-ca.pem` successfully verifies the server certificate with hostname `burrow-01.denops.ai` and address `192.168.1.3`. Configure DNS (or a host mapping) for that hostname before using the standard client. After the Proxmox ACL update, an authenticated VM 115 status request succeeded (HTTP 200): `test-node` on node `builder` is stopped. Live sandbox lifecycle testing passed: VM 115 was started, observed running, gracefully shut down, and observed stopped. QEMU guest agent ping reported that no guest agent is configured. No forced stop was used. The credential file currently requires privileged read access, so configure the eventual service account accordingly.

## Long-term architecture

Conductor is the DenOps control plane for repair, release orchestration, infrastructure observation, future provisioning, and future Edge configuration. Repair/build remains the first priority. The existing project models, SQLite state, Alpha single-slot reservation, migration safety gates, and verified Final Sync workflow remain in place.

The Infrastructure page now supports resource inventory, explicit expected state, configurable monitoring checks, manual read-only observations, freshness indicators, and audit records. Only the Proxmox VM power-state probe is implemented. Missing adapters, configuration failures, unsupported resource kinds, expired observations, and unverified guest readiness never imply healthy infrastructure. Observations do not mutate VM power state, create incidents, or trigger repairs. No background watchdog or automatic recovery runs.

Expected state distinguishes `running`, `stopped`, `on-demand`, and `policy-controlled`. Production VMs can expect running; templates can expect stopped; repair VMs are on-demand; maintenance uses policy-controlled state. On-demand and policy-controlled power observations report unknown policy health until a lifecycle/maintenance evaluator supplies context. An intentionally stopped VM must never be blindly restarted. The old `desired_power` database field is retained for migration compatibility and is not used by the watchdog.

### Module and provider boundaries

- `app/api/infrastructure.py` owns authenticated infrastructure administration, separate from repair/deployment routes.
- `app/services/watchdog.py` owns read-only probes and status/freshness evaluation. The registry supports future node, service, HTTP, database, disk, CPU, memory, TLS, DNS, mail, PostgreSQL backup/PITR/WAL, WireGuard, Edge, and network adapters.
- `app/services/proxmox.py` remains the single Proxmox API service. Guest Agent support is optional for current VM 115; future production/client templates can require it.
- `app/services/providers.py` defines VM, provisioning, DNS, and Edge contracts and typed plans. Git/SSH, PostgreSQL, Cloudflare, DenOps Edge, Omada, Vultr, and other providers can supply implementations outside project logic. Provider credentials stay in protected server configuration.
- `app/services/events.py` appends integration events in the caller's database transaction. New repair jobs emit `repair.queued`; monitoring runs emit `monitor.observed`. Release and builder event types are reserved for concrete lifecycle integrations. No event consumer, external notification, cache purge, or automatic action is enabled. Future consumers need independent durable cursors, idempotency, retry handling, and authorization boundaries.
- Infrastructure incidents and recovery action records can associate a resource/check with a repair ticket, approvals, action outcome, and verification. They are storage foundations only. Future restart-service, start-VM, verify-recovery, create-repair, and notify-admin policies default disabled and require a separately implemented executor with expected-state checks, bounded retries, cooldowns, approval, and audit history.

### Future provisioning

The future provisioning flow is approved service definition → node/template selection → clone → Cloud-Init hostname/network/authorized SSH keys/client enrollment → start → Guest Agent/client readiness → application deployment → provider-based exposure → health verification → ready. Typed plans reference network profiles, authorized SSH keys, and enrollment material; they do not embed credentials. No cloning or Cloud-Init endpoint is implemented, and no template or VM has been modified by these architecture additions. Provisioning compute must coordinate with Alpha's single-builder slot rather than bypass it.

Exposure is a per-service policy: LAN only, WireGuard only, Cloudflare Tunnel, Cloudflare proxied, DenOps Edge, direct reverse proxy, or custom. The contract defaults to LAN only. Cloudflare is optional, and application code never depends on a selected exposure provider or active origin WAN.

### Future DenOps Edge

Conductor manages configuration; DenOps Edge handles public ingress, TLS, reverse proxying, health routing, load balancing, explicitly approved caching, static assets, origin shielding, rate limits, maintenance, security policies, and WireGuard backhaul. Alpha supplies repair compute; production hosts run applications; the database host owns PostgreSQL; Git remains authoritative for code/releases.

East, Central, and West are configurable deployment roles, not hard-coded region/provider identities. All can serve active production traffic. A rollout uses one immutable configuration version/checksum, validates it on a selected first node, checks syntax/health/routing, then promotes the identical artifact to other nodes and verifies them. The validation node may also serve production. Staging may select a subset of the same physical nodes. Hosting vendor, datacenter, region, hardware, and network profiles remain configurable.

Replicate configuration (routes, host mappings, TLS references, cache/rate-limit/health/security policies, origins, and maintenance state), not cached object contents. Each edge can hold its own local cache. Cache contracts default disabled, require explicit public paths and TTL, and require authentication/personalization/sensitive-response bypass. A future serving adapter must enforce these rules and prohibit caching login, account, payment, booking, admin, and sensitive flows; supplier image licensing still requires review. Contracts alone do not implement an HTTP cache. Release publication events leave room for scoped cache invalidation/warming followed by edge verification.

Network profiles default to WireGuard `10.20.0.0/24` and LAN `192.168.0.0/16`, with both configurable. Stable public ingress and persistent/reconnecting private backhaul should hide Spectrum-to-Starlink origin failover, including CGNAT, without changing public edge IP/DNS. No router changes or tunnel configuration are performed now.

Only implemented UI modules appear as operational navigation. Servers, Provisioning, Network, Edge, and Settings can be added through dedicated routers and pages later. Future Edge telemetry must come from real observations; no regions, nodes, traffic, bandwidth, cache metrics, or health readings are fabricated.

## Source availability

The UI links to `/license` and `/source`. `/source` downloads an allowlisted first-party source archive including application code, tests, Alembic migrations, requirements, and setup/contribution documentation. Runtime databases, logs, virtual environments, credential files, and `.env` are excluded. These endpoints are public so source is available without an administrator token. Operators must package corresponding source for the actual deployed version and all applicable dependency notices when distributing a release. The endpoint caches one source snapshot per worker lifetime, so deploy immutable release directories and restart workers after a release. Repeated requests do not recompress the source archive.

## Security hardening

SQLite database files are created or restricted to owner-only permissions before the engine opens them. New database directories default to owner-only access; operators must also protect existing database directories and backups. HTTP request bodies are bounded to 256 KiB before parsing, including streamed requests. Source archives are cached once per worker. Authentication rejects invalid tokens without accepting non-ASCII header input as an internal error. HTTPS termination, project-scoped report credentials, administrator accounts/roles, and rate limiting still need implementation before production exposure.

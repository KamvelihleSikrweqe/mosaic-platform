# MOSAIC Milestone 1 — Secure Organisation Runtime

**Product direction:** Business Operating System  
**Priority:** Platform foundation  
**Status:** Proposed engineering milestone; implementation not yet complete  
**First proof application:** Supplier Management

## Outcome

An organisation can create and manage an isolated workspace on a shared MOSAIC installation. Every request is authenticated as an individual principal, membership is verified server-side, and tenant boundaries are enforced by both application policy and PostgreSQL. The system has repeatable migrations, automated isolation tests, operational telemetry, and a tested recovery path.

This milestone deliberately does not attempt to deliver the visual application builder or a production workflow engine. Those depend on a trustworthy runtime.

## Current baseline

The current preview has:
- A single shared HTTP Basic credential.
- A caller-supplied `X-Organisation-ID` selector without verified membership.
- Application-level organisation filters, but no PostgreSQL row-level security.
- SQLAlchemy models and an Alembic bootstrap; migration history and upgrade safety must be verified.
- A Render preview using a SQLite URL in the current deployment configuration; durable managed PostgreSQL must be wired and validated before real use.
- No production identity lifecycle, role/permission model, tested backup restoration, or independent security assessment.

It is explicitly not safe for real customer, personal, financial or confidential data.

## Architecture decisions

1. Keep a modular monolith for the control plane until scaling or isolation requirements justify service extraction.
2. Separate the control plane (organisations, principals, memberships, roles, environments, app metadata, deployment intent) from tenant workload execution.
3. Use OIDC/OAuth 2.1 with a standards-based identity provider; validate issuer, audience, signature, expiry and nonce/state where applicable. Never trust browser-provided identity or tenant headers.
4. Resolve tenant context from verified principal + active membership. Require an explicit permission for each operation.
5. Use PostgreSQL as the authoritative production database. Apply tenant RLS using transaction-scoped tenant context, with FORCE ROW LEVEL SECURITY where appropriate; the application DB role must not own tenant tables or bypass RLS.
6. Keep application-level tenant predicates as defence in depth. RLS is not a substitute for correct authorisation.
7. Use Alembic migrations only. Remove production reliance on `Base.metadata.create_all`; test upgrades from the previous released schema and rollback/forward recovery.
8. Treat audit as a separate append-only evidence stream. Record actor, tenant, action, resource, timestamp, correlation ID and outcome; restrict update/delete and plan external retention.
9. Use a managed secrets facility, rotate credentials, and never expose secrets in logs or client bundles.
10. Instrument API, database and background operations with OpenTelemetry-compatible traces, metrics and structured logs.

## Workstreams and acceptance criteria

### A. Identity and organisation membership
- OIDC login with PKCE for browser clients.
- Principal records map to stable identity-provider subject + issuer, not email alone.
- Organisation membership supports owner, admin, builder, operator, auditor and read-only roles.
- Every tenant API resolves membership server-side.
- Disabled users and revoked memberships lose access immediately or within a documented token/session revocation window.
- Tests cover unauthenticated, non-member, revoked member and cross-tenant access.

### B. Tenant isolation and PostgreSQL
- Provision and connect managed PostgreSQL; use TLS and least-privilege runtime credentials.
- Add RLS policies to every tenant-owned table.
- Tenant context is set transaction-locally and cannot leak across pooled connections.
- Runtime DB role cannot bypass RLS or own protected tables.
- Tests attempt cross-tenant reads, inserts, updates and deletes through both API and direct runtime-role SQL.
- Data survives redeploy, restart and service rescheduling.

### C. Schema lifecycle and migrations
- Establish a baseline Alembic revision matching the current schema.
- Verify upgrade from a clean database and from a copy of the existing preview schema.
- CI runs migration upgrade and schema consistency checks.
- Deploys fail closed if migrations fail; application does not serve traffic on an incompatible schema.

### D. Security and operational controls
- Rate limits and request size limits on public/authenticated endpoints.
- Secure headers, CORS allowlist and CSRF protection for cookie-based browser sessions.
- Secrets are injected from a managed secret store and rotated.
- Structured logs redact credentials, tokens and sensitive payloads.
- Health/readiness checks distinguish process health from dependency readiness.
- Dependency and container scanning run in CI.

### E. Backup, restore and observability
- Automated encrypted backups with documented retention.
- Restore drill into an isolated database, with integrity checks.
- Define initial RPO/RTO targets and measure restore time.
- OpenTelemetry traces, metrics and logs with tenant-safe labels (no sensitive payloads).
- Alert on error rate, latency, database saturation, failed migrations and backup failures.

## Definition of done

- Two independently authenticated organisations can use one installation concurrently.
- Automated tests prove tenant isolation for all tenant-owned resources.
- PostgreSQL is authoritative and data persists across redeployments.
- Migrations are repeatable and exercised in CI.
- Backup restoration is demonstrated and documented.
- Security controls and operational runbooks are documented.
- Supplier Management demo works entirely within the secured organisation context.
- No production-readiness or compliance claim is made until independent threat modelling, penetration testing, privacy review and operational readiness review are complete.

## Delivery sequence

1. Inventory current schema, deployment and migration history; capture baseline tests.
2. Provision PostgreSQL and migrate preview data only after backup and restore validation.
3. Implement OIDC principal and organisation membership model.
4. Add policy checks and PostgreSQL RLS.
5. Add CI isolation/migration/security tests.
6. Add observability, backup/restore and incident runbooks.
7. Run a two-organisation acceptance demonstration using fictional data.
8. Only then start the visual application runtime milestone.

## Commercial validation (parallel, non-production)

Interview 10–15 operations leaders and system owners in South Africa. Validate the pain around supplier onboarding and adjacent operations, existing systems, integration constraints, data residency/security requirements, buying authority, budget and willingness to pilot. Do not use employer-confidential information or imply employer endorsement.

Success signal: at least three organisations agree to a structured design-partner discovery/pilot discussion, and at least one confirms a funded pilot path subject to security review.

## Explicit non-goals

- Full visual app builder.
- General-purpose workflow marketplace.
- Arbitrary customer code execution.
- AI agent runtime.
- Kubernetes-based customer workload hosting.
- Compliance certification.
- Processing real regulated or sensitive data in the preview.

These remain downstream capabilities.

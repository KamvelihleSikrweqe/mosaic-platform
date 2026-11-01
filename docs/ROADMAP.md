# Engineering roadmap

## v0.1 — Developer preview
- Organisation creation and selection
- Tenant-scoped metadata object definitions
- Application draft and publish lifecycle
- Declarative workflow definition storage and enablement
- Application-level audit events
- Responsive web console and REST API

## v0.2 — Secure organisation foundation
- PostgreSQL as production database and Alembic migrations
- OIDC/Keycloak integration; verified identity-to-tenant mapping
- RBAC and fine-grained authorisation
- Tenant isolation tests, row-level security and security threat model
- Secrets management, structured logs, metrics and tracing

## v0.3 — Developer experience
- [x] Initial MOSAIC CLI and Python SDK
- Local development environment and project templates
- [x] Versioned application manifest JSON Schema
- Git-backed build/test/release pipeline
- [x] Logical release snapshots for development, staging and production (not infrastructure promotion)

## v0.4 — Application runtime
- Sandboxed extension runtime (WASM or isolated containers after threat review)
- UI component/plugin contract
- API registration, versioning and service-to-service identity
- Event subscriptions and durable workflow orchestration
- Workflow retries, idempotency, compensation and human task inbox

## v0.5 — Studios and marketplace
- [x] Visual page/form builder foundation and component registry
- [x] Versioned application manifests and logical environment release snapshots
- [x] Python SDK and CLI for validate/export/push/release
- Developer workspace and API explorer
- Signed app/connector packages and compatibility checks
- Private organisation catalogues and public marketplace
- Billing metering and tenant quotas

## v0.6 — AI and integrations
- Model gateway and provider abstraction
- RAG and agent lifecycle management
- Tool permissions, approval gates and execution traces
- Connector SDK and initial ERP/accounting integrations
- Evaluation, monitoring and rollback for AI releases

## Release gates
Every release requires automated tests, dependency and container scanning, migration tests, tenant-isolation tests, documentation, rollback procedure and a reviewed threat model for new execution surfaces.

## Next engineering gates after the Studio foundation

- Complete browser end-to-end tests for Studio editing, data bindings and workflow actions.
- Add deployment adapters that provision isolated runtime instances from immutable releases.
- Add environment-scoped configuration/secrets and signed artifacts before any customer-code execution.
- Add rollback and release promotion with explicit approval and audit.
- Harden production identity, PostgreSQL RLS, backups, observability and security testing before onboarding real tenants.

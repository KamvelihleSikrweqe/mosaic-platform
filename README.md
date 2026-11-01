# MOSAIC — Programmable Business Infrastructure

MOSAIC is an open-source project exploring a programmable operating environment for organisations. Each organisation should be able to configure and extend its own applications, data models, workflows, integrations, and AI capabilities while retaining control of its deployment and data.

> **Project status: early developer preview. Not production-ready.** The current prototype is a learning/demo vertical slice. It is not safe to expose to the public internet or use with real business/customer data.

## Product direction

- Organisation workspaces and isolated runtime environments
- Metadata-driven data models and application configuration
- Workflow orchestration and human-in-the-loop operations
- Developer and application studios
- Integration and AI-agent capabilities
- Self-hosted, cloud, and hybrid deployment options

## Prototype

The initial prototype source package is available from the project maintainer while the repository source import is being completed:

- FastAPI backend
- SQLite development database
- Browser-based workspace UI
- Organisation, data-object, application, workflow, and audit APIs
- Docker Compose local preview

## Security notice

The prototype contains deliberately simplified demo authentication and organisation selection. It does **not** provide verified user identity, secure tenant authorisation, production-grade secrets handling, or a hardened deployment configuration. Do not deploy it publicly, connect real customer data, or treat organisation IDs as an access-control boundary.

Before any shared deployment, the project needs OIDC-based authentication, server-enforced tenant membership and authorisation, secure configuration, database migrations/backups, rate limiting, observability, and a security review.

## Development principles

1. Build on proven open-source infrastructure where practical.
2. Keep the core modular, API-first, and portable.
3. Make tenant isolation and auditability foundational.
4. Prefer declarative configuration over arbitrary code execution.
5. Design for self-hosting and data ownership.

## License

The source package's current license and all third-party dependency licenses must be reviewed before a formal public release. No production or enterprise-readiness claim is made by this repository.

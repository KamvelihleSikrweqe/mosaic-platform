# MOSAIC — Programmable Business Infrastructure

MOSAIC is an open-source project exploring a programmable operating environment for organisations. Each organisation can configure its own applications, data models, workflows, integrations and AI capabilities while retaining control of deployment and data.

> **Status: v0.1.0 early developer preview. Runnable, but not production-ready.** Do not expose it to the public internet or use real customer, personal, financial or confidential company data.

## What works in this preview

- Create and select organisation workspaces.
- Define organisation-scoped metadata/data objects with JSON Schema.
- Create applications with JSON configuration and publish a new version.
- Store declarative workflow definitions using a restricted step vocabulary.
- Record application-level audit events.
- Use a responsive browser UI, REST API and interactive OpenAPI docs.

Workflow definitions are stored; they are not executed by a durable workflow engine. The audit log is not tamper-proof evidence.

## Run locally

Requires Python 3.11+ or Docker.

### Docker Compose

The Compose configuration binds to loopback only (127.0.0.1) so the demo is not exposed to other machines on your network.

~~~bash
docker compose up --build
~~~

Open http://localhost:8000 and API docs at http://localhost:8000/docs.

### Python

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn mosaic.main:app --reload
~~~

Open http://localhost:8000.

### Tests

~~~bash
pip install -r requirements-dev.txt
pytest -q
~~~

## API quick start

The local demo accepts the development bearer token mosaic-local-demo. This is intentionally not secure authentication. Organisation-scoped endpoints use X-Organisation-ID as a demo workspace selector only.

~~~bash
curl -X POST http://localhost:8000/api/v1/organisations \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer mosaic-local-demo' \
  -d '{"name":"Example Company","slug":"example-company"}'
~~~

Use the returned organisation ID in the X-Organisation-ID header for object, application, workflow and audit endpoints.

## Security warning

**Do not deploy this preview publicly or use it with real data.** The local preview has simplified demo authentication; organisation selection trusts a caller-supplied header and is not verified against an authenticated user's tenant membership. The application has no production-grade identity, authorisation, secrets management, rate limiting, tamper-proof audit, backup/restore or disaster-recovery controls. It has not undergone a security review or penetration test.

Before shared deployment, implement and independently test:
1. OIDC authentication and server-side user-to-organisation membership/authorisation.
2. PostgreSQL, schema migrations, row-level security and cross-tenant regression tests.
3. Secret management, secure sessions, CSRF protections, rate limiting and security headers.
4. Durable workflow execution, sandboxed extensions and explicit human approval gates.
5. Audit integrity, backups, restore drills, observability and incident response.
6. Threat modelling, penetration testing and a POPIA/privacy review.

## Architecture direction

The longer-term platform includes an organisation control plane, tenant runtime, developer platform, application/developer/infrastructure/AI studios and a governed marketplace. The current implementation is a small modular monolith; planned capabilities are not represented as completed features.

See the architecture, product vision, roadmap and security policy in the docs and root directory.

## Licence

A formal repository-wide open-source licence is still to be confirmed. Do not assume a licence grant until the maintainer adds and reviews the applicable licence file.

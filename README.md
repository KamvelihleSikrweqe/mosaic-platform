# MOSAIC — Programmable Business Infrastructure

MOSAIC is an open-source project exploring a programmable operating environment for organisations. Each organisation can configure its own applications, data models, workflows, integrations and AI capabilities while retaining control of deployment and data.

> **Status: v0.2.0 controlled developer preview. Not production-ready.** Do not use real customer, personal, financial or confidential company data.

## What works

- Create and select organisation workspaces.
- Define organisation-scoped data objects using validated JSON Schema (Draft 2020-12).
- Create, list, retrieve, update and delete records against those schemas.
- Scope data-object and record queries by the selected organisation.
- Create applications, preview them in a declarative runtime, and manage draft-to-published lifecycle metadata.
- Design applications in MOSAIC Studio using a reusable component palette, data bindings and governed workflow actions.
- Render dashboard, data-list and data-form pages against organisation-scoped data models; create, edit and delete validated business records from the application UI.
- Save versioned manifests and create immutable development, staging and production release snapshots.
- Use the dependency-free Python SDK and `mosaic` CLI to validate, export, push and release application manifests.
- Execute bounded, organisation-scoped workflows with persisted run history, idempotency keys, log steps and human approval gates.
- Record application-level audit events.
- Use a responsive browser UI, REST API and OpenAPI docs.
- Connect to SQLite for local preview or PostgreSQL using psycopg 3.

Workflow runs execute synchronously inside the API process. The first runtime supports bounded `log` and `manual_approval` steps, persisted run state, approval/rejection, run history and idempotency. It is not yet a durable background-worker engine: process crashes, long-running tasks and external side effects require a later worker/Temporal integration. The current runtime is a same-origin preview/hosted shell, not an independently provisioned deployment with a custom domain. Publishing changes lifecycle metadata; it does not create an isolated production deployment. Audit events are not tamper-evident.

## Run locally

Requires Docker Compose or Python 3.11+.

### Docker Compose

Copy `.env.example` to `.env`, replace the Keycloak database and admin password placeholders with unique random values, then start the stack:

~~~bash
cp .env.example .env
docker compose up --build
~~~

Open http://localhost:8000 and select **Sign in**. Keycloak administration is available at http://localhost:8080/admin. Create users there; enable a verified email address for users who need to accept organisation invitations. Both services bind to loopback only.

### Python

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MOSAIC_PREVIEW_USERNAME=owner
export MOSAIC_PREVIEW_PASSWORD='replace-with-a-long-random-local-secret'
uvicorn mosaic.main:app --reload
~~~

### Tests

~~~bash
pip install -r requirements-dev.txt
pytest -q
~~~

## API quick start

~~~bash
export MOSAIC_PREVIEW_PASSWORD='replace-with-a-long-random-local-secret'
AUTH=$(printf 'owner:%s' "$MOSAIC_PREVIEW_PASSWORD" | base64)
curl -X POST http://localhost:8000/api/v1/organisations \
  -H "Authorization: Basic $AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Example Company","slug":"example-company"}'
~~~

Use the returned organisation ID as the `X-Organisation-ID` header. Create a data object, then create records at `POST /api/v1/objects/{object_id}/records` with a JSON body such as `{"data":{"name":"Example Supplier"}}`.


## Application Studio and releases

Open an application and choose **Design** to launch MOSAIC Studio. Add pages and components, bind data components to organisation data models, and attach buttons to enabled workflows. Save uses optimistic version checking. The current component registry includes headings, text, metrics, data tables, data forms and governed workflow buttons.

Application manifests use `schemaVersion: "1.0"`. A page can contain up to 100 components; an application can contain up to 30 pages. Only registered component types and the allow-listed `workflow.run` action are accepted. The runtime never evaluates manifest-supplied JavaScript or HTML.

The release API stores immutable manifest snapshots for `development`, `staging` and `production`. A production release updates application lifecycle status to published. These are logical release records within the existing MOSAIC service; they do **not** provision isolated compute, a custom domain, independent infrastructure or automated rollback. Environment-specific secrets/configuration, artifact signing, deployment orchestration and rollback are future work.

### Python SDK and CLI

Install from the repository root with `pip install .`. Configure one of:
- `MOSAIC_TOKEN` for a bearer access token; or
- `MOSAIC_USERNAME` and `MOSAIC_PASSWORD` for the single-operator preview Basic Auth.

Also set `MOSAIC_URL` (defaults to `http://localhost:8000`) and `MOSAIC_ORG_ID`.

```bash
mosaic validate app.json
mosaic export --app-id APP_ID --output app.json
mosaic push --app-id APP_ID --file app.json
mosaic release --app-id APP_ID --environment staging
```

The CLI is a developer utility, not a replacement for authenticated server-side policy checks.

## Health endpoints

- `/health/live`: process liveness.
- `/health/ready`: database connectivity readiness.

## Security and production status

**This remains a restricted developer preview, not a production or multi-customer platform.** The Docker Compose development stack now uses Keycloak OIDC, verified server-side organisation membership and role checks. Its SQLite runtime does not enforce PostgreSQL RLS. The standalone Python preview can still use a single shared Basic Auth credential; that mode is not suitable for multi-user access. Do not use real personal, financial, customer or confidential company data. Production still requires PostgreSQL RLS integration tests with the actual non-superuser runtime role, secure headers, rate limiting, secrets management, tamper-evident audit, backups/restore drills, observability, incident response, threat modelling and independent penetration testing.

The current SQLAlchemy `create_all` bootstrap creates missing tables but does not migrate existing schemas. A versioned migration system is required before production rollout. Do not treat a successful deployment as a production-readiness certification.

## Architecture direction

The longer-term platform includes an organisation control plane, tenant runtime, developer platform, application/developer/infrastructure/AI studios and a governed marketplace. The current implementation is a modular-monolith preview; planned capabilities are not represented as completed features.

See `docs/ARCHITECTURE.md`, the product vision, roadmap and `SECURITY.md`.

## Licence

A formal repository-wide open-source licence is still to be confirmed. Do not assume a licence grant until the maintainer adds and reviews the applicable licence file.


## Multi-user login with Keycloak (local self-hosted)

The Compose stack can run a local Keycloak identity provider and the MOSAIC browser client. This is a **local development configuration**, not a hardened internet-facing identity deployment.

1. Copy `.env.example` to `.env` and replace all three Keycloak password placeholders with unique random secrets.
2. Import the supplied `keycloak/realm-mosaic.json` realm automatically when Keycloak starts.
3. Run `docker compose up --build`.
4. Open `http://localhost:8000`. Select **Sign in** and authenticate using a user you create in the Keycloak admin console at `http://localhost:8080/admin`.
5. Create an organisation. Your Keycloak issuer+subject identity becomes its owner. Invite colleagues using the invitation API once email verification is enabled for their accounts.

The browser uses Authorization Code + PKCE (S256), validates the OAuth state and OIDC nonce, and keeps short-lived access/refresh tokens in tab-scoped session storage. This reduces persistence beyond the current tab but remains exposed to same-origin script compromise; a production deployment should move token handling to a backend-for-frontend with secure, HttpOnly, SameSite cookies. The browser client is public and has no client secret. The API validates access-token signature, issuer and audience using Keycloak JWKS.

The realm includes a protocol mapper that adds the `mosaic-api` audience to access tokens. The local Keycloak URL and redirect URI are configured for localhost only. For a real deployment, use HTTPS, a stable public issuer, production Keycloak mode behind a trusted reverse proxy, a managed/durable Keycloak database, strict redirect URI and web-origin allowlists, secure secrets, MFA and account recovery policies. Update `OIDC_ISSUER`, `OIDC_JWKS_URL`, `OIDC_REDIRECT_URI`, and the realm client's redirect URI/web origin together. The issuer claim must match `OIDC_ISSUER` exactly.

Do not enable OIDC on the existing Render preview until its issuer, audience, JWKS URL, client ID, HTTPS redirect URI and durable PostgreSQL runtime are configured and tested. OIDC mode intentionally disables the shared Basic preview login.

# Security policy

## Current status

MOSAIC remains a controlled developer preview, not production software. The current hosted preview uses a single shared HTTP Basic credential and does not have OIDC configured. Do not use real personal, financial, customer or confidential company data.

The secure-organisation-runtime branch adds an OIDC JWT verification path, server-side organisation membership checks, owner assignment on organisation creation, basic role-based write restrictions, and PostgreSQL row-level security migration policies. These changes are not live until reviewed, merged, configured and deployed. SQLite does not enforce PostgreSQL RLS.

## Multi-user identity configuration

Set all three variables together:
- `OIDC_ISSUER`: exact issuer URL expected in tokens.
- `OIDC_AUDIENCE`: API audience expected in access tokens.
- `OIDC_JWKS_URL`: trusted HTTPS JWKS endpoint for the issuer.

MOSAIC verifies JWT signatures against JWKS, restricts algorithms to RS256/ES256, validates issuer and audience, and requires exp/iat/sub/iss/aud. The stable internal user key is a SHA-256 digest of issuer plus subject; email is not used as an identity key.

When any OIDC variable is set, Basic preview authentication is disabled. Incomplete OIDC configuration fails closed. An OIDC provider and a browser PKCE login flow still need to be configured/implemented before the hosted web UI can be used as a multi-user product. Do not enable OIDC on the current Render service until that flow and provider configuration are ready.

## Tenant isolation

On PostgreSQL, migration `0002_org_membership_rls` enables and forces row-level security on organisation-owned data tables and membership metadata. Each authenticated tenant request verifies membership before setting transaction-local tenant context. Keep the runtime database role non-superuser and without BYPASSRLS. Prefer a separate migration owner and least-privilege runtime role before production.

SQLite is for local development/preview only and does not provide equivalent row-level security. Application-level membership checks remain necessary even when RLS is enabled.

## Reporting a vulnerability

Do not publish exploit details in a public issue. Use GitHub's private vulnerability reporting feature if enabled, or request a private reporting channel from the maintainer.

## Required before production use

- Browser OIDC Authorization Code + PKCE login, logout, session renewal and CSRF-safe token handling.
- MFA policy and identity-provider configuration.
- Invitation lifecycle, membership revocation and full role/permission administration.
- Separate migration owner and least-privilege runtime database role; verify no BYPASSRLS.
- PostgreSQL integration tests that prove RLS blocks cross-tenant reads and writes using the actual runtime role.
- Versioned migration upgrade and rollback/recovery testing against a copy of the current database.
- Secret management, dependency/container scanning, secure headers, CORS allowlist and rate limiting.
- Durable workflow execution, sandboxed extensions and human approval gates.
- Tamper-evident audit, observability, incident response and disaster recovery.
- Threat modelling, independent penetration testing and privacy/legal review.

No compliance or security certification is claimed.

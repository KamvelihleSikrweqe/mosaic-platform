# Identity and tenant context

## Identity contract

MOSAIC accepts OIDC access tokens in the HTTP Authorization Bearer header. Configure:
- `OIDC_ISSUER`
- `OIDC_AUDIENCE`
- `OIDC_JWKS_URL`

All three must be present. Setting only part of the configuration makes the API fail closed. The API verifies token signatures against the JWKS endpoint, permits RS256 and ES256 only, validates issuer and audience, and requires expiry, issued-at, subject, issuer and audience claims.

The internal user key is a SHA-256 digest of the exact issuer and subject pair. Do not use email as the stable identity key. The identity provider must guarantee globally stable subject identifiers within an issuer.

## Organisation lifecycle

An authenticated principal creates an organisation and becomes its owner. Organisation listing and `GET /api/v1/me` return only memberships belonging to that principal. Tenant APIs require `X-Organisation-ID`, then resolve the membership server-side. Unknown and non-member organisations both return 404 to avoid confirming another tenant's existence.

Initial roles:
- `owner`, `admin`, `builder`, `operator`: read and write access to the current API surface.
- Other roles (including `member` and `auditor`): read-only access to the current API surface.

This is an initial coarse-grained role model, not the final fine-grained permission engine. Membership invitation, revocation, role administration and separation-of-duties policies remain to be implemented.

## PostgreSQL isolation

Migration `0002_org_membership_rls` creates the membership table and applies RLS to organisations, memberships, data objects, records, applications, workflows and audit events. The API sets user and tenant identifiers using transaction-local PostgreSQL settings, after verifying membership.

The runtime database role must not be a superuser or have BYPASSRLS. For production, use a separate migration-owner credential and a least-privilege application role. Confirm role attributes and run cross-tenant SQL tests with the exact application role. Never treat SQLite tests as proof of PostgreSQL isolation.

## Browser integration

The current browser UI uses the controlled preview gate. A real multi-user browser client still needs OIDC Authorization Code with PKCE, callback validation, secure token storage/renewal, logout and CSRF-safe session handling. Do not enable OIDC on the hosted UI until that integration and identity provider are configured.

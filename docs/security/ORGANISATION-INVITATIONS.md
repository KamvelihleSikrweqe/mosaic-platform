# Organisation invitation lifecycle

MOSAIC supports OIDC-authenticated organisation membership management.

## Endpoints

All endpoints require a verified OIDC bearer access token. Preview Basic authentication is deliberately not sufficient.

- `POST /api/v1/organisations/{org_id}/invitations` — owner/admin creates an invitation. JSON: `{"email":"person@example.com","role":"builder","expires_in_days":7}`. Roles accepted: member, operator, builder, admin. Only an owner may invite or promote an admin.
- `GET /api/v1/organisations/{org_id}/invitations` — list outstanding invitations (including expiry status).
- `DELETE /api/v1/organisations/{org_id}/invitations/{invitation_id}` — revoke a pending invitation.
- `POST /api/v1/invitations/accept` — accept with JSON `{"token":"<acceptance_token>"}`. The OIDC token must contain an email claim and `email_verified: true`; the verified email must match the invitation.
- `GET /api/v1/organisations/{org_id}/members` — list members (owner/admin).
- `PATCH /api/v1/organisations/{org_id}/members/{user_id}` — change role with JSON `{"role":"operator"}`.
- `DELETE /api/v1/organisations/{org_id}/members/{user_id}` — revoke membership.

## Token handling

The API generates a high-entropy random token containing the organisation identifier and a random secret. Only a SHA-256 hash is persisted. The raw token is returned once by the create endpoint and is not stored or included in audit events. Deliver it only through a trusted channel; email delivery is not configured yet. Tokens expire after 1–30 days (7 by default), are single-use, and can be revoked.

## Identity and roles

Membership identity is the stable issuer+subject-derived user ID, not the email address. Email is used only to bind an invitation to a verified identity at acceptance. Roles are owner, admin, builder, operator, and member. Owners cannot be removed or demoted through these endpoints. Admins cannot grant admin privileges or modify another admin; only an owner can do so.

## Deployment status and limitations

The invitation table has a tenant-scoped PostgreSQL RLS policy and an Alembic migration. The current hosted preview still uses Basic authentication and SQLite, so invitation operations intentionally return 403 there. A configured OIDC provider and browser Authorization Code + PKCE login are still required before end users can use this flow. PostgreSQL RLS must be integration-tested with a non-superuser, non-BYPASSRLS runtime database role before production use. Invitation email delivery, owner transfer, and session revocation are not implemented.

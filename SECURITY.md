# Security policy

## Current status
MOSAIC is an early developer preview and is not suitable for production, public deployment, or real personal, financial, or customer data. The prototype has simplified demo authentication and does not yet enforce verified tenant membership. Treat it as untrusted experimental software.

## Reporting a vulnerability
Do not publish exploit details in a public issue. Use GitHub's private vulnerability reporting feature if enabled, or request a private reporting channel from the maintainer.

## Security priorities
- OIDC authentication and server-side tenant membership checks
- Explicit authorisation policies and least privilege
- PostgreSQL row-level security and cross-tenant regression tests
- Secret management, dependency/container scanning and secure defaults
- Audit integrity, backup/restore and incident response procedures

No compliance or security certification is claimed.

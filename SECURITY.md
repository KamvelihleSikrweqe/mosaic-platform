# Security policy

## Current status

MOSAIC is a controlled developer preview, not production software. It uses a single shared HTTP Basic credential and a caller-supplied organisation selector. It does not yet provide enterprise identity, verified tenant membership, row-level security, tamper-evident audit or a completed independent security assessment. Do not use real personal, financial, customer or confidential company data.

## Reporting a vulnerability

Do not publish exploit details in a public issue. Use GitHub's private vulnerability reporting feature if enabled, or request a private reporting channel from the maintainer.

## Required before production use

- OIDC authentication, MFA integration, individual identities and server-side tenant membership checks.
- Explicit authorisation policies, least privilege and separation of duties.
- PostgreSQL row-level security and automated cross-tenant regression tests.
- Versioned schema migrations and tested backup/restore.
- Secret management, dependency/container scanning, secure headers and rate limiting.
- Durable workflow execution, sandboxed extensions and human approval gates.
- Tamper-evident audit, observability, incident response and disaster recovery.
- Threat modelling, independent penetration testing and privacy/legal review.

No compliance or security certification is claimed.

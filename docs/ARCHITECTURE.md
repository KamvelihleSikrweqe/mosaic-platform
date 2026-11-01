# Architecture specification — initial direction

## Control plane vs data plane
The control plane manages organisations, users, environments, policy, app catalogue, deployment intent and billing. Organisation workloads execute in a data plane that can be shared with strong isolation or dedicated per customer. Regulated customers must be able to run a dedicated or self-hosted data plane.

## Trust boundaries
- Browser and developer CLI are untrusted clients.
- API gateway validates identity and resolves tenant membership from signed identity claims.
- Control plane provisions resources but should not inspect tenant payloads by default.
- Runtime workers execute only signed, policy-approved packages in isolated sandboxes.
- External connectors receive narrowly scoped credentials from a secrets manager.
- Audit exports are append-only, integrity-protected and independently retained.

## Planned logical services
Identity and access, organisation registry, metadata registry, application catalogue, build/release controller, application runtime, workflow orchestrator, event router, connector runtime, policy decision point, audit/evidence and usage metering.

The first implementation should remain a modular monolith. Split services only when scale, isolation, ownership or deployment requirements justify it.

## Data model direction
Every tenant-owned record carries an organisation identifier. Production database access must enforce tenant boundaries server-side, ideally with PostgreSQL row-level security alongside application checks. Never trust an organisation identifier supplied by a browser without validating membership from verified identity claims.

## Extensibility
Use versioned manifests and stable contracts. Extension types include UI modules, workflow actions, connectors, data adapters and app packages. Require package signatures, publisher identity, declared permissions, compatibility metadata, resource limits and revocation support.

## Execution safety
Do not run customer code in the control plane. For custom code, use WASM or ephemeral isolated containers with no ambient credentials, strict CPU/memory/time limits, outbound network policy, filesystem isolation and per-execution identity. Start with declarative workflows and a small allow-listed action set.

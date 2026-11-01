# Application deployment lifecycle

## Current implementation

MOSAIC now stores immutable application releases and tenant-scoped deployment plans.

- A deployment plan references a ready release in the same organisation, application and environment.
- The provider adapter computes a deterministic SHA-256 digest from the canonical JSON manifest.
- The initial Docker adapter is a planning adapter only. It does not connect to a Docker daemon, provision compute, execute customer code, expose a URL or claim health.
- Studio can create and inspect deployment plans.
- A release can be promoted to another logical environment by copying its immutable manifest into a new release snapshot.
- Rollback creates a new release snapshot from a selected historical release. Existing release history is never rewritten.
- All promotion and rollback actions are tenant-scoped and audited.

## API

Create a plan:

~~~http
POST /api/v1/apps/{app_id}/deployments
X-Organisation-ID: {org_id}
Content-Type: application/json

{
  "release_id": "ready-release-uuid",
  "environment": "staging",
  "provider": "docker",
  "target": "local"
}
~~~

Promote a release:

~~~http
POST /api/v1/apps/{app_id}/promotions

{
  "source_release_id": "ready-release-uuid",
  "target_environment": "production"
}
~~~

Create a rollback snapshot:

~~~http
POST /api/v1/apps/{app_id}/environments/production/rollback

{
  "source_release_id": "previous-release-uuid",
  "target_environment": "production"
}
~~~

Rollback is deliberately append-only: it creates a new release version using the historical manifest. It does not rewrite a release or automatically switch a running workload.

## Provider worker boundary

A future provider worker must be separately deployed and authenticated. It must claim deployment jobs idempotently, verify the release digest, apply tenant/environment policy, fetch scoped secrets from a secret manager, provision an isolated declarative runtime, run readiness checks, and report signed status updates. Never expose the control-plane database or broad credentials to tenant workloads. Do not execute manifest-supplied HTML, JavaScript, Python or shell.

## Production prerequisites

Independent application URLs, actual container provisioning, custom domains, TLS, runtime health checks, automatic environment promotion, traffic switching, deployment rollback, per-environment secrets, signed artifacts, worker queue, quotas, and operational monitoring are not implemented. The current Render Free service is only the MOSAIC control-plane preview and is not a customer workload hosting target.

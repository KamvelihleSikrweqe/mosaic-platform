# MOSAIC Workflow Runtime

MOSAIC can execute a deliberately small, auditable workflow subset without an external orchestration service.

## Supported steps

- `log`: append a timestamped execution result.
- `manual_approval`: pause the run until an authorised organisation operator submits an approval or rejection.

Definitions are limited to 50 steps. Arbitrary code execution and outbound HTTP execution are intentionally not supported by this first runtime.

## API

All endpoints require the normal MOSAIC authentication and an `X-Organisation-ID` header.

1. Create a workflow with `POST /api/v1/workflows` and a `definition.steps` array.
2. Enable it with `POST /api/v1/workflows/{workflow_id}/enable`.
3. Start it with `POST /api/v1/workflows/{workflow_id}/runs`:

```json
{
  "input": {"supplier_id": "sup-123"},
  "idempotency_key": "supplier-123-onboarding"
}
```

4. Inspect a run with `GET /api/v1/workflow-runs/{run_id}`, or list history with `GET /api/v1/workflows/{workflow_id}/runs`.
5. When a run is `waiting_approval`, submit a decision:

```json
{"approved": true, "comment": "Supplier documents verified"}
```

to `POST /api/v1/workflow-runs/{run_id}/approval`.

A rejected approval ends the run in `failed`. An approved step resumes execution from the following step. Reusing an idempotency key within the same organisation returns the existing run for that workflow.

## Run states

- `running`: the runtime is advancing steps.
- `waiting_approval`: execution is paused for a human decision.
- `succeeded`: all steps completed.
- `failed`: execution stopped after a rejection or unsupported step.

Every run and step result is persisted. Workflow runs are organisation-scoped and protected by PostgreSQL row-level security when PostgreSQL is used. Audit events are written for starts, approval waits, completion and rejection.

## Current execution model and limitations

The initial runtime executes synchronously inside the API request. It is suitable for short, deterministic steps and local/self-hosted evaluation, not long-running or high-volume production workloads. There is no background worker, durable queue, retry scheduler, timeout management, parallel branches, event trigger system, external connector execution, or exactly-once guarantee across process crashes yet. The idempotency key prevents ordinary client retries from creating duplicate runs, but concurrent duplicate requests still need a database-level conflict recovery path.

Before production use, move step execution to a durable worker/queue (for example Temporal or a transactional outbox plus worker), add optimistic locking/lease ownership, retries and deadlines, and integration-test RLS with a non-superuser PostgreSQL runtime role.

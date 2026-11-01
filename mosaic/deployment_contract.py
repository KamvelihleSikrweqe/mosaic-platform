"""Safe deployment planning contracts for declarative MOSAIC applications.

This module deliberately creates plans only. It does not execute tenant code or
provision infrastructure; concrete providers must implement the adapter protocol.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class DeploymentPlan:
    provider: str
    target: str
    runtime_kind: str
    artifact_digest: str
    manifest: dict[str, Any]
    restrictions: tuple[str, ...]


class DeploymentAdapter(Protocol):
    provider: str

    def plan(self, *, target: str, manifest: dict[str, Any]) -> DeploymentPlan:
        """Validate and describe a deployment without executing application code."""
        ...


class DeclarativeDockerAdapter:
    """Build a provider-neutral plan for a future isolated Docker runtime."""

    provider = "docker"

    def plan(self, *, target: str, manifest: dict[str, Any]) -> DeploymentPlan:
        if not target or len(target) > 120:
            raise ValueError("Deployment target must be between 1 and 120 characters")
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return DeploymentPlan(
            provider=self.provider,
            target=target,
            runtime_kind="mosaic-declarative",
            artifact_digest=f"sha256:{digest}",
            manifest=manifest,
            restrictions=(
                "No arbitrary HTML, JavaScript, Python, shell, or customer code execution",
                "Only registered MOSAIC components and allow-listed actions are supported",
                "Secrets are not embedded in the application manifest or deployment plan",
                "A provider worker and isolated runtime must be configured before provisioning",
            ),
        )


ADAPTERS: dict[str, DeploymentAdapter] = {
    "docker": DeclarativeDockerAdapter(),
}


def create_deployment_plan(provider: str, target: str, manifest: dict[str, Any]) -> DeploymentPlan:
    adapter = ADAPTERS.get(provider)
    if adapter is None:
        raise ValueError(f"Unsupported deployment provider: {provider}")
    return adapter.plan(target=target, manifest=manifest)

import base64
import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///./test_mosaic.db"
os.environ["MOSAIC_PREVIEW_USERNAME"] = "owner"
os.environ["MOSAIC_PREVIEW_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient
from mosaic.main import app
from mosaic.db import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)
AUTH = {"Authorization": "Basic " + base64.b64encode(b"owner:test-password").decode()}


def create_org(name):
    response = client.post("/api/v1/organisations", json={
        "name": name, "slug": "deploy-" + uuid4().hex[:12]
    }, headers=AUTH)
    assert response.status_code == 201, response.text
    return {**AUTH, "X-Organisation-ID": response.json()["id"]}


def test_release_promotion_and_rollback_preserve_immutable_history_and_tenant_scope():
    headers = create_org("Release lifecycle")
    other_headers = create_org("Other release lifecycle")
    created = client.post("/api/v1/apps", json={
        "name": "Lifecycle app",
        "config": {"schemaVersion": "1.0", "pages": [{
            "id": "home", "name": "Home", "type": "dashboard",
            "components": [{"id": "title", "type": "heading", "props": {"text": "Version one"}}],
        }]},
    }, headers=headers)
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    v1 = client.post(f"/api/v1/apps/{app_id}/releases", json={"environment": "development"}, headers=headers)
    assert v1.status_code == 201, v1.text
    v2 = client.put(f"/api/v1/apps/{app_id}", json={
        "expected_version": v1.json()["version"],
        "config": {"schemaVersion": "1.0", "pages": [{
            "id": "home", "name": "Home", "type": "dashboard",
            "components": [{"id": "title", "type": "heading", "props": {"text": "Version two"}}],
        }]},
    }, headers=headers)
    assert v2.status_code == 200, v2.text
    v2release = client.post(f"/api/v1/apps/{app_id}/releases", json={"environment": "development"}, headers=headers)
    assert v2release.status_code == 201, v2release.text

    promoted = client.post(f"/api/v1/apps/{app_id}/promotions", json={
        "source_release_id": v2release.json()["id"], "target_environment": "staging"
    }, headers=headers)
    assert promoted.status_code == 201, promoted.text
    assert promoted.json()["environment"] == "staging"

    # Production can only be promoted from a ready release; the resulting snapshot
    # is immutable and can later be used as a rollback source.
    production = client.post(f"/api/v1/apps/{app_id}/promotions", json={
        "source_release_id": promoted.json()["id"], "target_environment": "production"
    }, headers=headers)
    assert production.status_code == 201, production.text

    # Create a newer production snapshot to simulate a bad release.
    update = client.put(f"/api/v1/apps/{app_id}", json={
        "expected_version": production.json()["version"],
        "config": {"schemaVersion": "1.0", "pages": [{
            "id": "home", "name": "Home", "type": "dashboard",
            "components": [{"id": "title", "type": "heading", "props": {"text": "Bad release"}}],
        }]},
    }, headers=headers)
    assert update.status_code == 200
    bad = client.post(f"/api/v1/apps/{app_id}/releases", json={"environment": "production"}, headers=headers)
    assert bad.status_code == 201

    rollback = client.post(f"/api/v1/apps/{app_id}/environments/production/rollback", json={
        "source_release_id": production.json()["id"], "target_environment": "production"
    }, headers=headers)
    assert rollback.status_code == 201, rollback.text
    assert rollback.json()["rolled_back_from"] == bad.json()["id"]

    releases = client.get(f"/api/v1/apps/{app_id}/releases", headers=headers).json()
    rollback_snapshot = client.get(
        f"/api/v1/apps/{app_id}/releases/{rollback.json()['id']}", headers=headers
    ).json()
    assert rollback_snapshot["manifest"]["pages"][0]["components"][0]["props"]["text"] == "Version two"
    assert any(item["id"] == bad.json()["id"] for item in releases)
    assert client.post(f"/api/v1/apps/{app_id}/promotions", json={
        "source_release_id": v2release.json()["id"], "target_environment": "staging"
    }, headers=other_headers).status_code == 404


def test_release_promotion_rejects_same_environment_and_rollback_current_release():
    headers = create_org("Promotion validation")
    created = client.post("/api/v1/apps", json={"name": "Validation app", "config": {"pages": []}}, headers=headers)
    app_id = created.json()["id"]
    release = client.post(f"/api/v1/apps/{app_id}/releases", json={"environment": "staging"}, headers=headers)
    assert release.status_code == 201
    same = client.post(f"/api/v1/apps/{app_id}/promotions", json={
        "source_release_id": release.json()["id"], "target_environment": "staging"
    }, headers=headers)
    assert same.status_code == 409
    current = client.post(f"/api/v1/apps/{app_id}/environments/staging/rollback", json={
        "source_release_id": release.json()["id"], "target_environment": "staging"
    }, headers=headers)
    assert current.status_code == 409

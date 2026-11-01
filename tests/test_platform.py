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
H = {"Authorization": "Basic " + base64.b64encode(b"owner:test-password").decode()}


def org(name, slug):
    return client.post(
        "/api/v1/organisations",
        json={"name": name, "slug": slug + "-" + uuid4().hex[:8]},
        headers=H,
    )


def test_tenant_isolation_and_app_lifecycle():
    a = org("Test Org A", "test-org-a")
    assert a.status_code == 201, a.text
    b = org("Test Org B", "test-org-b")
    assert b.status_code == 201, b.text
    aid, bid = a.json()["id"], b.json()["id"]
    ha, hb = {**H, "X-Organisation-ID": aid}, {**H, "X-Organisation-ID": bid}
    obj = client.post(
        "/api/v1/objects",
        json={"key": "supplier", "label": "Supplier", "schema": {"type": "object"}},
        headers=ha,
    )
    assert obj.status_code == 201
    assert client.get("/api/v1/objects", headers=hb).json() == []
    appres = client.post(
        "/api/v1/apps",
        json={"name": "Supplier Portal", "config": {"pages": []}},
        headers=ha,
    )
    assert appres.status_code == 201
    appid = appres.json()["id"]
    assert client.post(f"/api/v1/apps/{appid}/publish", headers=hb).status_code == 404
    published = client.post(f"/api/v1/apps/{appid}/publish", headers=ha)
    assert published.json()["status"] == "published"


def test_workflow_definition_validation():
    a = org("Workflow Org", "workflow-org")
    assert a.status_code == 201
    h = {**H, "X-Organisation-ID": a.json()["id"]}
    good = client.post(
        "/api/v1/workflows",
        json={"name": "Approval", "definition": {"steps": [{"type": "manual_approval"}]}},
        headers=h,
    )
    assert good.status_code == 201
    bad = client.post(
        "/api/v1/workflows",
        json={"name": "Unsafe", "definition": {"steps": [{"type": "python", "code": "import os"}]}},
        headers=h,
    )
    assert bad.status_code == 422


def test_preview_requires_basic_authentication():
    assert client.get("/").status_code == 401
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    bad = {"Authorization": "Basic " + base64.b64encode(b"owner:wrong").decode()}
    assert client.get("/api/v1/organisations", headers=bad).status_code == 401


def test_schema_validated_record_crud_and_tenant_isolation():
    a, b = org("Records Org A", "records-a"), org("Records Org B", "records-b")
    ha = {**H, "X-Organisation-ID": a.json()["id"]}
    hb = {**H, "X-Organisation-ID": b.json()["id"]}
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "email": {"type": "string", "format": "email"}},
        "required": ["name", "email"],
        "additionalProperties": False,
    }
    created_object = client.post(
        "/api/v1/objects",
        json={"key": "supplier", "label": "Supplier", "schema": schema},
        headers=ha,
    )
    assert created_object.status_code == 201, created_object.text
    object_id = created_object.json()["id"]

    invalid = client.post(
        f"/api/v1/objects/{object_id}/records",
        json={"data": {"name": "Acme", "email": "not-an-email"}},
        headers=ha,
    )
    assert invalid.status_code == 422

    created = client.post(
        f"/api/v1/objects/{object_id}/records",
        json={"data": {"name": "Acme Ltd", "email": "ops@acme.example"}},
        headers=ha,
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    assert client.get(f"/api/v1/records/{record_id}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/objects/{object_id}/records", headers=hb).status_code == 404

    updated = client.put(
        f"/api/v1/records/{record_id}",
        json={"data": {"name": "Acme Group", "email": "team@acme.example"}},
        headers=ha,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Acme Group"
    assert client.get(f"/api/v1/objects/{object_id}/records", headers=ha).json()[0]["id"] == record_id
    assert client.delete(f"/api/v1/records/{record_id}", headers=ha).status_code == 204
    assert client.get(f"/api/v1/records/{record_id}", headers=ha).status_code == 404


def test_supplier_demo_seed_is_idempotent():
    first = client.post("/api/v1/demo/supplier-onboarding", headers=H)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["organisation"]["slug"] == "mosaic-demo"
    assert result["data_object"]["key"] == "supplier"
    assert result["application"]["status"] == "draft"
    assert result["workflow"]["enabled"] is False
    assert result["records_created"] == 2

    second = client.post("/api/v1/demo/supplier-onboarding", headers=H)
    assert second.status_code == 200, second.text
    assert second.json()["organisation"]["id"] == result["organisation"]["id"]
    assert second.json()["records_created"] == 0
    headers = {**H, "X-Organisation-ID": result["organisation"]["id"]}
    records = client.get(
        f"/api/v1/objects/{result['data_object']['id']}/records", headers=headers
    )
    assert records.status_code == 200
    assert len(records.json()) == 2

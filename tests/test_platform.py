import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///./test_mosaic.db"
os.environ["MOSAIC_ALLOW_INSECURE_DEMO"] = "true"

from fastapi.testclient import TestClient
from mosaic.main import app

client = TestClient(app)
H = {"Authorization": "Bearer mosaic-local-demo"}

def org(name, slug):
    return client.post("/api/v1/organisations", json={"name": name, "slug": slug + "-" + uuid4().hex[:8]}, headers=H)

def test_tenant_isolation_and_app_lifecycle():
    a = org("Test Org A", "test-org-a")
    assert a.status_code == 201, a.text
    b = org("Test Org B", "test-org-b")
    assert b.status_code == 201, b.text
    aid = a.json()["id"]
    bid = b.json()["id"]
    ha = {**H, "X-Organisation-ID": aid}
    hb = {**H, "X-Organisation-ID": bid}
    obj = client.post("/api/v1/objects", json={"key": "supplier", "label": "Supplier", "schema": {"type": "object"}}, headers=ha)
    assert obj.status_code == 201
    assert client.get("/api/v1/objects", headers=hb).json() == []
    appres = client.post("/api/v1/apps", json={"name": "Supplier Portal", "config": {"pages": []}}, headers=ha)
    assert appres.status_code == 201
    appid = appres.json()["id"]
    assert client.post(f"/api/v1/apps/{appid}/publish", headers=hb).status_code == 404
    published = client.post(f"/api/v1/apps/{appid}/publish", headers=ha)
    assert published.json()["status"] == "published"

def test_workflow_definition_validation():
    a = org("Workflow Org", "workflow-org")
    assert a.status_code == 201
    h = {**H, "X-Organisation-ID": a.json()["id"]}
    good = client.post("/api/v1/workflows", json={"name": "Approval", "definition": {"steps": [{"type": "manual_approval"}]}}, headers=h)
    assert good.status_code == 201
    bad = client.post("/api/v1/workflows", json={"name": "Unsafe", "definition": {"steps": [{"type": "python", "code": "import os"}]}}, headers=h)
    assert bad.status_code == 422

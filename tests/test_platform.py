import base64
import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite:///./test_mosaic.db"
os.environ["MOSAIC_PREVIEW_USERNAME"] = "owner"
os.environ["MOSAIC_PREVIEW_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient
from mosaic.main import app
from mosaic.auth import Principal, get_current_principal
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



def test_application_runtime_manifest_is_tenant_scoped_and_validates_data_sources():
    created = org("Runtime App Org", "runtime-app-org")
    other = org("Other Runtime Org", "other-runtime-org")
    headers = {**H, "X-Organisation-ID": created.json()["id"]}
    other_headers = {**H, "X-Organisation-ID": other.json()["id"]}
    model = client.post(
        "/api/v1/objects",
        json={"key": "supplier", "label": "Supplier", "schema": {
            "type": "object", "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False,
        }},
        headers=headers,
    )
    assert model.status_code == 201, model.text
    created_app = client.post(
        "/api/v1/apps",
        json={"name": "Supplier Workspace", "description": "Manage suppliers", "config": {
            "navigation": ["Dashboard", "Suppliers"],
            "pages": [
                {"name": "Dashboard", "type": "dashboard"},
                {"name": "Suppliers", "type": "data-list", "dataSource": "supplier"},
            ],
        }},
        headers=headers,
    )
    assert created_app.status_code == 201, created_app.text
    app_id = created_app.json()["id"]
    runtime = client.get(f"/api/v1/apps/{app_id}/runtime", headers=headers)
    assert runtime.status_code == 200, runtime.text
    assert runtime.json()["status"] == "draft"
    assert runtime.json()["objects"]["supplier"]["id"] == model.json()["id"]
    assert len(runtime.json()["pages"]) == 2
    assert client.get(f"/api/v1/apps/{app_id}/runtime", headers=other_headers).status_code == 404

    invalid = client.post(
        "/api/v1/apps",
        json={"name": "Broken App", "config": {"pages": [
            {"name": "Missing", "type": "data-list", "dataSource": "not_a_model"}
        ]}},
        headers=headers,
    )
    assert invalid.status_code == 201
    assert client.get(f"/api/v1/apps/{invalid.json()['id']}/runtime", headers=headers).status_code == 422


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



def test_workflow_runtime_pauses_for_approval_and_resumes_idempotently():
    created_org = org("Runtime Org", "runtime-org")
    assert created_org.status_code == 201
    headers = {**H, "X-Organisation-ID": created_org.json()["id"]}
    created = client.post(
        "/api/v1/workflows",
        json={"name": "Supplier approval", "definition": {"steps": [
            {"type": "log", "message": "Supplier submitted"},
            {"type": "manual_approval", "label": "Procurement review"},
            {"type": "log", "message": "Supplier approved"},
        ]}},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    assert client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"input": {"supplier_id": "sup-123"}},
        headers=headers,
    ).status_code == 409
    assert client.post(f"/api/v1/workflows/{workflow_id}/enable", headers=headers).json()["enabled"]

    started = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"input": {"supplier_id": "sup-123"}, "idempotency_key": "supplier-123"},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "waiting_approval"
    assert run["current_step"] == 1
    assert len(run["step_results"]) == 2

    replay = client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={"input": {"supplier_id": "sup-123"}, "idempotency_key": "supplier-123"},
        headers=headers,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == run["id"]

    approved = client.post(
        f"/api/v1/workflow-runs/{run['id']}/approval",
        json={"approved": True, "comment": "Verified supplier documents"},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "succeeded"
    assert [item["status"] for item in approved.json()["step_results"]] == [
        "completed", "approved", "completed"
    ]
    assert client.post(
        f"/api/v1/workflow-runs/{run['id']}/approval",
        json={"approved": True},
        headers=headers,
    ).status_code == 409
    history = client.get(f"/api/v1/workflows/{workflow_id}/runs", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["id"] == run["id"]


def test_workflow_runtime_rejection_stops_run():
    created_org = org("Reject Org", "reject-org")
    headers = {**H, "X-Organisation-ID": created_org.json()["id"]}
    created = client.post(
        "/api/v1/workflows",
        json={"name": "Review", "definition": {"steps": [
            {"type": "manual_approval", "label": "Review"},
            {"type": "log", "message": "This must not run"},
        ]}},
        headers=headers,
    )
    workflow_id = created.json()["id"]
    client.post(f"/api/v1/workflows/{workflow_id}/enable", headers=headers)
    run = client.post(f"/api/v1/workflows/{workflow_id}/runs", json={}, headers=headers).json()
    rejected = client.post(
        f"/api/v1/workflow-runs/{run['id']}/approval",
        json={"approved": False, "comment": "Incomplete documentation"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"
    assert rejected.json()["current_step"] == 0
    assert len(rejected.json()["step_results"]) == 1


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



def test_oidc_principal_owns_only_its_organisation():
    owner = Principal(
        user_id="a" * 64,
        issuer="https://identity.example",
        subject="user-a",
        email="owner@example.test",
    )
    app.dependency_overrides[get_current_principal] = lambda: owner
    try:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Owned Workspace", "slug": "owned-" + uuid4().hex[:8]},
            headers=H,
        )
        assert created.status_code == 201, created.text
        org_id = created.json()["id"]

        owner_headers = {**H, "X-Organisation-ID": org_id}
        object_response = client.post(
            "/api/v1/objects",
            json={"key": "supplier", "label": "Supplier", "schema": {"type": "object"}},
            headers=owner_headers,
        )
        assert object_response.status_code == 201, object_response.text
        assert any(item["id"] == org_id for item in client.get("/api/v1/organisations", headers=H).json())
        me = client.get("/api/v1/me", headers=H)
        assert me.status_code == 200
        assert me.json()["organisations"] == [{"id": org_id, "role": "owner"}]

        stranger = Principal(
            user_id="b" * 64,
            issuer="https://identity.example",
            subject="user-b",
            email="stranger@example.test",
        )
        app.dependency_overrides[get_current_principal] = lambda: stranger
        denied = client.get("/api/v1/objects", headers=owner_headers)
        assert denied.status_code == 404
        assert client.get("/api/v1/organisations", headers=H).json() == []
        assert client.get("/api/v1/me", headers=H).json()["organisations"] == []
    finally:
        app.dependency_overrides.clear()


def test_verified_single_use_organisation_invitation_and_membership_lifecycle():
    owner = Principal(
        user_id="c" * 64, issuer="https://identity.example", subject="owner-invite",
        email="owner@example.test", email_verified=True,
    )
    app.dependency_overrides[get_current_principal] = lambda: owner
    try:
        created = client.post(
            "/api/v1/organisations",
            json={"name": "Invitation Workspace", "slug": "invite-" + uuid4().hex[:8]},
            headers=H,
        )
        assert created.status_code == 201, created.text
        org_id = created.json()["id"]
        invitation = client.post(
            f"/api/v1/organisations/{org_id}/invitations",
            json={"email": "new.member@example.test", "role": "builder"},
            headers=H,
        )
        assert invitation.status_code == 201, invitation.text
        token = invitation.json()["acceptance_token"]
        assert token and "token_hash" not in invitation.text

        unverified = Principal(
            user_id="d" * 64, issuer="https://identity.example", subject="new-member",
            email="new.member@example.test", email_verified=False,
        )
        app.dependency_overrides[get_current_principal] = lambda: unverified
        assert client.post("/api/v1/invitations/accept", json={"token": token}, headers=H).status_code == 403

        wrong_email = Principal(
            user_id="e" * 64, issuer="https://identity.example", subject="wrong-email",
            email="other@example.test", email_verified=True,
        )
        app.dependency_overrides[get_current_principal] = lambda: wrong_email
        assert client.post("/api/v1/invitations/accept", json={"token": token}, headers=H).status_code == 403

        member = Principal(
            user_id="f" * 64, issuer="https://identity.example", subject="new-member",
            email="NEW.MEMBER@example.test", email_verified=True,
        )
        app.dependency_overrides[get_current_principal] = lambda: member
        accepted = client.post("/api/v1/invitations/accept", json={"token": token}, headers=H)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["role"] == "builder"
        assert client.post("/api/v1/invitations/accept", json={"token": token}, headers=H).status_code == 410

        app.dependency_overrides[get_current_principal] = lambda: owner
        members = client.get(f"/api/v1/organisations/{org_id}/members", headers=H)
        assert members.status_code == 200
        assert {item["role"] for item in members.json()} == {"owner", "builder"}
        assert client.patch(
            f"/api/v1/organisations/{org_id}/members/{member.user_id}",
            json={"role": "operator"}, headers=H,
        ).json()["role"] == "operator"
        assert client.delete(
            f"/api/v1/organisations/{org_id}/members/{member.user_id}", headers=H
        ).status_code == 204
        assert len(client.get(f"/api/v1/organisations/{org_id}/members", headers=H).json()) == 1
    finally:
        app.dependency_overrides.clear()

import base64
import binascii
import hmac
import os
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db
from .auth import Principal, get_current_principal, oidc_enabled
from .models import Application, AuditEvent, DataObject, DataRecord, Organisation, OrganisationMembership, Workflow

app = FastAPI(
    title="MOSAIC Platform",
    version="0.2.0",
    description="Programmable business infrastructure — controlled developer preview",
)
ROOT = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def preview_basic_auth(request, call_next):
    # Single-operator preview gate. This is not enterprise identity or tenant authorisation.
    if request.url.path in {"/health", "/health/live", "/health/ready"}:
        return await call_next(request)
    oidc_vars = ("OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_JWKS_URL")
    if any(os.getenv(key) for key in oidc_vars):
        if not oidc_enabled():
            return JSONResponse({"detail": "OIDC configuration is incomplete"}, status_code=503)
        return await call_next(request)
    expected_password = os.getenv("MOSAIC_PREVIEW_PASSWORD")
    expected_username = os.getenv("MOSAIC_PREVIEW_USERNAME", "owner")
    if not expected_password:
        return JSONResponse({"detail": "Preview authentication is not configured"}, status_code=503)
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="MOSAIC preview", charset="UTF-8"'},
        )
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, separator, password = decoded.partition(":")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        username, separator, password = "", "", ""
    valid = (
        bool(separator)
        and hmac.compare_digest(username, expected_username)
        and hmac.compare_digest(password, expected_password)
    )
    if not valid:
        return JSONResponse(
            {"detail": "Invalid credentials"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="MOSAIC preview", charset="UTF-8"'},
        )
    request.state.principal = {
        "user_id": "preview:owner",
        "issuer": "preview",
        "subject": "owner",
        "email": None,
        "is_preview": True,
    }
    return await call_next(request)


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")


class ObjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")
    label: str = Field(min_length=1, max_length=160)
    spec: dict = Field(default_factory=dict, alias="schema")


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    config: dict = Field(default_factory=dict)


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    definition: dict = Field(default_factory=dict)


class RecordIn(BaseModel):
    data: dict


def require_token(principal: Principal = Depends(get_current_principal)):
    return principal


def set_user_context(db: Session, user_id: str):
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.current_user_id', :value, true)"), {"value": user_id})


def set_tenant_context(db: Session, org_id: str):
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.current_org_id', :value, true)"), {"value": org_id})


def org_scope(
    request: Request,
    x_org_id: str = Header(..., alias="X-Organisation-ID"),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    set_user_context(db, principal.user_id)
    if not principal.is_preview:
        membership = db.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.org_id == x_org_id,
                OrganisationMembership.user_id == principal.user_id,
            )
        )
        if not membership:
            raise HTTPException(404, "Organisation not found")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and membership.role not in {
            "owner", "admin", "builder", "operator"
        }:
            raise HTTPException(403, "Your organisation role cannot perform this action")
    org = db.get(Organisation, x_org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    set_tenant_context(db, org.id)
    return org


def audit(db, org_id, action, resource_type, resource_id, details=None):
    db.add(
        AuditEvent(
            id=str(uuid4()),
            org_id=org_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )


def object_for_org(db: Session, object_id: str, org_id: str) -> DataObject:
    obj = db.scalar(
        select(DataObject).where(DataObject.id == object_id, DataObject.org_id == org_id)
    )
    if not obj:
        raise HTTPException(404, "Data object not found")
    return obj


def validate_record(schema: dict, data: dict):
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    except SchemaError as exc:
        raise HTTPException(422, f"Invalid stored JSON Schema: {exc.message}") from exc
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise HTTPException(422, f"Record validation failed at {location}: {exc.message}") from exc


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/demo/suppliers")
def supplier_portal_demo():
    """Serve the runnable supplier onboarding demo application."""
    return FileResponse(ROOT / "static" / "supplier-portal.html")


@app.get("/health")
@app.get("/health/live")
def health_live():
    return {"status": "ok", "service": "mosaic-platform", "version": "0.2.0"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ready", "database": "connected"}


@app.get("/api/v1/platform")
def platform():
    return {
        "name": "MOSAIC",
        "tagline": "Build your business on a platform you can programme",
        "capabilities": [
            "organisations", "metadata-driven data objects", "validated business records",
            "application lifecycle", "workflow definitions", "audit events",
        ],
        "stage": "controlled-developer-preview",
    }


@app.post("/api/v1/demo/supplier-onboarding", dependencies=[Depends(require_token)])
def load_supplier_onboarding_demo(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Create or reuse a complete, fictional supplier-onboarding demo workspace."""
    if not principal.is_preview:
        raise HTTPException(403, "The shared demo seed is available only in preview mode")
    org = db.scalar(select(Organisation).where(Organisation.slug == "mosaic-demo"))
    if not org:
        org = Organisation(id=str(uuid4()), name="MOSAIC Demo Workspace", slug="mosaic-demo")
        db.add(org)
        db.flush()
        audit(db, org.id, "organisation.created", "organisation", org.id, {"source": "demo_seed"})

    schema = {
        "type": "object",
        "required": ["company_name", "email", "status"],
        "properties": {
            "company_name": {"type": "string", "minLength": 2},
            "email": {"type": "string", "format": "email"},
            "registration_number": {"type": "string"},
            "contact_person": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "approved", "rejected"]},
        },
        "additionalProperties": False,
    }
    obj = db.scalar(select(DataObject).where(
        DataObject.org_id == org.id, DataObject.key == "supplier"
    ))
    if not obj:
        obj = DataObject(
            id=str(uuid4()), org_id=org.id, key="supplier",
            label="Supplier", schema_json=schema,
        )
        db.add(obj)
        db.flush()
        audit(db, org.id, "object.created", "data_object", obj.id, {"key": "supplier"})

    app_item = db.scalar(select(Application).where(
        Application.org_id == org.id, Application.name == "Supplier Onboarding Portal"
    ))
    if not app_item:
        app_item = Application(
            id=str(uuid4()), org_id=org.id, name="Supplier Onboarding Portal",
            description="Register and manage suppliers through an approval process.",
            config={
                "navigation": ["Dashboard", "Suppliers", "Approvals"],
                "pages": [
                    {"name": "Dashboard", "type": "dashboard"},
                    {"name": "Suppliers", "type": "data-list", "dataSource": "supplier"},
                    {"name": "Register Supplier", "type": "data-form", "dataSource": "supplier"},
                ],
            },
            status="draft",
        )
        db.add(app_item)
        db.flush()
        audit(db, org.id, "application.created", "application", app_item.id, {"source": "demo_seed"})

    workflow = db.scalar(select(Workflow).where(
        Workflow.org_id == org.id, Workflow.name == "Supplier Approval Workflow"
    ))
    if not workflow:
        workflow = Workflow(
            id=str(uuid4()), org_id=org.id, name="Supplier Approval Workflow",
            definition={"steps": [
                {"type": "manual_approval", "label": "Review supplier application"},
                {"type": "log", "message": "Supplier approval completed"},
            ]},
            enabled=False,
        )
        db.add(workflow)
        db.flush()
        audit(db, org.id, "workflow.created", "workflow", workflow.id, {"source": "demo_seed"})

    examples = [
        {
            "company_name": "Acme Office Supplies",
            "email": "onboarding@acme.example",
            "registration_number": "DEMO-REG-001",
            "contact_person": "Jordan Example",
            "status": "pending",
        },
        {
            "company_name": "Cape Digital Services",
            "email": "suppliers@capedigital.example",
            "registration_number": "DEMO-REG-002",
            "contact_person": "Taylor Example",
            "status": "approved",
        },
    ]
    existing = db.scalars(select(DataRecord).where(
        DataRecord.org_id == org.id, DataRecord.object_id == obj.id
    )).all()
    existing_names = {r.data.get("company_name") for r in existing}
    created_records = 0
    for data in examples:
        if data["company_name"] not in existing_names:
            record = DataRecord(id=str(uuid4()), org_id=org.id, object_id=obj.id, data=data)
            db.add(record)
            db.flush()
            audit(db, org.id, "record.created", "data_record", record.id, {"object_key": "supplier", "source": "demo_seed"})
            created_records += 1

    db.commit()
    return {
        "organisation": {"id": org.id, "name": org.name, "slug": org.slug},
        "data_object": {"id": obj.id, "key": obj.key, "label": obj.label},
        "application": {"id": app_item.id, "name": app_item.name, "status": app_item.status},
        "workflow": {"id": workflow.id, "name": workflow.name, "enabled": workflow.enabled},
        "records_created": created_records,
        "message": "Supplier onboarding demo is ready. Re-running this action will reuse existing resources.",
    }


@app.post("/api/v1/organisations", dependencies=[Depends(require_token)], status_code=201)
def create_org(
    payload: OrgIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    set_user_context(db, principal.user_id)
    if db.scalar(select(Organisation).where(Organisation.slug == payload.slug)):
        raise HTTPException(409, "Slug already exists")
    org = Organisation(id=str(uuid4()), name=payload.name, slug=payload.slug)
    set_tenant_context(db, org.id)
    db.add(org)
    db.flush()
    if not principal.is_preview:
        db.add(OrganisationMembership(
            id=str(uuid4()), org_id=org.id, user_id=principal.user_id,
            issuer=principal.issuer, subject=principal.subject, email=principal.email, role="owner",
        ))
    audit(db, org.id, "organisation.created", "organisation", org.id, {"slug": org.slug})
    db.commit()
    db.refresh(org)
    return {"id": org.id, "name": org.name, "slug": org.slug, "created_at": org.created_at}


@app.get("/api/v1/organisations", dependencies=[Depends(require_token)])
def list_orgs(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    set_user_context(db, principal.user_id)
    if principal.is_preview and db.bind and db.bind.dialect.name == "sqlite":
        organisations = db.scalars(select(Organisation).order_by(Organisation.name)).all()
    else:
        organisations = db.scalars(
            select(Organisation)
            .join(OrganisationMembership, OrganisationMembership.org_id == Organisation.id)
            .where(OrganisationMembership.user_id == principal.user_id)
            .order_by(Organisation.name)
        ).all()
    return [{"id": o.id, "name": o.name, "slug": o.slug} for o in organisations]


@app.get("/api/v1/me", dependencies=[Depends(require_token)])
def current_user(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    set_user_context(db, principal.user_id)
    if principal.is_preview and db.bind and db.bind.dialect.name == "sqlite":
        memberships = []
    else:
        memberships = db.scalars(
            select(OrganisationMembership)
            .where(OrganisationMembership.user_id == principal.user_id)
            .order_by(OrganisationMembership.created_at.asc())
        ).all()
    return {
        "user_id": principal.user_id,
        "issuer": principal.issuer,
        "subject": principal.subject,
        "email": principal.email,
        "preview": principal.is_preview,
        "organisations": [
            {"id": item.org_id, "role": item.role}
            for item in memberships
        ],
    }


@app.post("/api/v1/objects", dependencies=[Depends(require_token)], status_code=201)
def create_object(
    payload: ObjectIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)
):
    try:
        Draft202012Validator.check_schema(payload.spec)
    except SchemaError as exc:
        raise HTTPException(422, f"Invalid JSON Schema: {exc.message}") from exc
    obj = DataObject(
        id=str(uuid4()), org_id=org.id, key=payload.key,
        label=payload.label, schema_json=payload.spec,
    )
    db.add(obj)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An object with this key already exists in this organisation") from exc
    audit(db, org.id, "object.created", "data_object", obj.id, {"key": obj.key})
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "key": obj.key, "label": obj.label, "schema": obj.schema_json}


@app.get("/api/v1/objects", dependencies=[Depends(require_token)])
def list_objects(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [
        {"id": o.id, "key": o.key, "label": o.label, "schema": o.schema_json}
        for o in db.scalars(
            select(DataObject).where(DataObject.org_id == org.id).order_by(DataObject.created_at.desc())
        ).all()
    ]


@app.post(
    "/api/v1/objects/{object_id}/records",
    dependencies=[Depends(require_token)],
    status_code=201,
)
def create_record(
    object_id: str,
    payload: RecordIn,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    obj = object_for_org(db, object_id, org.id)
    validate_record(obj.schema_json, payload.data)
    record = DataRecord(
        id=str(uuid4()), org_id=org.id, object_id=obj.id, data=payload.data
    )
    db.add(record)
    audit(db, org.id, "record.created", "data_record", record.id, {"object_key": obj.key})
    db.commit()
    db.refresh(record)
    return {
        "id": record.id, "object_id": record.object_id, "data": record.data,
        "created_at": record.created_at, "updated_at": record.updated_at,
    }


@app.get(
    "/api/v1/objects/{object_id}/records",
    dependencies=[Depends(require_token)],
)
def list_records(
    object_id: str,
    limit: int = 50,
    offset: int = 0,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    object_for_org(db, object_id, org.id)
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(422, "limit must be 1-100 and offset must be non-negative")
    records = db.scalars(
        select(DataRecord)
        .where(DataRecord.object_id == object_id, DataRecord.org_id == org.id)
        .order_by(DataRecord.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return [
        {"id": r.id, "object_id": r.object_id, "data": r.data,
         "created_at": r.created_at, "updated_at": r.updated_at}
        for r in records
    ]


@app.get("/api/v1/records/{record_id}", dependencies=[Depends(require_token)])
def get_record(
    record_id: str,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    record = db.scalar(
        select(DataRecord).where(DataRecord.id == record_id, DataRecord.org_id == org.id)
    )
    if not record:
        raise HTTPException(404, "Record not found")
    return {"id": record.id, "object_id": record.object_id, "data": record.data,
            "created_at": record.created_at, "updated_at": record.updated_at}


@app.put("/api/v1/records/{record_id}", dependencies=[Depends(require_token)])
def update_record(
    record_id: str,
    payload: RecordIn,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    record = db.scalar(
        select(DataRecord).where(DataRecord.id == record_id, DataRecord.org_id == org.id)
    )
    if not record:
        raise HTTPException(404, "Record not found")
    obj = object_for_org(db, record.object_id, org.id)
    validate_record(obj.schema_json, payload.data)
    record.data = payload.data
    audit(db, org.id, "record.updated", "data_record", record.id, {"object_key": obj.key})
    db.commit()
    db.refresh(record)
    return {"id": record.id, "object_id": record.object_id, "data": record.data,
            "created_at": record.created_at, "updated_at": record.updated_at}


@app.delete(
    "/api/v1/records/{record_id}",
    dependencies=[Depends(require_token)],
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_record(
    record_id: str,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    record = db.scalar(
        select(DataRecord).where(DataRecord.id == record_id, DataRecord.org_id == org.id)
    )
    if not record:
        raise HTTPException(404, "Record not found")
    audit(db, org.id, "record.deleted", "data_record", record.id)
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/apps", dependencies=[Depends(require_token)], status_code=201)
def create_app(payload: AppIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    item = Application(
        id=str(uuid4()), org_id=org.id, name=payload.name,
        description=payload.description, config=payload.config, status="draft",
    )
    db.add(item)
    db.flush()
    audit(db, org.id, "application.created", "application", item.id)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description,
            "config": item.config, "status": item.status, "version": item.version}


@app.get("/api/v1/apps", dependencies=[Depends(require_token)])
def list_apps(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [
        {"id": a.id, "name": a.name, "description": a.description,
         "status": a.status, "version": a.version, "config": a.config}
        for a in db.scalars(
            select(Application).where(Application.org_id == org.id).order_by(Application.created_at.desc())
        ).all()
    ]


@app.post("/api/v1/apps/{app_id}/publish", dependencies=[Depends(require_token)])
def publish_app(app_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    item = db.scalar(select(Application).where(Application.id == app_id, Application.org_id == org.id))
    if not item:
        raise HTTPException(404, "Application not found")
    item.status = "published"
    item.version += 1
    audit(db, org.id, "application.published", "application", item.id, {"version": item.version})
    db.commit()
    return {"id": item.id, "status": item.status, "version": item.version}


@app.post("/api/v1/workflows", dependencies=[Depends(require_token)], status_code=201)
def create_workflow(
    payload: WorkflowIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)
):
    steps = payload.definition.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 50:
        raise HTTPException(422, "Workflow must contain a steps array with at most 50 steps")
    allowed = {"manual_approval", "log", "http_request_placeholder"}
    for step in steps:
        if not isinstance(step, dict) or step.get("type") not in allowed:
            raise HTTPException(422, f"Unsupported step type. Allowed: {', '.join(sorted(allowed))}")
    wf = Workflow(
        id=str(uuid4()), org_id=org.id, name=payload.name,
        definition=payload.definition, enabled=False,
    )
    db.add(wf)
    db.flush()
    audit(db, org.id, "workflow.created", "workflow", wf.id, {"steps": len(steps)})
    db.commit()
    db.refresh(wf)
    return {"id": wf.id, "name": wf.name, "definition": wf.definition, "enabled": wf.enabled}


@app.get("/api/v1/workflows", dependencies=[Depends(require_token)])
def list_workflows(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [
        {"id": w.id, "name": w.name, "definition": w.definition, "enabled": w.enabled}
        for w in db.scalars(
            select(Workflow).where(Workflow.org_id == org.id).order_by(Workflow.created_at.desc())
        ).all()
    ]


@app.post("/api/v1/workflows/{workflow_id}/enable", dependencies=[Depends(require_token)])
def enable_workflow(
    workflow_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)
):
    wf = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.org_id == org.id))
    if not wf:
        raise HTTPException(404, "Workflow not found")
    wf.enabled = True
    audit(db, org.id, "workflow.enabled", "workflow", wf.id)
    db.commit()
    return {"id": wf.id, "enabled": True}


@app.get("/api/v1/audit", dependencies=[Depends(require_token)])
def audit_log(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [
        {"id": e.id, "actor": e.actor, "action": e.action, "resource_type": e.resource_type,
         "resource_id": e.resource_id, "details": e.details, "created_at": e.created_at}
        for e in db.scalars(
            select(AuditEvent).where(AuditEvent.org_id == org.id)
            .order_by(AuditEvent.created_at.desc()).limit(200)
        ).all()
    ]

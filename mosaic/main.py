import os
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import Base, engine, get_db
from .models import Organisation, DataObject, Application, Workflow, AuditEvent

Base.metadata.create_all(bind=engine)
app = FastAPI(title="MOSAIC Platform", version="0.1.0", description="Programmable business infrastructure — developer preview")
ROOT = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
DEMO_TOKEN = os.getenv("MOSAIC_DEMO_TOKEN", "mosaic-local-demo")

class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")

class ObjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")
    label: str
    spec: dict = Field(default_factory=dict, alias="schema")

class AppIn(BaseModel):
    name: str
    description: str = ""
    config: dict = Field(default_factory=dict)

class WorkflowIn(BaseModel):
    name: str
    definition: dict = Field(default_factory=dict)

def require_token(authorization: str | None = Header(default=None)):
    # Deliberately simple local-preview gate. Replace with OIDC/Keycloak before any shared deployment.
    if os.getenv("MOSAIC_ALLOW_INSECURE_DEMO", "true").lower() != "true":
        if authorization != f"Bearer {DEMO_TOKEN}":
            raise HTTPException(401, "Valid bearer token required")
    elif authorization and authorization != f"Bearer {DEMO_TOKEN}":
        raise HTTPException(401, "Invalid demo token")

def org_scope(x_org_id: str = Header(..., alias="X-Organisation-ID"), db: Session = Depends(get_db)):
    # Demo-only selector. This is NOT an authenticated tenant membership check.
    org = db.get(Organisation, x_org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    return org

def audit(db, org_id, action, resource_type, resource_id, details=None):
    db.add(AuditEvent(id=str(uuid4()), org_id=org_id, action=action, resource_type=resource_type, resource_id=resource_id, details=details or {}))

@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/health")
def health():
    return {"status": "ok", "service": "mosaic-platform", "version": "0.1.0"}

@app.get("/api/v1/platform")
def platform():
    return {"name": "MOSAIC", "tagline": "Build your business on a platform you can programme", "capabilities": ["organisations", "metadata-driven data objects", "application lifecycle", "workflow definitions", "audit events"], "stage": "developer-preview"}

@app.post("/api/v1/organisations", dependencies=[Depends(require_token)], status_code=201)
def create_org(payload: OrgIn, db: Session = Depends(get_db)):
    if db.scalar(select(Organisation).where(Organisation.slug == payload.slug)):
        raise HTTPException(409, "Slug already exists")
    org = Organisation(id=str(uuid4()), name=payload.name, slug=payload.slug)
    db.add(org)
    db.flush()
    audit(db, org.id, "organisation.created", "organisation", org.id, {"slug": org.slug})
    db.commit()
    db.refresh(org)
    return {"id": org.id, "name": org.name, "slug": org.slug, "created_at": org.created_at}

@app.get("/api/v1/organisations", dependencies=[Depends(require_token)])
def list_orgs(db: Session = Depends(get_db)):
    return [{"id": o.id, "name": o.name, "slug": o.slug} for o in db.scalars(select(Organisation).order_by(Organisation.name)).all()]

@app.post("/api/v1/objects", dependencies=[Depends(require_token)], status_code=201)
def create_object(payload: ObjectIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    obj = DataObject(id=str(uuid4()), org_id=org.id, key=payload.key, label=payload.label, schema_json=payload.spec)
    db.add(obj)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(409, "An object with this key already exists in this organisation")
    audit(db, org.id, "object.created", "data_object", obj.id, {"key": obj.key})
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "key": obj.key, "label": obj.label, "schema": obj.schema_json}

@app.get("/api/v1/objects", dependencies=[Depends(require_token)])
def list_objects(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [{"id": o.id, "key": o.key, "label": o.label, "schema": o.schema_json} for o in db.scalars(select(DataObject).where(DataObject.org_id == org.id).order_by(DataObject.created_at.desc())).all()]

@app.post("/api/v1/apps", dependencies=[Depends(require_token)], status_code=201)
def create_app(payload: AppIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    item = Application(id=str(uuid4()), org_id=org.id, name=payload.name, description=payload.description, config=payload.config, status="draft")
    db.add(item)
    db.flush()
    audit(db, org.id, "application.created", "application", item.id)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description, "config": item.config, "status": item.status, "version": item.version}

@app.get("/api/v1/apps", dependencies=[Depends(require_token)])
def list_apps(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [{"id": a.id, "name": a.name, "description": a.description, "status": a.status, "version": a.version, "config": a.config} for a in db.scalars(select(Application).where(Application.org_id == org.id).order_by(Application.created_at.desc())).all()]

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
def create_workflow(payload: WorkflowIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    steps = payload.definition.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 50:
        raise HTTPException(422, "Workflow must contain a steps array with at most 50 steps")
    # Workflow definitions are declarative only; arbitrary code execution is intentionally unsupported.
    allowed = {"manual_approval", "log", "http_request_placeholder"}
    for step in steps:
        if not isinstance(step, dict) or step.get("type") not in allowed:
            raise HTTPException(422, f"Unsupported step type. Allowed: {', '.join(sorted(allowed))}")
    wf = Workflow(id=str(uuid4()), org_id=org.id, name=payload.name, definition=payload.definition, enabled=False)
    db.add(wf)
    db.flush()
    audit(db, org.id, "workflow.created", "workflow", wf.id, {"steps": len(steps)})
    db.commit()
    db.refresh(wf)
    return {"id": wf.id, "name": wf.name, "definition": wf.definition, "enabled": wf.enabled}

@app.get("/api/v1/workflows", dependencies=[Depends(require_token)])
def list_workflows(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [{"id": w.id, "name": w.name, "definition": w.definition, "enabled": w.enabled} for w in db.scalars(select(Workflow).where(Workflow.org_id == org.id).order_by(Workflow.created_at.desc())).all()]

@app.post("/api/v1/workflows/{workflow_id}/enable", dependencies=[Depends(require_token)])
def enable_workflow(workflow_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    wf = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.org_id == org.id))
    if not wf:
        raise HTTPException(404, "Workflow not found")
    wf.enabled = True
    audit(db, org.id, "workflow.enabled", "workflow", wf.id)
    db.commit()
    return {"id": wf.id, "enabled": True}

@app.get("/api/v1/audit", dependencies=[Depends(require_token)])
def audit_log(org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    return [{"id": e.id, "actor": e.actor, "action": e.action, "resource_type": e.resource_type, "resource_id": e.resource_id, "details": e.details, "created_at": e.created_at} for e in db.scalars(select(AuditEvent).where(AuditEvent.org_id == org.id).order_by(AuditEvent.created_at.desc()).limit(200)).all()]

import base64
import binascii
import hmac
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
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
from .models import Application, ApplicationRelease, AuditEvent, DataObject, DataRecord, Organisation, OrganisationMembership, OrganisationInvitation, Workflow, WorkflowRun

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


class InvitationIn(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default="member", pattern=r"^(member|operator|builder|admin)$")
    expires_in_days: int = Field(default=7, ge=1, le=30)


class RoleIn(BaseModel):
    role: str = Field(pattern=r"^(member|operator|builder|admin)$")


class InvitationAcceptIn(BaseModel):
    token: str = Field(min_length=40, max_length=200)


class ObjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")
    label: str = Field(min_length=1, max_length=160)
    spec: dict = Field(default_factory=dict, alias="schema")


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    config: dict = Field(default_factory=dict)


class AppUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    config: dict
    expected_version: int = Field(ge=1)


class ReleaseIn(BaseModel):
    environment: str = Field(pattern=r"^(development|staging|production)$")


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    definition: dict = Field(default_factory=dict)


class WorkflowRunIn(BaseModel):
    input: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class WorkflowApprovalIn(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


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


@app.get("/api/v1/auth/config")
def browser_auth_config(request: Request):
    """Expose public OIDC client settings; never expose a client secret."""
    if not oidc_enabled():
        return {"enabled": False}
    client_id = os.getenv("OIDC_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "OIDC_CLIENT_ID is required for browser login")
    issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
    return {
        "enabled": True,
        "issuer": issuer,
        "client_id": client_id,
        "redirect_uri": os.getenv("OIDC_REDIRECT_URI") or str(request.base_url).rstrip("/") + "/",
        "scopes": ["openid", "profile", "email"],
    }


@app.get("/api/v1/app-components", dependencies=[Depends(require_token)])
def list_app_components():
    return [
        {"type": "heading", "label": "Heading", "description": "Section title", "props": {"text": "Section heading"}},
        {"type": "text", "label": "Text", "description": "Supporting copy", "props": {"text": "Describe this part of the application"}},
        {"type": "metric", "label": "Metric", "description": "Count records in a data model", "props": {"label": "Total records"}, "binding": {"object": "supplier"}},
        {"type": "data-table", "label": "Data table", "description": "List records from a data model", "binding": {"object": "supplier"}},
        {"type": "data-form", "label": "Data form", "description": "Create records in a data model", "binding": {"object": "supplier"}},
        {"type": "button", "label": "Workflow button", "description": "Start an enabled workflow", "props": {"label": "Run workflow"}},
    ]


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



def require_org_admin(org: Organisation, principal: Principal, db: Session) -> OrganisationMembership:
    if principal.is_preview:
        raise HTTPException(403, "Organisation invitations require verified OIDC identity")
    membership = db.scalar(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org.id, OrganisationMembership.user_id == principal.user_id
    ))
    if not membership or membership.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only organisation owners and admins can manage membership")
    return membership


def normalise_email(value: str) -> str:
    return value.strip().casefold()


@app.post("/api/v1/organisations/{org_id}/invitations", status_code=201)
def create_invitation(org_id: str, payload: InvitationIn,
    principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    actor = require_org_admin(org, principal, db)
    if not principal.email_verified or not principal.email:
        raise HTTPException(403, "A verified email address is required to manage invitations")
    email = normalise_email(payload.email)
    if actor.role != "owner" and payload.role == "admin":
        raise HTTPException(403, "Only an owner can invite an organisation admin")
    existing = db.scalar(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org_id, OrganisationMembership.email == email))
    if existing:
        raise HTTPException(409, "This email already belongs to the organisation")
    pending = db.scalar(select(OrganisationInvitation).where(
        OrganisationInvitation.org_id == org_id, OrganisationInvitation.email == email,
        OrganisationInvitation.accepted_at.is_(None), OrganisationInvitation.revoked_at.is_(None)))
    if pending and pending.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
        raise HTTPException(409, "An active invitation already exists for this email")
    token = f"{org_id}.{secrets.token_urlsafe(36)}"
    invitation = OrganisationInvitation(
        id=str(uuid4()), org_id=org_id, email=email,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), role=payload.role,
        invited_by=principal.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days))
    db.add(invitation)
    audit(db, org_id, "membership.invitation_created", "organisation_invitation",
          invitation.id, {"email": email, "role": payload.role})
    db.commit()
    return {"id": invitation.id, "email": email, "role": payload.role,
            "expires_at": invitation.expires_at, "acceptance_token": token,
            "delivery": "manual", "message": "Deliver this token through a trusted channel. It is shown only once."}


@app.get("/api/v1/organisations/{org_id}/invitations")
def list_invitations(org_id: str, principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    require_org_admin(org, principal, db)
    invitations = db.scalars(select(OrganisationInvitation).where(
        OrganisationInvitation.org_id == org_id,
        OrganisationInvitation.accepted_at.is_(None),
        OrganisationInvitation.revoked_at.is_(None),
    ).order_by(OrganisationInvitation.created_at.desc())).all()
    now = datetime.now(timezone.utc)
    return [{"id": item.id, "email": item.email, "role": item.role,
             "expires_at": item.expires_at, "expired": item.expires_at.replace(tzinfo=timezone.utc) <= now}
            for item in invitations]


@app.get("/api/v1/organisations/{org_id}/members")
def list_members(org_id: str, principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    require_org_admin(org, principal, db)
    members = db.scalars(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org_id).order_by(OrganisationMembership.created_at.asc())).all()
    return [{"user_id": x.user_id, "email": x.email, "role": x.role, "created_at": x.created_at}
            for x in members]


@app.patch("/api/v1/organisations/{org_id}/members/{user_id}")
def update_member_role(org_id: str, user_id: str, payload: RoleIn,
    principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    actor = require_org_admin(org, principal, db)
    target = db.scalar(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org_id, OrganisationMembership.user_id == user_id))
    if not target:
        raise HTTPException(404, "Member not found")
    if target.role == "owner":
        raise HTTPException(409, "The organisation owner role cannot be changed here")
    if actor.role != "owner" and (target.role == "admin" or payload.role == "admin"):
        raise HTTPException(403, "Only an owner can change administrator roles")
    target.role = payload.role
    audit(db, org_id, "membership.role_updated", "organisation_membership", target.id, {"role": payload.role})
    db.commit()
    return {"user_id": target.user_id, "role": target.role}


@app.delete("/api/v1/organisations/{org_id}/members/{user_id}", status_code=204)
def remove_member(org_id: str, user_id: str, principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    actor = require_org_admin(org, principal, db)
    target = db.scalar(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org_id, OrganisationMembership.user_id == user_id))
    if not target:
        raise HTTPException(404, "Member not found")
    if target.role == "owner":
        raise HTTPException(409, "The organisation owner cannot be removed")
    if actor.role != "owner" and target.role == "admin":
        raise HTTPException(403, "Only an owner can remove an administrator")
    audit(db, org_id, "membership.revoked", "organisation_membership", target.id,
          {"user_id": target.user_id, "role": target.role})
    db.delete(target)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/invitations/accept")
def accept_invitation(payload: InvitationAcceptIn, principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db)):
    if principal.is_preview or not principal.email_verified or not principal.email:
        raise HTTPException(403, "Accepting an invitation requires a verified OIDC email")
    org_id, separator, secret = payload.token.partition(".")
    if not separator or not secret or len(org_id) != 36:
        raise HTTPException(400, "Invalid invitation token")
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    invitation = db.scalar(select(OrganisationInvitation).where(
        OrganisationInvitation.org_id == org_id,
        OrganisationInvitation.token_hash == hashlib.sha256(payload.token.encode()).hexdigest()))
    if not invitation:
        raise HTTPException(404, "Invitation not found")
    now = datetime.now(timezone.utc)
    expiry = invitation.expires_at.replace(tzinfo=timezone.utc)
    if invitation.accepted_at or invitation.revoked_at or expiry <= now:
        raise HTTPException(410, "Invitation is no longer valid")
    if normalise_email(principal.email) != invitation.email:
        raise HTTPException(403, "This invitation was issued to a different email address")
    if db.scalar(select(OrganisationMembership).where(
        OrganisationMembership.org_id == org_id, OrganisationMembership.user_id == principal.user_id)):
        raise HTTPException(409, "You are already a member of this organisation")
    invitation.accepted_at = now
    membership = OrganisationMembership(
        id=str(uuid4()), org_id=org_id, user_id=principal.user_id,
        issuer=principal.issuer, subject=principal.subject,
        email=normalise_email(principal.email), role=invitation.role)
    db.add(membership)
    audit(db, org_id, "membership.invitation_accepted", "organisation_membership",
          membership.id, {"role": invitation.role})
    db.commit()
    return {"organisation_id": org_id, "role": membership.role, "message": "Invitation accepted"}


@app.delete("/api/v1/organisations/{org_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(org_id: str, invitation_id: str,
    principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    set_user_context(db, principal.user_id)
    set_tenant_context(db, org_id)
    org = db.get(Organisation, org_id)
    if not org:
        raise HTTPException(404, "Organisation not found")
    require_org_admin(org, principal, db)
    invitation = db.scalar(select(OrganisationInvitation).where(
        OrganisationInvitation.org_id == org_id, OrganisationInvitation.id == invitation_id))
    if not invitation:
        raise HTTPException(404, "Invitation not found")
    if invitation.accepted_at:
        raise HTTPException(409, "An accepted invitation cannot be revoked")
    invitation.revoked_at = datetime.now(timezone.utc)
    audit(db, org_id, "membership.invitation_revoked", "organisation_invitation", invitation.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


def validate_application_manifest(config: dict, org_id: str, db: Session):
    if not isinstance(config, dict):
        raise HTTPException(422, "Application manifest must be a JSON object")
    schema_version = config.get("schemaVersion", "1.0")
    if schema_version != "1.0":
        raise HTTPException(422, "Unsupported application manifest schemaVersion")
    pages = config.get("pages", [])
    if not isinstance(pages, list) or len(pages) > 30:
        raise HTTPException(422, "Application pages must be an array with at most 30 entries")
    allowed_pages = {"dashboard", "data-list", "data-form"}
    allowed_components = {"heading", "text", "metric", "data-table", "data-form", "button"}
    object_keys = {
        item.key for item in db.scalars(select(DataObject).where(DataObject.org_id == org_id)).all()
    }
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise HTTPException(422, f"Page {page_index} must be an object")
        if page.get("type", "dashboard") not in allowed_pages:
            raise HTTPException(422, f"Unsupported page type at position {page_index}")
        source = page.get("dataSource")
        if source and source not in object_keys:
            raise HTTPException(422, f"Page {page_index} references unknown data model '{source}'")
        components = page.get("components", [])
        if not isinstance(components, list) or len(components) > 100:
            raise HTTPException(422, f"Page {page_index} must have at most 100 components")
        for component_index, component in enumerate(components, start=1):
            if not isinstance(component, dict) or component.get("type") not in allowed_components:
                raise HTTPException(422, f"Unsupported component at page {page_index}, position {component_index}")
            props = component.get("props", {})
            if not isinstance(props, dict) or len(str(props)) > 8000:
                raise HTTPException(422, "Component props must be a small JSON object")
            if component.get("binding"):
                binding = component["binding"]
                if not isinstance(binding, dict) or binding.get("object") not in object_keys:
                    raise HTTPException(422, "Component data binding references an unknown data model")
            action = component.get("action")
            if action:
                if not isinstance(action, dict) or action.get("type") != "workflow.run":
                    raise HTTPException(422, "Only the governed workflow.run action is currently supported")
                workflow_id = action.get("workflowId")
                workflow = db.scalar(select(Workflow).where(
                    Workflow.id == workflow_id, Workflow.org_id == org_id, Workflow.enabled.is_(True)
                ))
                if not workflow:
                    raise HTTPException(422, "Workflow actions must reference an enabled workflow in this organisation")
                action_input = action.get("input", {})
                if not isinstance(action_input, dict) or len(str(action_input)) > 4000:
                    raise HTTPException(422, "Workflow action input must be a small JSON object")
    return config


@app.post("/api/v1/apps", dependencies=[Depends(require_token)], status_code=201)
def create_app(payload: AppIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    validate_application_manifest(payload.config, org.id, db)
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


@app.get("/apps/{app_id}/studio")
def application_studio(app_id: str):
    """Serve the visual application editor; API requests enforce tenant membership."""
    return FileResponse(ROOT / "static" / "app-studio.html")


@app.get("/apps/{app_id}/preview")
def application_preview(app_id: str):
    """Serve the declarative application runtime shell; tenant access is checked by its API."""
    return FileResponse(ROOT / "static" / "app-runtime.html")


@app.get("/api/v1/apps/{app_id}/runtime", dependencies=[Depends(require_token)])
def get_application_runtime(
    app_id: str,
    org: Organisation = Depends(org_scope),
    db: Session = Depends(get_db),
):
    item = db.scalar(select(Application).where(
        Application.id == app_id, Application.org_id == org.id
    ))
    if not item:
        raise HTTPException(404, "Application not found")
    config = item.config if isinstance(item.config, dict) else {}
    objects = db.scalars(
        select(DataObject).where(DataObject.org_id == org.id)
    ).all()
    object_index = {obj.key: {
        "id": obj.id, "key": obj.key, "label": obj.label, "schema": obj.schema_json
    } for obj in objects}
    pages = config.get("pages", [])
    if not isinstance(pages, list) or len(pages) > 30:
        raise HTTPException(422, "Application pages must be an array with at most 30 entries")
    for page in pages:
        if not isinstance(page, dict) or page.get("type", "dashboard") not in {
            "dashboard", "data-list", "data-form"
        }:
            raise HTTPException(422, "Unsupported application page. Supported types: dashboard, data-list, data-form")
    return {
        "id": item.id, "name": item.name, "description": item.description,
        "status": item.status, "version": item.version,
        "navigation": config.get("navigation", []),
        "pages": pages,
        "objects": object_index,
        "workflows": [
            {"id": workflow.id, "name": workflow.name, "enabled": workflow.enabled}
            for workflow in db.scalars(select(Workflow).where(
                Workflow.org_id == org.id, Workflow.enabled.is_(True)
            )).all()
        ],
        "organisation": {"id": org.id, "name": org.name},
    }



@app.put("/api/v1/apps/{app_id}", dependencies=[Depends(require_token)])
def update_app(
    app_id: str, payload: AppUpdateIn,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    item = db.scalar(select(Application).where(
        Application.id == app_id, Application.org_id == org.id
    ))
    if not item:
        raise HTTPException(404, "Application not found")
    if item.version != payload.expected_version:
        raise HTTPException(409, "Application version changed. Reload before saving.")
    validate_application_manifest(payload.config, org.id, db)
    item.config = payload.config
    if payload.name is not None:
        item.name = payload.name
    if payload.description is not None:
        item.description = payload.description
    item.version += 1
    audit(db, org.id, "application.updated", "application", item.id, {"version": item.version})
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "description": item.description,
            "config": item.config, "status": item.status, "version": item.version}


@app.get("/api/v1/apps/{app_id}/releases", dependencies=[Depends(require_token)])
def list_app_releases(
    app_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    item = db.scalar(select(Application.id).where(
        Application.id == app_id, Application.org_id == org.id
    ))
    if not item:
        raise HTTPException(404, "Application not found")
    releases = db.scalars(select(ApplicationRelease).where(
        ApplicationRelease.app_id == app_id, ApplicationRelease.org_id == org.id
    ).order_by(ApplicationRelease.version.desc(), ApplicationRelease.created_at.desc())).all()
    return [{"id": release.id, "version": release.version, "environment": release.environment,
             "status": release.status, "created_at": release.created_at}
            for release in releases]


@app.post("/api/v1/apps/{app_id}/releases", dependencies=[Depends(require_token)], status_code=201)
def create_app_release(
    app_id: str, payload: ReleaseIn,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    item = db.scalar(select(Application).where(
        Application.id == app_id, Application.org_id == org.id
    ))
    if not item:
        raise HTTPException(404, "Application not found")
    validate_application_manifest(item.config, org.id, db)
    item.version += 1
    release = ApplicationRelease(
        id=str(uuid4()), org_id=org.id, app_id=item.id, version=item.version,
        environment=payload.environment, status="ready", manifest=item.config,
    )
    db.add(release)
    if payload.environment == "production":
        item.status = "published"
    audit(db, org.id, "application.released", "application_release", release.id,
          {"app_id": item.id, "version": release.version, "environment": release.environment})
    db.commit()
    return {"id": release.id, "app_id": item.id, "version": release.version,
            "environment": release.environment, "status": release.status}


@app.get("/api/v1/apps/{app_id}/releases/{release_id}", dependencies=[Depends(require_token)])
def get_app_release(
    app_id: str, release_id: str,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    release = db.scalar(select(ApplicationRelease).where(
        ApplicationRelease.id == release_id, ApplicationRelease.app_id == app_id,
        ApplicationRelease.org_id == org.id,
    ))
    if not release:
        raise HTTPException(404, "Application release not found")
    return {"id": release.id, "app_id": release.app_id, "version": release.version,
            "environment": release.environment, "status": release.status,
            "manifest": release.manifest, "created_at": release.created_at}


@app.post("/api/v1/apps/{app_id}/publish", dependencies=[Depends(require_token)])
def publish_app(app_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)):
    item = db.scalar(select(Application).where(Application.id == app_id, Application.org_id == org.id))
    if not item:
        raise HTTPException(404, "Application not found")
    validate_application_manifest(item.config, org.id, db)
    item.version += 1
    release = ApplicationRelease(
        id=str(uuid4()), org_id=org.id, app_id=item.id, version=item.version,
        environment="production", status="ready", manifest=item.config,
    )
    db.add(release)
    item.status = "published"
    audit(db, org.id, "application.published", "application", item.id,
          {"version": item.version, "release_id": release.id, "environment": "production"})
    db.commit()
    return {"id": item.id, "status": item.status, "version": item.version, "release_id": release.id}


def validate_workflow_definition(definition: dict):
    steps = definition.get("steps", [])
    if not isinstance(steps, list) or len(steps) > 50:
        raise HTTPException(422, "Workflow must contain a steps array with at most 50 steps")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or step.get("type") not in {"manual_approval", "log"}:
            raise HTTPException(422, f"Unsupported step at position {index}. Supported steps: log, manual_approval")
        if step["type"] == "log":
            message = step.get("message", "")
            if not isinstance(message, str) or len(message) > 2000:
                raise HTTPException(422, f"Log step {index} requires a message of at most 2000 characters")
        if step["type"] == "manual_approval":
            label = step.get("label", "Approval required")
            if not isinstance(label, str) or len(label) > 200:
                raise HTTPException(422, f"Approval step {index} label must be at most 200 characters")
    return steps


def advance_workflow_run(db: Session, org_id: str, workflow: Workflow, run: WorkflowRun):
    steps = workflow.definition.get("steps", [])
    while run.current_step < len(steps):
        index = run.current_step
        step = steps[index]
        if step["type"] == "log":
            results = list(run.step_results or [])
            results.append({
                "step": index, "type": "log", "status": "completed",
                "message": step.get("message", ""), "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            run.step_results = results
            run.current_step += 1
            continue
        if step["type"] == "manual_approval":
            run.status = "waiting_approval"
            results = list(run.step_results or [])
            results.append({
                "step": index, "type": "manual_approval", "status": "waiting",
                "label": step.get("label", "Approval required"),
                "requested_at": datetime.now(timezone.utc).isoformat(),
            })
            run.step_results = results
            audit(db, org_id, "workflow_run.waiting_approval", "workflow_run", run.id, {"step": index})
            return
        run.status = "failed"
        run.error = f"Unsupported step type at position {index + 1}"
        return
    run.status = "succeeded"
    audit(db, org_id, "workflow_run.succeeded", "workflow_run", run.id, {"steps": len(steps)})


@app.post("/api/v1/workflows", dependencies=[Depends(require_token)], status_code=201)
def create_workflow(
    payload: WorkflowIn, org: Organisation = Depends(org_scope), db: Session = Depends(get_db)
):
    steps = validate_workflow_definition(payload.definition)
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
    validate_workflow_definition(wf.definition)
    wf.enabled = True
    audit(db, org.id, "workflow.enabled", "workflow", wf.id)
    db.commit()
    return {"id": wf.id, "enabled": True}


@app.post("/api/v1/workflows/{workflow_id}/runs", dependencies=[Depends(require_token)], status_code=201)
def start_workflow_run(
    workflow_id: str, payload: WorkflowRunIn,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    workflow = db.scalar(select(Workflow).where(
        Workflow.id == workflow_id, Workflow.org_id == org.id
    ))
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if not workflow.enabled:
        raise HTTPException(409, "Enable the workflow before starting a run")
    steps = validate_workflow_definition(workflow.definition)
    if payload.idempotency_key:
        existing = db.scalar(select(WorkflowRun).where(
            WorkflowRun.org_id == org.id,
            WorkflowRun.idempotency_key == payload.idempotency_key,
        ))
        if existing:
            if existing.workflow_id != workflow.id:
                raise HTTPException(409, "Idempotency key was already used for another workflow")
            return workflow_run_response(existing)
    run = WorkflowRun(
        id=str(uuid4()), org_id=org.id, workflow_id=workflow.id,
        status="running", input=payload.input, step_results=[],
        current_step=0, idempotency_key=payload.idempotency_key,
    )
    db.add(run)
    db.flush()
    audit(db, org.id, "workflow_run.started", "workflow_run", run.id, {"workflow_id": workflow.id})
    advance_workflow_run(db, org.id, workflow, run)
    db.commit()
    db.refresh(run)
    return workflow_run_response(run)


def workflow_run_response(run: WorkflowRun):
    return {
        "id": run.id, "workflow_id": run.workflow_id, "status": run.status,
        "input": run.input, "current_step": run.current_step,
        "step_results": run.step_results, "error": run.error,
        "created_at": run.created_at, "updated_at": run.updated_at,
    }


@app.get("/api/v1/workflows/{workflow_id}/runs", dependencies=[Depends(require_token)])
def list_workflow_runs(
    workflow_id: str, limit: int = 50, offset: int = 0,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    if not db.scalar(select(Workflow.id).where(Workflow.id == workflow_id, Workflow.org_id == org.id)):
        raise HTTPException(404, "Workflow not found")
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(422, "limit must be 1-100 and offset must be non-negative")
    runs = db.scalars(select(WorkflowRun).where(
        WorkflowRun.workflow_id == workflow_id, WorkflowRun.org_id == org.id
    ).order_by(WorkflowRun.created_at.desc()).limit(limit).offset(offset)).all()
    return [workflow_run_response(run) for run in runs]


@app.get("/api/v1/workflow-runs/{run_id}", dependencies=[Depends(require_token)])
def get_workflow_run(
    run_id: str, org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    run = db.scalar(select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.org_id == org.id
    ))
    if not run:
        raise HTTPException(404, "Workflow run not found")
    return workflow_run_response(run)


@app.post("/api/v1/workflow-runs/{run_id}/approval", dependencies=[Depends(require_token)])
def decide_workflow_approval(
    run_id: str, payload: WorkflowApprovalIn,
    org: Organisation = Depends(org_scope), db: Session = Depends(get_db),
):
    run = db.scalar(select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.org_id == org.id
    ))
    if not run:
        raise HTTPException(404, "Workflow run not found")
    if run.status != "waiting_approval":
        raise HTTPException(409, "Workflow run is not waiting for approval")
    workflow = db.scalar(select(Workflow).where(
        Workflow.id == run.workflow_id, Workflow.org_id == org.id
    ))
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    pending = next((item for item in reversed(run.step_results)
                    if item.get("type") == "manual_approval" and item.get("status") == "waiting"), None)
    if not pending:
        raise HTTPException(409, "No pending approval step exists")
    results = [dict(item) for item in (run.step_results or [])]
    pending = next(item for item in reversed(results)
                   if item.get("type") == "manual_approval" and item.get("status") == "waiting")
    pending["status"] = "approved" if payload.approved else "rejected"
    pending["comment"] = payload.comment
    pending["decided_at"] = datetime.now(timezone.utc).isoformat()
    run.step_results = results
    if payload.approved:
        run.current_step += 1
        run.status = "running"
        advance_workflow_run(db, org.id, workflow, run)
    else:
        run.status = "failed"
        run.error = "Workflow stopped because an approval was rejected"
        audit(db, org.id, "workflow_run.rejected", "workflow_run", run.id, {"step": pending["step"]})
    db.commit()
    db.refresh(run)
    return workflow_run_response(run)


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

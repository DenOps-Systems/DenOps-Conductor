# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, case, update
from sqlalchemy.exc import IntegrityError
from app.core.security import admin, reporter
from app.api.infrastructure import router as infrastructure_router
from app.core.database import get_db
from app.models import Project, BuilderVM, Repair, AlphaSlot, Release, Migration, AuditEvent, now
from app.schemas import ProjectInput, VMInput, RepairInput
from app.services.events import emit
from app.services.source import source_archive

app = FastAPI(title="DenOps Conductor", version="0.3.0")
app.include_router(infrastructure_router)

@app.middleware("http")
async def secure_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/health")
def health():
    return {"status": "ok", "service": "denops-conductor"}

@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(Path(__file__).parent / "static/index.html")

@app.get("/static/{filename}", include_in_schema=False)
def asset(filename: str):
    if filename not in {"app.js", "style.css", "logo.png"}:
        raise HTTPException(404)
    return FileResponse(Path(__file__).parent / "static" / filename)

def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}

def audit(db, action, kind, identity, detail="", actor="admin"):
    db.add(AuditEvent(actor=actor, action=action, entity_type=kind, entity_id=identity, detail=detail))

def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicting project, VM, or record")

def project_exists(db, identity):
    if not db.get(Project, identity):
        raise HTTPException(404, "Project not found")

@app.get("/api/overview", dependencies=[Depends(admin)])
def overview(db=Depends(get_db)):
    result = {}
    for key, model in [("projects", Project), ("builders", BuilderVM), ("repairs", Repair), ("releases", Release), ("migrations", Migration), ("audit", AuditEvent)]:
        result[key] = [serialize(r) for r in db.scalars(select(model).order_by(model.id.desc()).limit(500))]
    slot = db.get(AlphaSlot, 1)
    result["alpha"] = {"active_repair_id": slot.repair_id if slot else None, "status": "reserved" if slot and slot.repair_id else "idle", "infrastructure_verified": False}
    return result

@app.post("/api/projects", dependencies=[Depends(admin)], status_code=201)
def create_project(payload: ProjectInput, db=Depends(get_db)):
    row = Project(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Project slug already exists")
    audit(db, "project-created", "project", row.id)
    commit(db)
    return serialize(row)

@app.put("/api/projects/{identity}", dependencies=[Depends(admin)])
def edit_project(identity: int, payload: ProjectInput, db=Depends(get_db)):
    project_exists(db, identity)
    row = db.get(Project, identity)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, "project-updated", "project", identity)
    commit(db)
    return serialize(row)

@app.post("/api/builders", dependencies=[Depends(admin)], status_code=201)
def create_builder(payload: VMInput, db=Depends(get_db)):
    project_exists(db, payload.project_id)
    row = BuilderVM(**payload.model_dump())
    db.add(row)
    audit(db, "builder-configured", "project", payload.project_id)
    commit(db)
    return serialize(row)

def ingest(payload, db, actor):
    # Serialize deduplication and queue writes across SQLite workers.
    db.execute(update(AlphaSlot).where(AlphaSlot.id == 1).values(id=1))
    project_exists(db, payload.project_id)
    row = None
    if payload.error_signature:
        row = db.scalar(select(Repair).where(Repair.project_id == payload.project_id, Repair.error_signature == payload.error_signature, Repair.state.not_in(["resolved", "failed"])))
    if row:
        row.occurrence_count += 1
        row.last_seen = now()
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        if rank[payload.severity] < rank[row.severity]:
            row.severity = payload.severity
    else:
        row = Repair(**payload.model_dump())
        db.add(row)
        db.flush()
        emit(db, "repair.queued", "repair", row.id, {"project_id": row.project_id, "state": row.state})
    db.flush()
    audit(db, "error-reported", "repair", row.id, actor=actor)
    commit(db)
    return serialize(row)

@app.post("/api/repairs", dependencies=[Depends(admin)], status_code=201)
def create_repair(payload: RepairInput, db=Depends(get_db)):
    return ingest(payload, db, "admin")

@app.post("/api/reports", dependencies=[Depends(reporter)], status_code=201)
def report(payload: RepairInput, db=Depends(get_db)):
    return ingest(payload, db, "reporter")

@app.post("/api/queue/reserve", dependencies=[Depends(admin)])
def reserve(db=Depends(get_db)):
    # This is a reservation only: VM start requires live power checks and exact Git synchronization.
    db.execute(update(AlphaSlot).where(AlphaSlot.id == 1).values(id=1))
    slot = db.get(AlphaSlot, 1)
    if slot is None:
        raise HTTPException(503, "Run database migrations first")
    if slot.repair_id:
        raise HTTPException(409, "Alpha already has an active repair")
    priority = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=Repair.severity, else_=4)
    row = db.scalar(select(Repair).join(BuilderVM, BuilderVM.project_id == Repair.project_id).where(Repair.state == "queued").order_by(priority, Repair.first_seen, Repair.id))
    if not row:
        raise HTTPException(409, "No queued repair with a configured builder")
    row.builder_id = db.scalar(select(BuilderVM.id).where(BuilderVM.project_id == row.project_id))
    row.state = "preparing"
    slot.repair_id = row.id
    audit(db, "repair-reserved", "repair", row.id)
    commit(db)
    return serialize(row)

@app.get("/api/repairs/{identity}", dependencies=[Depends(admin)])
def repair_detail(identity: int, db=Depends(get_db)):
    row = db.get(Repair, identity)
    if not row:
        raise HTTPException(404)
    return {"repair": serialize(row), "events": [serialize(r) for r in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "repair", AuditEvent.entity_id == identity).order_by(AuditEvent.id))]}

@app.get("/api/releases/{identity}", dependencies=[Depends(admin)])
def release_detail(identity: int, db=Depends(get_db)):
    row = db.get(Release, identity)
    if not row:
        raise HTTPException(404)
    return {"release": serialize(row), "migrations": [serialize(r) for r in db.scalars(select(Migration).where(Migration.project_id == row.project_id, Migration.release_commit == row.commit))], "events": [serialize(r) for r in db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "release", AuditEvent.entity_id == identity))]}


@app.get("/license", include_in_schema=False)
def license_text():
    return FileResponse(Path(__file__).resolve().parent.parent / "LICENSE", media_type="text/plain")

@app.get("/source", include_in_schema=False)
def corresponding_source():
    return Response(source_archive(), media_type="application/gzip", headers={"Content-Disposition": 'attachment; filename="denops-conductor-source.tar.gz"'})

# SPDX-License-Identifier: AGPL-3.0-only
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.database import get_db
from app.core.security import admin
from app.models import InfrastructureResource, MonitorCheck, MonitorObservation, Project, BuilderVM, AuditEvent
from app.services.watchdog import ResourceKind, ExpectedState, ProbeKind, ProbeRegistry, ProxmoxVMProbe, observation_view
from app.services.proxmox import Proxmox
from app.services.events import emit

router = APIRouter(prefix='/api/infrastructure', tags=['infrastructure'], dependencies=[Depends(admin)])
registry = ProbeRegistry()
registry.register(ProbeKind.PROXMOX_VM, ProxmoxVMProbe(Proxmox))

class ResourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ResourceKind
    project_id: int | None = Field(default=None, gt=0)
    builder_id: int | None = Field(default=None, gt=0)
    node: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]+$', max_length=100)
    vm_id: int | None = Field(default=None, gt=0)
    expected_state: ExpectedState = ExpectedState.POLICY_CONTROLLED

    @model_validator(mode='after')
    def vm_identity(self):
        if self.kind == ResourceKind.PROXMOX_VM and (not self.node or not self.vm_id):
            raise ValueError('Proxmox VMs require node and VM ID')
        if self.kind != ResourceKind.PROXMOX_VM and (self.vm_id or self.builder_id or self.expected_state != ExpectedState.POLICY_CONTROLLED):
            raise ValueError('VM settings require a Proxmox VM resource')
        return self

class CheckInput(BaseModel):
    resource_id: int = Field(gt=0)
    probe_kind: ProbeKind
    freshness_seconds: int = Field(default=300, ge=30, le=86400)

def fields(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}

def save(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Resource or monitoring check already exists or conflicts')

@router.get('')
def inventory(db=Depends(get_db)):
    resources = list(db.scalars(select(InfrastructureResource).order_by(InfrastructureResource.id)))
    checks = list(db.scalars(select(MonitorCheck).order_by(MonitorCheck.id)))
    result = []
    for check in checks:
        last = db.scalar(select(MonitorObservation).where(MonitorObservation.check_id == check.id).order_by(MonitorObservation.id.desc()).limit(1))
        result.append({**fields(check), 'observation': observation_view(last, check.freshness_seconds)})
    return {'resources': [fields(row) for row in resources], 'checks': result, 'resource_kinds': list(ResourceKind), 'probe_kinds': list(ProbeKind), 'expected_states': list(ExpectedState), 'automatic_recovery': False}

@router.post('/resources', status_code=201)
def create_resource(payload: ResourceInput, db=Depends(get_db)):
    if payload.project_id and not db.get(Project, payload.project_id):
        raise HTTPException(404, 'Project not found')
    if payload.builder_id:
        builder = db.get(BuilderVM, payload.builder_id)
        if not builder:
            raise HTTPException(404, 'Builder not found')
        if builder.node != payload.node or builder.vm_id != payload.vm_id or builder.project_id != payload.project_id:
            raise HTTPException(422, 'Resource identity must match its project builder')
    row = InfrastructureResource(**payload.model_dump())
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Builder already has an infrastructure resource')
    db.add(AuditEvent(actor='admin', action='infrastructure-resource-created', entity_type='infrastructure-resource', entity_id=row.id))
    save(db)
    return fields(row)

@router.post('/checks', status_code=201)
def create_check(payload: CheckInput, db=Depends(get_db)):
    if not db.get(InfrastructureResource, payload.resource_id):
        raise HTTPException(404, 'Resource not found')
    row = MonitorCheck(**payload.model_dump())
    db.add(row)
    db.add(AuditEvent(actor='admin', action='monitor-check-configured', entity_type='infrastructure-resource', entity_id=payload.resource_id))
    save(db)
    return fields(row)

@router.post('/checks/{identity}/run')
def run_check(identity: int, db=Depends(get_db)):
    check = db.get(MonitorCheck, identity)
    if not check:
        raise HTTPException(404, 'Monitoring check not found')
    if not check.enabled:
        raise HTTPException(409, 'Monitoring check disabled')
    resource = db.get(InfrastructureResource, check.resource_id)
    result = registry.observe(ProbeKind(check.probe_kind), resource)
    observation = MonitorObservation(check_id=check.id, status=result.status, summary=result.summary)
    db.add(observation)
    emit(db, "monitor.observed", "monitor-check", check.id, {"status": result.status, "resource_id": resource.id})
    db.add(AuditEvent(actor='admin', action='monitor-check-observed', entity_type='monitor-check', entity_id=check.id, detail=result.status))
    save(db)
    return fields(observation)

@router.get('/checks/{identity}/history')
def history(identity: int, db=Depends(get_db)):
    if not db.get(MonitorCheck, identity):
        raise HTTPException(404, 'Monitoring check not found')
    return [fields(row) for row in db.scalars(select(MonitorObservation).where(MonitorObservation.check_id == identity).order_by(MonitorObservation.id.desc()).limit(100))]

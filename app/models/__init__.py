# SPDX-License-Identifier: AGPL-3.0-only
from datetime import datetime, timezone
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def now():
    return datetime.now(timezone.utc)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    repository: Mapped[str]
    production_branch: Mapped[str] = mapped_column(default="main")
    production_server: Mapped[str] = mapped_column(default="")
    application_path: Mapped[str] = mapped_column(default="")
    service_name: Mapped[str] = mapped_column(default="")
    port: Mapped[int | None]
    hostname: Mapped[str] = mapped_column(default="")
    health_endpoint: Mapped[str] = mapped_column(default="")
    production_database_ref: Mapped[str] = mapped_column(default="")
    test_database_ref: Mapped[str] = mapped_column(default="")
    migration_directory: Mapped[str] = mapped_column(default="db/migrations")
    deployment_policy: Mapped[str] = mapped_column(default="approval-required")
    automatic_repair: Mapped[bool] = mapped_column(default=False)
    production_commit: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=now)

class BuilderVM(Base):
    __tablename__ = "builder_vms"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    vm_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
    node: Mapped[str]
    power_state: Mapped[str] = mapped_column(default="unknown")
    readiness: Mapped[str] = mapped_column(default="unverified")
    last_sync: Mapped[datetime | None]
    last_final_sync: Mapped[datetime | None]

class Repair(Base):
    __tablename__ = "repairs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    severity: Mapped[str]
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    error_signature: Mapped[str | None]
    stack_trace: Mapped[str] = mapped_column(Text, default="")
    component: Mapped[str] = mapped_column(default="")
    occurrence_count: Mapped[int] = mapped_column(default=1)
    first_seen: Mapped[datetime] = mapped_column(default=now)
    last_seen: Mapped[datetime] = mapped_column(default=now)
    production_release: Mapped[str] = mapped_column(default="")
    production_commit: Mapped[str | None]
    builder_commit: Mapped[str | None]
    correlation_ids: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(default="queued")
    builder_id: Mapped[int | None] = mapped_column(ForeignKey("builder_vms.id"))
    notes: Mapped[str] = mapped_column(Text, default="")

class AlphaSlot(Base):
    __tablename__ = "alpha_slot"
    id: Mapped[int] = mapped_column(primary_key=True)
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repairs.id"), unique=True)

class Release(Base):
    __tablename__ = "releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repairs.id"))
    builder_id: Mapped[int | None] = mapped_column(ForeignKey("builder_vms.id"))
    release_number: Mapped[str]
    commit: Mapped[str]
    previous_commit: Mapped[str | None]
    migration_start: Mapped[int | None]
    migration_end: Mapped[int | None]
    started_at: Mapped[datetime] = mapped_column(default=now)
    ended_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(default="pending-approval")
    health_result: Mapped[str] = mapped_column(default="unverified")
    restoration_status: Mapped[str] = mapped_column(default="not-requested")
    final_sync_status: Mapped[str] = mapped_column(default="not-requested")
    failure: Mapped[str] = mapped_column(Text, default="")

class Migration(Base):
    __tablename__ = "project_migrations"
    __table_args__ = (UniqueConstraint("project_id", "migration_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    migration_number: Mapped[int]
    filename: Mapped[str]
    checksum: Mapped[str]
    state: Mapped[str] = mapped_column(default="pending")
    applied_at: Mapped[datetime | None]
    release_commit: Mapped[str | None]

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=now)
    actor: Mapped[str]
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[int | None]
    detail: Mapped[str] = mapped_column(Text, default="")

class InfrastructureResource(Base):
    __tablename__ = "infrastructure_resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    kind: Mapped[str]
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    builder_id: Mapped[int | None] = mapped_column(ForeignKey("builder_vms.id"), unique=True)
    node: Mapped[str | None]
    vm_id: Mapped[int | None]
    desired_power: Mapped[str] = mapped_column(default="any")
    expected_state: Mapped[str] = mapped_column(default="policy-controlled")
    created_at: Mapped[datetime] = mapped_column(default=now)

class MonitorCheck(Base):
    __tablename__ = "monitor_checks"
    __table_args__ = (UniqueConstraint("resource_id", "probe_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("infrastructure_resources.id"))
    probe_kind: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    freshness_seconds: Mapped[int] = mapped_column(default=300)
    created_at: Mapped[datetime] = mapped_column(default=now)

class MonitorObservation(Base):
    __tablename__ = "monitor_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("monitor_checks.id"), index=True)
    status: Mapped[str]
    summary: Mapped[str]
    observed_at: Mapped[datetime] = mapped_column(default=now, index=True)


class DomainEvent(Base):
    __tablename__ = "domain_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=now)
    event_type: Mapped[str] = mapped_column(index=True)
    entity_type: Mapped[str]
    entity_id: Mapped[int]
    correlation_id: Mapped[str | None]
    schema_version: Mapped[int] = mapped_column(default=1)
    payload: Mapped[str] = mapped_column(Text, default="{}")

class InfrastructureIncident(Base):
    __tablename__ = "infrastructure_incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("infrastructure_resources.id"))
    check_id: Mapped[int | None] = mapped_column(ForeignKey("monitor_checks.id"))
    repair_id: Mapped[int | None] = mapped_column(ForeignKey("repairs.id"))
    signature: Mapped[str]
    state: Mapped[str] = mapped_column(default="open")
    first_seen: Mapped[datetime] = mapped_column(default=now)
    last_seen: Mapped[datetime] = mapped_column(default=now)
    resolved_at: Mapped[datetime | None]

class RecoveryActionRecord(Base):
    __tablename__ = "recovery_action_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("infrastructure_incidents.id"))
    action: Mapped[str]
    status: Mapped[str] = mapped_column(default="proposed")
    approved_by: Mapped[str | None]
    requested_at: Mapped[datetime] = mapped_column(default=now)
    completed_at: Mapped[datetime | None]
    verification_result: Mapped[str] = mapped_column(default="unknown")

class ReportCredential(Base):
    __tablename__ = "report_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str]
    token_digest: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    revoked_at: Mapped[datetime | None]

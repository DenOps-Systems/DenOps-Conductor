# SPDX-License-Identifier: AGPL-3.0-only
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    repository: str = Field(min_length=1, max_length=500)
    production_branch: str = Field(default="main", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$", max_length=200)
    production_server: str = Field(default="", max_length=255)
    application_path: str = Field(default="", max_length=500)
    service_name: str = Field(default="", pattern=r"^[A-Za-z0-9_.@-]*$", max_length=200)
    port: int | None = Field(default=None, ge=1, le=65535)
    hostname: str = Field(default="", max_length=255)
    health_endpoint: str = Field(default="", max_length=500)
    production_database_ref: str = Field(default="", pattern=r"^[A-Z0-9_]*$", max_length=120)
    test_database_ref: str = Field(default="", pattern=r"^[A-Z0-9_]*$", max_length=120)
    migration_directory: str = Field(default="db/migrations", max_length=250)
    deployment_policy: Literal["automatic", "approval-required", "database-approval", "high-risk-approval"] = "approval-required"
    automatic_repair: bool = False

    @field_validator("repository")
    @classmethod
    def repository_safe(cls, value):
        if not value.startswith(("https://", "git@")) or "\n" in value or "\r" in value:
            raise ValueError("Use an HTTPS or SSH Git repository")
        if value.startswith("https://") and "@" in value:
            raise ValueError("Store credentials outside the repository URL")
        return value

    @field_validator("migration_directory")
    @classmethod
    def relative_path(cls, value):
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("Migration directory must be a relative path without traversal")
        return value

class VMInput(BaseModel):
    project_id: int = Field(gt=0)
    vm_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    node: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=100)

class RepairInput(BaseModel):
    project_id: int = Field(gt=0)
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    title: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=20000)
    error_signature: str | None = Field(default=None, min_length=1, max_length=500)
    stack_trace: str = Field(default="", max_length=30000)
    component: str = Field(default="", max_length=250)
    production_release: str = Field(default="", max_length=200)
    production_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    correlation_ids: str = Field(default="", max_length=4000)

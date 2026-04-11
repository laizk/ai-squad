from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class EntityType(str, Enum):
    project = "project"
    team_member = "team_member"
    project_assignment = "project_assignment"
    milestone = "milestone"
    task = "task"


class ReasonCategory(str, Enum):
    initial_creation = "initial_creation"
    scope_change = "scope_change"
    prompt_tuning = "prompt_tuning"
    fix = "fix"
    rollback = "rollback"
    human_override = "human_override"
    policy_change = "policy_change"
    retry = "retry"
    other = "other"


class ReasonInput(BaseModel):
    category: ReasonCategory
    detail: str = Field(min_length=20)
    references: list[str] = Field(default_factory=list)


class ProjectBase(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: ProjectStatus | None = None
    github_org: str | None = Field(default=None, max_length=255)
    github_repo: str | None = Field(default=None, max_length=255)
    github_project_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class ProjectCreate(ProjectBase):
    name: str = Field(min_length=1, max_length=255)
    reason: ReasonInput


class ProjectUpdate(ProjectBase):
    reason: ReasonInput


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    status: ProjectStatus
    github_org: str | None
    github_repo: str | None
    github_project_id: str | None
    current_version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[ProjectResponse]


class RevisionReason(BaseModel):
    category: ReasonCategory
    detail: str
    references: list[str]


class RevisionResponse(BaseModel):
    revision_number: int
    actor: str
    change_summary: str
    reason: RevisionReason
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any]
    created_at: datetime


class RevisionListResponse(BaseModel):
    entity_type: EntityType
    entity_id: UUID
    revisions: list[RevisionResponse]

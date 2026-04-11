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


class TeamMemberRole(str, Enum):
    pm = "pm"
    ux = "ux"
    dev_jr = "dev-jr"
    dev_sr = "dev-sr"
    qa = "qa"
    devops = "devops"
    judge = "judge"
    custom = "custom"


class ProviderType(str, Enum):
    ollama = "ollama"
    anthropic = "anthropic"
    openai = "openai"
    custom = "custom"


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


class TeamMemberBase(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: TeamMemberRole | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    skills: list[str] | None = None
    provider: ProviderType | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class TeamMemberCreate(TeamMemberBase):
    name: str = Field(min_length=1, max_length=255)
    role: TeamMemberRole
    display_name: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    reason: ReasonInput


class TeamMemberUpdate(TeamMemberBase):
    reason: ReasonInput


class TeamMemberResponse(BaseModel):
    id: UUID
    name: str
    role: TeamMemberRole
    display_name: str
    description: str | None
    skills: list[str]
    provider: ProviderType
    model: str
    is_active: bool
    current_version: int
    created_at: datetime
    updated_at: datetime


class TeamMemberListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[TeamMemberResponse]


class ProjectAssignmentCreate(BaseModel):
    team_member_id: UUID
    model_override: str | None = Field(default=None, max_length=255)
    provider_override: ProviderType | None = None
    reason: ReasonInput


class ProjectAssignmentUpdate(BaseModel):
    is_enabled: bool | None = None
    model_override: str | None = Field(default=None, max_length=255)
    provider_override: ProviderType | None = None
    disable_reason: str | None = None
    reason: ReasonInput


class ProjectAssignmentModelUpdate(BaseModel):
    model_override: str | None = Field(default=None, max_length=255)
    provider_override: ProviderType | None = None
    reason: ReasonInput


class ProjectAssignmentDelete(BaseModel):
    reason: ReasonInput


class ProjectAssignmentResponse(BaseModel):
    id: UUID
    project_id: UUID
    team_member_id: UUID
    is_enabled: bool
    provider_override: ProviderType | None
    model_override: str | None
    disabled_at: datetime | None
    disable_reason: str | None
    current_version: int
    created_at: datetime
    updated_at: datetime


class ProjectAssignmentListResponse(BaseModel):
    total: int
    items: list[ProjectAssignmentResponse]

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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


class MilestoneStatus(str, Enum):
    planned = "planned"
    in_progress = "in_progress"
    review = "review"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"


class TaskStatus(str, Enum):
    backlog = "backlog"
    queued = "queued"
    in_progress = "in_progress"
    review = "review"
    qa_check = "qa_check"
    judge_review = "judge_review"
    pending_human = "pending_human"
    done = "done"
    rejected = "rejected"
    rework = "rework"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class EntityType(str, Enum):
    project = "project"
    team_member = "team_member"
    project_assignment = "project_assignment"
    milestone = "milestone"
    task = "task"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    changes_requested = "changes_requested"


class EvidenceType(str, Enum):
    artifact = "artifact"
    test_result = "test_result"
    screenshot = "screenshot"
    log = "log"
    github_link = "github_link"
    other = "other"


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


class ApprovalEvidenceInput(BaseModel):
    evidence_type: EvidenceType
    artifact_id: UUID | None = None
    external_url: str | None = None
    description: str = Field(min_length=1, max_length=1000)


class ApprovalEvidenceResponse(BaseModel):
    id: UUID
    approval_id: UUID
    evidence_type: EvidenceType
    artifact_id: UUID | None
    external_url: str | None
    description: str
    created_at: datetime


class ApprovalCreate(BaseModel):
    entity_type: EntityType
    entity_id: UUID
    approved_revision_number: int = Field(ge=1)
    status: ApprovalStatus
    comment: str = Field(min_length=10)
    override_used: bool = False
    override_reason: str | None = None
    evidence: list[ApprovalEvidenceInput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_approval(self) -> "ApprovalCreate":
        if self.status == ApprovalStatus.pending:
            raise ValueError("Approval decisions must use approved, rejected, or changes_requested status")

        if self.override_used and not self.override_reason:
            raise ValueError("override_reason is required when override_used is true")

        if not self.override_used and self.override_reason is not None:
            raise ValueError("override_reason is only allowed when override_used is true")

        return self


class ApprovalResponse(BaseModel):
    id: UUID
    entity_type: EntityType
    entity_id: UUID
    approved_revision_number: int
    status: ApprovalStatus
    comment: str
    override_used: bool
    override_reason: str | None
    is_stale: bool
    stale_at: datetime | None
    decided_by: str
    decided_at: datetime
    created_at: datetime
    updated_at: datetime
    evidence: list[ApprovalEvidenceResponse]


class ApprovalListResponse(BaseModel):
    total: int
    items: list[ApprovalResponse]


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


class MilestoneBase(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: MilestoneStatus | None = None
    display_order: int | None = Field(default=None, ge=0)
    acceptance_criteria: list[str] | None = None
    due_date: date | None = None


class MilestoneCreate(MilestoneBase):
    title: str = Field(min_length=1, max_length=500)
    reason: ReasonInput


class MilestoneUpdate(MilestoneBase):
    reason: ReasonInput


class MilestoneResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: MilestoneStatus
    display_order: int
    acceptance_criteria: list[str]
    due_date: date | None
    current_version: int
    created_at: datetime
    updated_at: datetime


class MilestoneListResponse(BaseModel):
    total: int
    items: list[MilestoneResponse]


class TaskBase(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assigned_role: TeamMemberRole | None = None
    acceptance_criteria: list[str] | None = None
    display_order: int | None = Field(default=None, ge=0)


class TaskCreate(TaskBase):
    title: str = Field(min_length=1, max_length=500)
    reason: ReasonInput


class TaskUpdate(TaskBase):
    reason: ReasonInput


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    assigned_role: TeamMemberRole | None
    acceptance_criteria: list[str]
    display_order: int
    current_version: int
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    total: int
    items: list[TaskResponse]

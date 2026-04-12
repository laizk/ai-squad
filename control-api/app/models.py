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


# ── Runs ──────────────────────────────────────────────────────

class RunStatus(str, Enum):
    created = "created"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RunStepStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ArtifactType(str, Enum):
    spec = "spec"
    milestone_plan = "milestone_plan"
    tasks = "tasks"
    acceptance_criteria = "acceptance_criteria"
    ui_notes = "ui_notes"
    component_map = "component_map"
    ux_risks = "ux_risks"
    implementation_summary = "implementation_summary"
    code_diff = "code_diff"
    review_findings = "review_findings"
    refactor_summary = "refactor_summary"
    test_plan = "test_plan"
    test_results = "test_results"
    bug_list = "bug_list"
    docker_changes = "docker_changes"
    ci_changes = "ci_changes"
    runbook = "runbook"
    rubric_score = "rubric_score"
    recommendation = "recommendation"
    decision_log = "decision_log"
    dev_output = "dev_output"
    sandbox_result = "sandbox_result"
    other = "other"


WORKFLOW_STEPS: dict[str, list[tuple[str, bool]]] = {
    # (role, pause_after)
    "pm_planning":      [("pm", True)],
    "dev_cycle":        [
        ("dev-jr", False),
        ("dev-sr", False),
        ("qa", False),
        ("judge", False),
    ],
    "full_sequential":  [
        ("pm",     True),
        ("dev-jr", False),
        ("dev-sr", False),
        ("qa",     False),
        ("judge",  False),
    ],
}

OPTIONAL_ROLES_SKIPPED = ["ux", "devops"]


class RunCreate(BaseModel):
    project_id: UUID
    task_id: UUID | None = None
    workflow_type: str = Field(default="pm_planning", min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_workflow_type(self) -> "RunCreate":
        if self.workflow_type not in WORKFLOW_STEPS:
            raise ValueError(
                f"workflow_type must be one of: {', '.join(WORKFLOW_STEPS.keys())}"
            )
        return self


class RunStepResponse(BaseModel):
    id: UUID
    run_id: UUID
    role: str
    step_order: int
    status: RunStepStatus
    pause_after: bool
    output_artifact_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class RunResponse(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID | None
    status: RunStatus
    workflow_type: str
    trigger_actor: str
    idempotency_key: str
    steps: list[RunStepResponse]
    started_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    github_issue_number: int | None = None
    github_branch: str | None = None
    github_pr_number: int | None = None


class RunGithubRefUpdate(BaseModel):
    github_issue_number: int | None = None
    github_branch: str | None = None
    github_pr_number: int | None = None


class RunListResponse(BaseModel):
    total: int
    items: list[RunResponse]


class ArtifactResponse(BaseModel):
    id: UUID
    project_id: UUID
    run_id: UUID | None
    run_step_id: UUID | None
    role: str | None
    artifact_type: ArtifactType
    name: str
    version: int
    is_current: bool
    created_at: datetime


class ArtifactContentResponse(BaseModel):
    id: UUID
    artifact_type: ArtifactType
    name: str
    body: str
    created_at: datetime

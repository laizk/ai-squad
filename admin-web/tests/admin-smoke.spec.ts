import { expect, request as playwrightRequest, test } from "@playwright/test";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://localhost:8000";

type CleanupState = {
  projectId?: string;
  teamMemberId?: string;
};

let cleanupState: CleanupState = {};

function buildReason(detail: string) {
  return {
    category: "scope_change",
    detail,
    references: []
  };
}

function parseEntityId(href: string | null, segment: string) {
  if (!href) {
    throw new Error(`Missing ${segment} href.`);
  }

  const match = href.match(new RegExp(`/${segment}/([^/?#]+)`));
  if (!match?.[1]) {
    throw new Error(`Could not parse ${segment} id from href: ${href}`);
  }

  return match[1];
}

async function cleanupSmokeData(state: CleanupState) {
  const api = await playwrightRequest.newContext({
    baseURL: apiBaseURL,
    extraHTTPHeaders: {
      "Content-Type": "application/json"
    }
  });

  try {
    if (state.projectId && state.teamMemberId) {
      await api.delete(`/api/v1/projects/${state.projectId}/team/${state.teamMemberId}`, {
        data: {
          reason: buildReason(
            "Disabling the Playwright smoke-test assignment so the project staffing returns to a non-active validation state."
          )
        },
        failOnStatusCode: false
      });
    }

    if (state.teamMemberId) {
      await api.patch(`/api/v1/team-members/${state.teamMemberId}`, {
        data: {
          is_active: false,
          reason: buildReason(
            "Marking the Playwright smoke-test team member inactive after validation so roster counts stay clean."
          )
        },
        failOnStatusCode: false
      });
    }

    if (state.projectId) {
      await api.patch(`/api/v1/projects/${state.projectId}`, {
        data: {
          status: "archived",
          reason: buildReason(
            "Archiving the Playwright smoke-test project after validation so active workspace listings stay meaningful."
          )
        },
        failOnStatusCode: false
      });
    }
  } finally {
    await api.dispose();
  }
}

test.beforeEach(() => {
  cleanupState = {};
});

test.afterEach(async () => {
  await cleanupSmokeData(cleanupState);
});

test("admin web smoke flow covers project, team member, assignment, and revision diffs", async ({ page }) => {

  const uniqueToken = Date.now().toString();
  const projectName = `Playwright Smoke Project ${uniqueToken}`;
  const projectDescription = "Smoke path for create, review, assignment, and revision-diff validation.";
  const milestoneTitle = `Smoke Milestone ${uniqueToken}`;
  const taskTitle = `Smoke Task ${uniqueToken}`;
  const teamMemberName = `pw-smoke-${uniqueToken}`;
  const teamMemberDisplayName = `Playwright Smoke ${uniqueToken}`;
  const initialModel = "qwen3.5:32b";
  const updatedModel = "qwen3.5:14b";

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /planning desk/i })).toBeVisible();

  await page.getByRole("link", { name: /view system health/i }).click();
  await expect(page.getByRole("heading", { name: /local stack health/i })).toBeVisible();
  await expect(page.getByText(/Dependencies/i)).toBeVisible();
  await page.getByRole("link", { name: /back to projects/i }).click();
  await expect(page.getByRole("heading", { name: /planning desk/i })).toBeVisible();

  const newProjectCard = page.locator("article.card").filter({ hasText: "New project" }).first();
  await newProjectCard.getByLabel("Name", { exact: true }).fill(projectName);
  await newProjectCard.getByLabel("Description").fill(projectDescription);
  await newProjectCard.getByLabel("GitHub org").fill("ai-squad");
  await newProjectCard.getByLabel("GitHub repo").fill("playwright-smoke");
  await newProjectCard.getByRole("button", { name: "Create project" }).click();
  await expect(newProjectCard.getByText("Project created.")).toBeVisible();

  const projectLink = page.getByRole("link", { name: new RegExp(projectName) }).first();
  await expect(projectLink).toBeVisible();
  cleanupState.projectId = parseEntityId(await projectLink.getAttribute("href"), "projects");

  await projectLink.click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  const milestoneCreateCard = page.locator("article.card").filter({ hasText: "Add milestone" }).first();
  await milestoneCreateCard.getByLabel("Title").fill(milestoneTitle);
  await milestoneCreateCard.getByLabel("Description").fill("Smoke milestone for timeline and diff verification.");
  await milestoneCreateCard.getByLabel("Due date").fill("2026-05-01");
  await milestoneCreateCard
    .getByLabel("Acceptance criteria")
    .fill("Timeline shows revision entries\nMilestone diff is visible");
  await milestoneCreateCard.getByRole("button", { name: "Add milestone" }).click();
  await expect(milestoneCreateCard.getByText("Milestone added.")).toBeVisible();

  const milestoneCard = page.locator(".milestone-card").filter({ hasText: milestoneTitle }).first();
  await expect(milestoneCard).toBeVisible();
  await milestoneCard.getByLabel("Title").fill(taskTitle);
  await milestoneCard.getByLabel("Description").fill("Smoke task created from the project detail view.");
  await milestoneCard.getByLabel("Assigned role").selectOption("dev-sr");
  await milestoneCard.getByLabel("Priority").selectOption("high");
  await milestoneCard
    .getByLabel("Acceptance criteria")
    .fill("Task appears on milestone\nTask diff becomes visible after status update");
  await milestoneCard.getByRole("button", { name: "Add task" }).click();
  await expect(milestoneCard.getByText("Task added.")).toBeVisible();

  await milestoneCard.getByLabel("Status").first().selectOption("review");
  await milestoneCard.getByRole("button", { name: "Update milestone" }).click();
  await expect(milestoneCard.getByText("Milestone updated.")).toBeVisible();

  const taskCard = milestoneCard.locator(".task-card").filter({ hasText: taskTitle }).first();
  await expect(taskCard).toBeVisible();
  await taskCard.getByLabel("Status").selectOption("in_progress");
  await taskCard.getByRole("button", { name: "Update task" }).click();
  await expect(taskCard.getByText("Task updated.")).toBeVisible();

  await expect(page.locator(".timeline-diff-row").filter({ hasText: "Status" }).first()).toBeVisible();

  await page.goto("/team-members");
  await expect(page.getByRole("heading", { name: /ai team members/i })).toBeVisible();

  const createMemberCard = page.locator("article.card").filter({ hasText: "Add team member" }).first();
  await createMemberCard.getByLabel("Name", { exact: true }).fill(teamMemberName);
  await createMemberCard.getByLabel("Display name").fill(teamMemberDisplayName);
  await createMemberCard.getByLabel("Role").selectOption("qa");
  await createMemberCard.getByLabel("Provider").selectOption("ollama");
  await createMemberCard.getByLabel("Model").fill(initialModel);
  await createMemberCard.getByLabel("Description").fill("Smoke team member used to validate assignment and diff flows.");
  await createMemberCard.getByLabel("Skills").fill("playwright, review, validation");
  await createMemberCard.getByRole("button", { name: "Create team member" }).click();
  await expect(createMemberCard.getByText("Team member created.")).toBeVisible();

  const teamMemberLink = page.getByRole("link", { name: new RegExp(teamMemberDisplayName) }).first();
  await expect(teamMemberLink).toBeVisible();
  cleanupState.teamMemberId = parseEntityId(await teamMemberLink.getAttribute("href"), "team-members");

  await teamMemberLink.click();
  await expect(page.getByRole("heading", { name: teamMemberDisplayName })).toBeVisible();

  const profileCard = page.locator("article.card").filter({ hasText: "Edit defaults" }).first();
  await profileCard.getByLabel("Model").fill(updatedModel);
  await profileCard.getByLabel("Description").fill("Smoke team member updated to verify revision-diff rendering.");
  await profileCard.getByRole("button", { name: "Save team member" }).click();
  await expect(profileCard.getByText("Team member updated.")).toBeVisible();
  await expect(page.locator(".timeline-diff-row").filter({ hasText: "Model" }).first()).toBeVisible();

  await page.goto(`/projects/${cleanupState.projectId}`);
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  const assignmentCard = page.locator("article.card").filter({ hasText: "Assigned team members" }).first();
  const teamMemberSelect = assignmentCard.locator('select[name="team_member_id"]');
  await expect(teamMemberSelect).toBeVisible();
  await teamMemberSelect.selectOption(cleanupState.teamMemberId ?? "");
  await assignmentCard.getByRole("button", { name: "Assign to project" }).click();
  await expect(assignmentCard.getByText("Team member assigned.")).toBeVisible();
  await expect(assignmentCard.getByText("1 active · 1 total")).toBeVisible();

  const assignmentRow = assignmentCard.locator(".assignment-item").filter({ hasText: teamMemberDisplayName }).first();
  await assignmentRow.getByRole("button", { name: "Disable assignment" }).click();
  await expect(assignmentRow.getByText("Assignment disabled.")).toBeVisible();
  await expect(assignmentCard.getByText("0 active · 1 total")).toBeVisible();

  await assignmentRow.getByRole("button", { name: "Re-enable assignment" }).click();
  await expect(assignmentRow.getByText("Assignment re-enabled.")).toBeVisible();
  await expect(assignmentCard.getByText("1 active · 1 total")).toBeVisible();

  await expect(page.getByText(/project_assignment/i).first()).toBeVisible();
  await expect(page.locator(".timeline-diff-row").filter({ hasText: "Enabled" }).first()).toBeVisible();
});

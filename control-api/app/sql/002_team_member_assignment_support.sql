ALTER TABLE team_members
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_team_members_role ON team_members(role);
CREATE INDEX IF NOT EXISTS idx_team_members_active ON team_members(is_active);
CREATE INDEX IF NOT EXISTS idx_project_team_members_project ON project_team_members(project_id);
CREATE INDEX IF NOT EXISTS idx_project_team_members_member ON project_team_members(team_member_id);

GRANT SELECT, INSERT, UPDATE ON team_members TO squad_app;
GRANT SELECT, INSERT, UPDATE ON project_team_members TO squad_app;

# AI Squad — Test Strategy
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11

---

## 1. Testing Principles

1. Use real dependencies for persistence and orchestration tests.
2. Separate workflow correctness from model quality.
3. Test negative paths early, not just in hardening.
4. Treat safety boundaries as products with their own test suites.
5. Validate content usefulness where shape-only checks would be easy to fake.
6. Require evidence-producing tests for every approval path.

---

## 2. Test Layers

### Contract tests
Validate JSON schemas, prompt-eval record shapes, and API request/response contracts.

### Integration tests
Exercise control-api, postgres, redis, workers, sandbox dispatcher, and artifact storage together.

### End-to-end tests
Drive admin-web and the full workflow from trigger through approval.

### Safety tests
Attack permission boundaries, sandbox isolation, branch protections, secret handling, and stale approval logic.

### Calibration and regression tests
Check that judges and prompt revisions correlate with human expectations on a golden dataset.

### Chaos tests
Deliberately break dependencies, inject malformed model outputs, or interrupt worker flows.

---

## 3. Required Shared Fixtures

The test suite must provide:
- deterministic stub agent outputs for PM, reviewer, QA, and judge
- golden planning briefs with expected PM quality characteristics
- human-scored fixture set for judge calibration
- GitHub test repository configuration
- webhook replay fixtures
- safety attack cases for sandbox and GitHub policy checks

---

## 4. Cross-Cutting Tests

These are required across phases, not only once.

### 4.1 State machine property tests
For tasks, milestones, runs, and approvals:
- only legal transitions are accepted
- illegal transitions are rejected
- terminal states remain terminal unless explicit re-entry rules exist

### 4.2 Schema integrity tests
- every registered role has an output contract
- every JSON schema is itself valid
- contract registry and team-member seed data stay aligned

### 4.3 Revision tests
- append-only invariants hold
- current read path returns latest revision
- point-in-time reconstruction returns expected graph state
- stale approvals are invalidated after later edits

### 4.4 Idempotency tests
- duplicate run trigger with the same key returns the original run
- retried step increments attempt number rather than replacing history

### 4.5 Migration tests
- fresh schema boot works
- previous-version data migrates forward cleanly
- old revisions remain readable after schema changes

---

## 5. Phase Test Requirements

### P-1
- service boot smoke tests
- `/health` endpoint test
- admin-web shell load test

### P0
- dependency degradation tests
- restricted DB role test
- direct revision mutation rejection tests
- seed policy presence tests

### P1
- CRUD integration tests
- revision read-path tests
- assignment override scope tests
- point-in-time reconstruction tests
- stale approval invalidation tests

### P2
- Playwright create/edit flows
- revision diff visibility
- evidence-required approval flow
- stale approval badge visibility

### P3
- stub workflow sequencing
- pause/resume/reject flows
- idempotent trigger tests
- deterministic retry behavior

### P4
- PM contract tests
- PM content sanity checks
- GitHub issue linkage tests
- decision log quality threshold checks

### P5
- sandbox red-team suite
- GitHub permission boundary tests
- PR creation and branch protection tests
- rework loop tests

### P6
- QA sandbox execution tests
- judge rubric schema tests
- judge calibration tests
- approval evidence persistence tests
- human override tests

### P7
- webhook ingest tests
- webhook replay tests
- reconciliation report tests
- bounded GitHub noise tests

### P8
- optional-step inclusion and skip-path tests
- UI visibility for skipped steps

### P9
- golden task regression tests
- prompt revision compare tests
- prompt-eval persistence tests

### P10
- chaos tests for dependency outages
- malformed model output tests
- cancellation cleanup tests
- safety violation UI tests

---

## 6. Anti-Fake Test Rules

These checks exist specifically to catch shallow implementations.

### PM anti-fake checks
- task count sanity for non-trivial briefs
- minimum acceptance-criteria density
- minimum decision rationale length
- duplicate-description detection
- placeholder language detection

### Dev anti-fake checks
- suspiciously tiny diffs for large tasks
- stub function or TODO detection in changed files
- zero-duration or empty sandbox results fail
- PR body minimum quality threshold

### Judge anti-fake checks
- judge must rank known-bad outputs below known-good outputs
- repetitive identical scoring patterns trigger failure
- recommendation must align with overall score

### Approval anti-fake checks
- approval without evidence is blocked
- approval for stale revision is blocked or clearly marked override

---

## 7. Sandbox Red-Team Suite

Minimum attack cases:
- read outside mounted workspace
- write outside mounted workspace
- network egress attempt
- non-whitelisted command execution
- infinite loop timeout
- memory pressure abuse
- process explosion attempt
- filesystem enumeration outside allowed scope

Passing this suite is mandatory before claiming the sandbox is safe enough for V1.

---

## 8. GitHub Integration Tests

GitHub tests must cover:
- issue creation content and labels
- branch naming and branch policy enforcement
- PR creation with bounded body content
- comment rate limiting and aggregation
- webhook event capture
- local relay and replay workflow

Issue-count-only tests are insufficient.

---

## 9. Human Verification Support

Automated tests are not enough. Each phase should emit evidence artifacts that a human can inspect:
- representative API responses
- representative UI screenshots or recordings
- sandbox execution output
- GitHub object links
- judge calibration report
- prompt comparison report

The test suite should help produce evidence, not replace human review.

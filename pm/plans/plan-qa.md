# Fully Specified Project from project.yaml

Goal: a project fully specified by project.yaml where auto-starting the final PR
yields a high probability of producing fully user-ready software with all planned
features. Once an initial iteration is working, enable automated proposals and
testing of methods for improving performance and efficiency — including generating
equivalent or higher quality code with fewer tokens, and producing code that is
more robust to adversarial agents.

## Phase 1: Quality Assurance Pipeline

### PR: Add optional quality assurance step with test instruction library and review-QA loop
- **description**: Add an optional QA / manual testing step between review and merge. Creates a review-QA loop: QA changes re-trigger review, review changes re-trigger QA, loop terminates when QA passes with no changes for N iterations (default 1). Includes a test instruction library (pm/instructions/) with titles and short descriptions, a TUI pane for browsing/editing instructions, QA session recording as PR notes, automatic QA work directory creation, a flow for QA on existing features via dummy PRs or standalone mode, and updates to the INPUT_REQUIRED flow since QA replaces most manual testing needs from review.
- **depends_on**:

---

### PR: Persist generated QA tests across iterations of the QA loop
- **description**: QA test plans and results persist across loop iterations for incremental testing, test history tracking, and stability detection. Storage alongside QA work directory or as structured PR QA notes.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Support user stories at PR creation and edit time for QA test generation
- **description**: Attach user stories to PRs at creation (--story) or via edit screen. Stories guide QA test generation toward acceptance-style end-to-end tests from the user perspective. Stored as a PR field in project.yaml, passed to QA agent during test planning.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Add pause-after-QA-plan mode with global setting, prefix key, and per-PR field
- **description**: Pause QA execution after test generation for user review/approval. Three activation methods: global setting (qa_pause_after_plan in project.yaml), prefix key for single QA run, per-PR field (qa_pause). Priority: per-PR overrides global, prefix key overrides both.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

## Phase 2: Automated Optimization

### PR: Add automated performance and efficiency proposal framework
- **description**: Framework for automatically proposing and testing methods to improve code generation performance and efficiency. Includes metrics collection (token usage, code quality scores, test pass rates), A/B testing infrastructure for comparing approaches, and a feedback loop that evaluates proposals against baseline measurements. Targets: generating equivalent or higher quality code with fewer tokens, and producing code that is more performant and robust to adversarial inputs.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop, Persist generated QA tests across iterations of the QA loop

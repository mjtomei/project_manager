# Import from existing repo

Add cluster analysis to the import/init flow so users get an automated starting
point for PR decomposition based on code structure, rather than purely manual
discovery.

## PRs

### PR: Add background cluster computation to plan import
- **description**: Run cluster extraction in parallel when `_run_plan_import` starts, so results are available without blocking the interactive flow
- **tests**: Unit test verifying cluster extraction runs and returns results within the import flow
- **files**: pm_core/cli.py
- **depends_on**:

---

### PR: Include cluster suggestions in import prompt
- **description**: Add cluster analysis results as a "Phase 1.5" in the import prompt - Claude receives clusters as a suggested starting point for PR decomposition, which can be used, modified, or ignored
- **tests**: Integration test verifying the prompt includes cluster summary when available
- **files**: pm_core/cli.py
- **depends_on**: Add background cluster computation to plan import

---

### PR: Add cluster-first option to guide workflow
- **description**: In the guide's "initialized" step, offer `pm cluster explore` as an alternative path alongside `pm plan add`, giving users a choice between manual and automated starting points
- **tests**: Test that guide prompt mentions both cluster and manual options
- **files**: pm_core/guide.py
- **depends_on**:

---

### PR: Smart repo-size detection with approach recommendation
- **description**: Detect repo size (lines of code) and recommend manual vs cluster-based approach automatically - small repos get manual suggestion, large repos get cluster suggestion
- **tests**: Unit tests for size detection thresholds and recommendation logic
- **files**: pm_core/cli.py, pm_core/guide.py
- **depends_on**: Add cluster-first option to guide workflow

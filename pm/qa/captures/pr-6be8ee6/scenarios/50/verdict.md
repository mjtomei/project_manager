# Scenario 50: End-to-end bug-fix + QA captures pipeline

INPUT_REQUIRED

refiner rejected: This scenario bundles five independent stories that each require multi-hour interactive Claude-in-tmux sessions to drive from the real user surface: invoking the bug-fix 5-step flow (`pm pr session`), running the review loop end-to-end twice to observe INPUT_REQUIRED→PASS transitions, running `pm qa run` scenarios that produce captures, exercising the e8fe399 verifier-gate after a follow-up keystroke, and triggering finalize. There is also no user-facing `pm qa finalize <pr-id>` surface — `qa_finalize_prompt.py` is only invoked as an internal pane by `pm qa run` (pm_core/qa_loop.py:419), so the finalize sub-story has no standalone entry point at all. Driving this within a single QA pass would require many hours of interactive LLM work and is out of budget.

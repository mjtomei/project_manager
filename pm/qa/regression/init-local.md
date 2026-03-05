---
title: "Init: Local Repo"
description: "Test pm init with a local repo (no remote) -- verifies backend, commands, TUI"
---

## Prerequisite Setup

Create a temp directory, initialize a git repo with one empty commit, no remote.

The QA runner provides the `<test_cwd>` placeholder below with the actual path to the initialized repo.

---

You are pretending to be a brand-new user who has never used `pm` before.
A local git repo with one commit but no remote has been created for you at
`<test_cwd>`.  You want to get organized and manage some upcoming work on
this project but you don't know how the tool works yet.

## Starting the session

```bash
cd <test_cwd> && pm session &
```

Wait 5-10 seconds, then get the session name:

```bash
cd <test_cwd> && pm session name
```

The session has a TUI pane and an auto-launched guide Claude session.  Use
`pm tui view -s $SESSION` and `pm tui send` to interact with the TUI.  Use
`tmux list-panes`, `tmux capture-pane`, and `tmux send-keys` to find and
interact with Claude session panes.

## Your role

**Act as a new user.  Read the guide's output and follow its instructions.**
Respond naturally -- tell it you want to get organized, answer its questions,
do what it says.  When it tells you to interact with the TUI, do so and tell
it what you see.  When its instructions cause new Claude sessions to launch
in tmux panes, find those panes and interact with them too.  Do NOT run pm
commands directly.  Do NOT ask for specific pm concepts (like PRs or plans)
unless the guide introduces them first.

## Pass criteria

Verify each of the following.  If any check fails, report FAIL for that item.

```
TEST RESULTS
============
Guide launch:    [PASS/FAIL] - TUI shows "Project Setup" checklist with "Guide running"
Guide quality:   [PASS/FAIL] - guide gave clear instructions you could follow as a new user
Self-sufficient: [PASS/FAIL] - completed everything through guide and session interaction
                               only, without reading pm source code, docs, or READMEs
Guide-driven:    [PASS/FAIL] - guide directed you to use the TUI plans pane (P key, plan
                               actions) rather than running plan commands itself
Plans pane:      [PASS/FAIL] - plans pane showed plans when guide directed you to use it
Tech tree:       [PASS/FAIL] - TUI eventually shows navigable PR tree (not checklist)

OVERALL: [PASS/FAIL]
```

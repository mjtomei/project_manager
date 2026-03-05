---
title: Tech Tree Visual Review
description: Review tech tree appearance for visual issues and improvements
---
You are reviewing the visual appearance of the pm TUI's tech tree (PR dependency graph).
Your goal is to identify any visual issues and suggest improvements to make the TUI
look better and be more usable.

## Background

The TUI displays a "tech tree" showing PRs and their dependencies. Each PR is shown
as a box with its ID, title, and status. Dependencies are shown with connecting lines.
There have been reports of:
- Boxes overlapping or clipping into each other
- Alignment issues with dependency lines
- Text truncation problems
- General visual polish issues

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes (arrow keys to navigate, Enter to select)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer

## Test Procedure

### Part 1: Initial Visual Assessment

1. Run `pm tui clear-frames` to start fresh
2. Run `pm tui view` to capture the current TUI state
3. Carefully examine the output and note:
   - Are there any PRs displayed? If not, note "No PRs to display"
   - If PRs are displayed, check for visual issues:
     * Do any boxes overlap or clip into each other?
     * Are the box borders complete and properly drawn?
     * Is text properly contained within boxes?
     * Are dependency lines (if any) properly aligned?
     * Is the spacing between elements consistent?
     * Is the overall layout balanced?

### Part 2: Navigation Testing (if PRs exist)

1. Try navigating with arrow keys:
   - `pm tui send Up` and `pm tui send Down` to move selection
   - After each, run `pm tui view` to see the updated state
2. Check if:
   - Selection highlighting is visible and clear
   - The display updates smoothly without visual artifacts
   - Selected item is clearly distinguishable from others

### Part 3: Different Terminal Widths (optional)

If you can resize or have info about terminal width:
1. Note the current width from the captured frame
2. Consider how the layout might look at different widths
3. Note any elements that might break at narrower widths

### Part 4: Aesthetic Review

Look at the TUI with a critical eye for design:
1. Color choices - are they readable and pleasant?
2. Use of Unicode characters - appropriate and rendering correctly?
3. Information density - too cluttered or too sparse?
4. Visual hierarchy - is it clear what's important?
5. Consistency - do similar elements look similar?

## What To Look For

Common visual issues in terminal UIs:
- Box-drawing characters not connecting properly (gaps or overlaps)
- ANSI color codes not being interpreted (showing as escape sequences)
- Unicode characters showing as boxes or question marks
- Text extending beyond its container
- Misaligned columns or rows
- Inconsistent padding or margins
- Hard-to-read color combinations (e.g., dark text on dark background)

## Reporting

Provide a detailed visual review:

```
TECH TREE VISUAL REVIEW
=======================

PRs Present: [Yes/No] - <count if yes>

## Visual Issues Found

### Critical (breaks usability)
<list any critical issues, or "None found">

### Moderate (noticeable but usable)
<list any moderate issues, or "None found">

### Minor (polish issues)
<list any minor issues, or "None found">

## Current Appearance

<Describe what you see - the overall layout, how PRs are displayed,
 what the tree structure looks like>

## Suggestions for Improvement

### High Priority
<suggestions that would significantly improve the experience>

### Nice to Have
<suggestions for visual polish>

## Screenshots/Frames

Key frames from `pm tui frames --all`:
<Note the frame numbers and what they show>

## Overall Assessment

Visual Quality: [Poor/Fair/Good/Excellent]
Usability: [Poor/Fair/Good/Excellent]

Summary:
<2-3 sentence summary of the TUI's visual state and top recommendations>
```

Be specific and constructive in your feedback. If you see overlapping boxes or other
issues, describe exactly where they occur and what they look like.

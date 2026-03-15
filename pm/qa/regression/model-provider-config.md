---
title: "Model & Provider Configuration"
description: "Test model targeting, provider selection, and configuration"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Check current model/provider configuration
```bash
python3 -c "
from pm_core.providers import list_providers, get_default_provider
providers = list_providers()
print(f'Available providers: {len(providers)}')
for p in providers:
    print(f'  {p}')
default = get_default_provider()
print(f'Default provider: {default}')
" 2>&1 || echo "Provider system not configured"
```

### 2. Verify claude launcher resolves providers
```bash
python3 -c "
from pm_core.claude_launcher import build_claude_shell_cmd
cmd = build_claude_shell_cmd(prompt='test')
print(f'Built command: {cmd[:100]}...')
# Verify it doesn't crash and produces a valid command string
assert 'claude' in cmd, 'Command should contain claude'
print('Provider resolution: OK')
"
```

### 3. Check per-session-type model targeting
```bash
python3 -c "
from pm_core.paths import get_global_setting_value
for session_type in ['implementation', 'review', 'qa', 'planner', 'watcher']:
    model = get_global_setting_value(f'model-{session_type}', 'default')
    print(f'  {session_type}: {model}')
" 2>&1 || echo "Model targeting not configured"
```

### 4. Verify model flag in built commands
```bash
python3 -c "
from pm_core.claude_launcher import build_claude_shell_cmd
# Test with explicit model
cmd = build_claude_shell_cmd(prompt='test', model='claude-sonnet-4-20250514')
assert '--model' in cmd, 'Should have --model flag'
print(f'Model flag present: OK')
print(f'Command: {cmd[:150]}...')
"
```

## Expected Behavior

- Provider system loads without errors
- Claude launcher builds valid command strings
- Per-session-type model targeting is queryable
- Explicit model overrides work

## Reporting

```
TEST RESULTS
============
provider list:     [PASS/FAIL] - Providers enumerated
cmd build:         [PASS/FAIL] - Claude command builds correctly
model targeting:   [PASS/FAIL] - Per-session-type models queryable
model override:    [PASS/FAIL] - Explicit model flag works

OVERALL: [PASS/FAIL]
```

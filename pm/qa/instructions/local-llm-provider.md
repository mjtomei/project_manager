---
title: Local LLM Provider Integration
description: Validate local LLM provider setup, verification, and model selection
tags: [provider, local-llm, integration]
---
## Setup

Ensure Ollama (or another local LLM server) is installed and running:

```bash
ollama serve  # if not already running
ollama pull glm-4.7-flash  # or another small model
```

## Test Steps

### 1. Provider Add and Verify
```bash
pm provider add test-ollama --api-base http://localhost:11434 --model glm-4.7-flash
```
- Should test connectivity, context window, and tool use
- Should report results for each check
- Should succeed if model supports tool calling

### 2. Provider Test (full)
```bash
pm provider test test-ollama
```
- Should show: Connectivity, Context window, Tool use, Inference status
- For openai-type providers, should also probe Anthropic API support

### 3. Provider Test (quick)
```bash
pm provider test test-ollama --quick
```
- Should only test connectivity (skip tool use)

### 4. Model Show Lists Local Providers
```bash
pm model show
```
- Should include a "Available local/external providers" section
- Should list the test-ollama provider with its model and api_base

### 5. Model Targeting with Provider
```bash
pm model set watcher provider:test-ollama
pm model show
```
- Watcher row should show `provider:test-ollama`

### 6. Provider Cleanup
```bash
pm model unset watcher
pm provider remove test-ollama
```

## Expected Behavior

- Provider add performs real connectivity and inference checks
- Provider test reports capabilities clearly (reachable, tool use, inference, context window)
- Model show always displays configured local providers even without active overrides
- OpenAI-type providers that support /v1/messages get a suggestion to use type=local

## Reporting

Report PASS if all steps complete successfully.
Report NEEDS_WORK if any verification step produces incorrect output.
Report INPUT_REQUIRED if Ollama is not available to test against.

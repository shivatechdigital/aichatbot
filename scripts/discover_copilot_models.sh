#!/usr/bin/env bash
set -u

# These are candidate CLI IDs, not the display labels shown by VS Code.
models=(
  gpt-5.4
  gpt-5-mini
  gpt-5.3-codex
  gpt-5.4-mini
  gpt-5.5
  gpt-5.6-luna
  gpt-6-astra
  gpt-6-luna
  gpt-6-sol
  claude-sonnet-5
  claude-fable-5
  claude-fable-5.1
  claude-haiku-4.5
  claude-opus-4.7
  claude-opus-4.8
  claude-opus-5
  claude-opus-5.5
  gemini-3.5-flash
  gemini-3.6-flash
  gemini-3.7-flash
  gemini-3.8-flash
  grok-4.5
  grok-4.6
  grok-4.7
)

printf 'auto\n'
for model in "${models[@]}"; do
  if output=$(copilot --model "$model" -p 'Reply only: OK' --silent 2>&1); then
    printf '%s\n' "$model"
  fi
done
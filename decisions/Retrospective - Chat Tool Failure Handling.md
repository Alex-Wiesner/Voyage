---
title: Retrospective - Chat Tool Failure Handling
type: note
permalink: voyage/decisions/retrospective-chat-tool-failure-handling
tags:
- pattern
- lesson
- chat
- retrospective
---

# Retrospective - Chat Tool Failure Handling

## Retrospective: chat tool failure handling
- [pattern] Separating successful-tool iterations from bounded all-failure rounds prevents external tool outages from exhausting the main tool-call budget. #pattern
- [pattern] Classify chat tool failures into required-parameter errors, retryable execution failures, and permanent execution failures so each path can use the right UX and retry behavior. #pattern
- [risk] Mixed batches with both successful and failed tool calls still rely on the global success iteration cap as a backstop; acceptable pre-release, but worth revisiting if multi-tool itineraries remain noisy. #risk

confidence=high; last_validated=2026-03-10; volatility=medium; review_after_days=60; validation_count=1; contradiction_count=0

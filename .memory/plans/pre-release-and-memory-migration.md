---
title: pre-release-and-memory-migration
type: note
permalink: voyage/plans/pre-release-and-memory-migration
---

# Plan: Pre-release policy + .memory migration

## Scope
- Update project instruction files to treat Voyage as pre-release (no production compatibility constraints yet).
- Migrate `.memory/` to the standardized structure defined in AGENTS guidance.

## Tasks
- [x] Add pre-release policy guidance in instruction files (`AGENTS.md` + synced counterparts).
  - **Acceptance**: Explicit statement that architecture-level changes (including replacing LiteLLM) are allowed in pre-release, with preference for correctness over backward compatibility.
  - **Agent**: librarian
  - **Note**: Added identical "Pre-Release Policy" section to all 4 instruction files (AGENTS.md, CLAUDE.md, .cursorrules, .github/copilot-instructions.md). Also updated `.memory Files` section in AGENTS.md, CLAUDE.md, .cursorrules to reference new nested structure.

- [x] Migrate `.memory/` to standard structure.
  - **Acceptance**: standardized directories/files exist (`manifest.yaml`, `system.md`, `knowledge/*`, `plans/`, `research/`, `gates/`, `sessions/`), prior knowledge preserved/mapped, and manifest entries are updated.
  - **Agent**: librarian
  - **Note**: Decomposed `knowledge.md` (578 lines) into 7 nested files. Old `knowledge.md` marked DEPRECATED with pointers. Manifest updated with all new entries. Created `gates/`, `sessions/continuity.md`.

- [x] Validate migration quality.
  - **Acceptance**: no broken references in migrated memory docs; concise migration note included in plan.
  - **Agent**: librarian
  - **Note**: Cross-references updated in decisions.md (knowledge.md -> knowledge/overview.md). All new files cross-link to decisions.md, plans/, and each other.

## Migration Map (old -> new)

| Old location | New location | Content |
|---|---|---|
| `knowledge.md` §Project Overview | `system.md` | One-paragraph project overview |
| `knowledge.md` §Architecture, §Services, §Auth, §Key File Locations | `knowledge/overview.md` | Architecture, API proxy, AI chat, services, auth, file locations |
| `knowledge.md` §Dev Commands, §Pre-Commit, §Environment, §Known Issues | `knowledge/tech-stack.md` | Stack, commands, env vars, known issues |
| `knowledge.md` §Key Patterns | `knowledge/conventions.md` | Frontend/backend coding patterns, workflow conventions |
| `knowledge.md` §Chat Model Override, §Error Mapping, §OpenCode Zen, §Agent Tools, §Backend Chat Endpoints, §WS4, §Context Derivation | `knowledge/patterns/chat-and-llm.md` | All chat/LLM implementation patterns |
| `knowledge.md` §Collection Sharing, §Itinerary, §User Preferences | `knowledge/domain/collections-and-sharing.md` | Collections domain knowledge |
| `knowledge.md` §WS1 Config, §Frontend Gaps | `knowledge/domain/ai-configuration.md` | AI configuration domain |
| (new) | `sessions/continuity.md` | Session continuity notes |
| (new) | `gates/.gitkeep` | Quality gates directory placeholder |
| `knowledge.md` | `knowledge.md` (DEPRECATED) | Deprecation notice with pointers to new locations |
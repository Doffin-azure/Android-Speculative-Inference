# Root Document Map

This file explains how the older root-level documents relate to the newer `docs/` library.

## Root-Level Files

- `ANDROID_APP_CHECKPOINT.md`
- `LLAMA_CPP_INTEGRATION_PLAN.md`
- `MIDTERM_REPORT.md`

## How To Use Them

`ANDROID_APP_CHECKPOINT.md`

- best treated as the rolling checkpoint archive
- contains many incremental node records
- useful when reconstructing exact session-by-session progress

`LLAMA_CPP_INTEGRATION_PLAN.md`

- best treated as the integration history and architecture-oriented plan archive
- useful when checking why a migration decision was made

`MIDTERM_REPORT.md`

- best treated as the formal academic progress report
- useful for thesis/reporting context rather than day-to-day implementation guidance

## How The New Library Helps

The `docs/` library is intended to reduce the cost of resuming work by separating:

- operational environment knowledge
- current technical status
- collaboration workflow
- archive mapping

## Source Of Truth Strategy

Use this strategy when there is overlap:

1. `docs/project/current-status.md` for what to do next
2. `docs/environment/*.md` for environment-specific execution details
3. `docs/workflow/collaboration-rules.md` for process rules
4. root-level documents for detailed history and formal records

## Migration Intent

The purpose of the `docs/` library is not to delete the old files.

It is to migrate the most reusable knowledge out of long rolling archives and into smaller topic-specific references:

- environment setup knowledge moves into `docs/environment/`
- active execution guidance moves into `docs/project/`
- process rules move into `docs/workflow/`
- the root files remain as archive or report material

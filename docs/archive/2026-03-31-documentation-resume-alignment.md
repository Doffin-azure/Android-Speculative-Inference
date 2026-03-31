# Documentation Resume Alignment - 2026-03-31

## Completed In This Node

- aligned `docs/README.md` with the intended source-of-truth order so resume flow starts from `docs/project/current-status.md`
- expanded `docs/project/current-status.md` with an explicit immediate execution order and a concrete definition of done for the next node
- found the local Git executable and recorded it in ignored local configuration through `gradle-local.properties`

## Why This Matters

- the project now has a cleaner operational resume path
- the next node is explicitly focused on preserving and re-checking the proven Android local-runtime baseline
- future git-sync work can use a known-good absolute Git path even when `git` is missing from the default PowerShell `PATH`

## Recommended Resume Point

Continue from `docs/project/current-status.md` and treat the next node as complete only after:

- the Android local-runtime milestone is preserved as the known-good baseline
- a few repeat on-device prompt checks are run again
- any regression is captured through the existing diagnostics path instead of reopening old preparation work by default

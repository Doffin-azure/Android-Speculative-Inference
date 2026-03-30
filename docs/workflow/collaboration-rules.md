# Collaboration Rules

## Repository Rules

- Keep local machine files, IDE noise, virtual environments, Gradle outputs, and generated artifacts out of git.
- After each completed node or session, perform a git sync.
- Do not treat git sync as silent cleanup. Record a short explanation of what changed.
- Do not stop at the git explanation alone. Also write a short node summary into the markdown archive/checkpoint documents so future resume points stay explicit.

## Build And Verification Boundary

- Android Studio sync, build, install, and runtime verification are performed by the user.
- Codex should focus on code changes, document changes, diagnostics, and clear verification instructions.
- Android bundle and packaging work must be performed by the user, not by Codex.

## Working Style

- Prefer continuing the current mainline instead of reopening old preparation work.
- Keep the active native integration centered in `:lib`.
- Treat root-level historical notes carefully when they conflict with newer architecture.

## Practical Interpretation

When resuming work:

- check `docs/project/current-status.md`
- check `docs/environment/desktop-gguf-runtime-supplement.md` if the task involves GGUF validation or desktop runtime
- use root-level documents as archive/history, not as the fastest operational reference

When closing a completed node:

- sync git
- provide a short human-readable explanation of the sync
- update the relevant markdown archive/checkpoint documents with a brief summary of the completed work

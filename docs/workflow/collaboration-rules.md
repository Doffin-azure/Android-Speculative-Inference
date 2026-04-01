# Collaboration Rules

## Repository Rules

- Keep local machine files, IDE noise, virtual environments, Gradle outputs, and generated artifacts out of git.
- After each completed node or session, perform a git sync.
- Do not treat git sync as silent cleanup. Record a short explanation of what changed.
- Do not stop at the git explanation alone. Also write a short node summary into the markdown archive/checkpoint documents so future resume points stay explicit.
- When a core feature is implemented, also add or update a dedicated code-explanation document that includes the core code snippets and a short explanation of how they work.
- Do not treat behavioral summaries as enough for core features. The documentation close-out should explicitly show the key code path and explain why it is the core implementation.
- Keep `docs/project/project-core-code-history.md` as the historical ledger for already completed feature nodes reviewed from git history.

## Git Command Fallback

- Do not assume `git` is always available on the current shell `PATH`.
- On this machine, if `git status` fails in PowerShell, use:
  - `C:\Program Files\Git\cmd\git.exe`
- Preferred fallback commands:
  - `& 'C:\Program Files\Git\cmd\git.exe' status --short`
  - `& 'C:\Program Files\Git\cmd\git.exe' diff --stat`
  - `& 'C:\Program Files\Git\cmd\git.exe' add ...`
  - `& 'C:\Program Files\Git\cmd\git.exe' commit -m "..."`
- Treat this absolute-path fallback as the default recovery path before concluding that git is unavailable.

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
- if the node contains a core feature, update the code-explanation document with the key code snippets and short explanations
- if `git` is missing from `PATH`, retry with `C:\Program Files\Git\cmd\git.exe` before treating git-sync as blocked

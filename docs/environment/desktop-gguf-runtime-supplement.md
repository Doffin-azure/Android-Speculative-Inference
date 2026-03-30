# Desktop GGUF Runtime Supplement

## Purpose

This document records the computer-side environment prepared to inspect and attempt to run GGUF models locally.

It exists as a supplement to the Android-focused project notes.

## Environment Snapshot

Primary working environment used for this supplement:

- repository root: `C:\Users\JXZ\AndroidStudioProjects\MyApplication2`
- host OS: `Windows`
- active shell in this workspace: `PowerShell`
- current helper Python environment: `.venv-gguf/`
- current desktop source tree for `llama.cpp`: `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`

Important environment caveats observed:

- `git` is not currently available in the default PowerShell `PATH`, so repository sync commands may need an absolute `git.exe` path.
- Windows was good enough for GGUF inspection work, but the desktop `llama.cpp` runtime attempt was easier to push forward through WSL Ubuntu.
- Temporary package and tool artifacts can appear during this setup and should stay out of git.

## Validated Model

Validated on:

- `Llama-3.2-1B-Instruct-Q4_K_M.gguf`

Observed file facts:

- size: `807,694,464` bytes
- approximate size: `770.3 MB`
- header: `GGUF`
- version: `3`
- tensor count: `147`
- metadata/field count: `38`
- architecture metadata: `llama`
- model name metadata: `Llama 3.2 1B Instruct`

Interpretation:

- the model file looks structurally valid on the computer
- this strongly suggests the Android-side load failure is not caused by an obviously broken or empty GGUF artifact

## Desktop GGUF Inspection Environment

Project-local Python inspection environment:

- virtual environment path: `.venv-gguf/`
- ignored by git via `.gitignore`
- script entry point: `tools/gguf_check.py`

Installed Python packages in that environment:

- `numpy`
- `pyyaml`

Why these are installed:

- `llama.cpp/gguf-py` needs them in order to read GGUF metadata

## GGUF Inspection Command

From the project root in PowerShell:

```powershell
.\.venv-gguf\Scripts\python tools\gguf_check.py Llama-3.2-1B-Instruct-Q4_K_M.gguf
```

What this does:

- loads the local `llama.cpp/gguf-py` reader
- reads the GGUF metadata from the given model file
- prints core metadata fields for quick validation

## Desktop `llama.cpp` CLI Build Environment

Source tree used:

- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`

Model path used from WSL:

- `/mnt/c/Users/JXZ/AndroidStudioProjects/MyApplication2/Llama-3.2-1B-Instruct-Q4_K_M.gguf`

WSL environment discovered:

- distro: `Ubuntu`
- compiler: `g++ 13.3.0`
- build tool present: `make 4.3`
- system `cmake`: missing
- system `ninja`: missing
- `sudo`: available but requires user password

Workaround used:

- downloaded Ubuntu `.deb` packages for `cmake` and the required runtime libraries
- extracted them into a user-space directory under `/tmp/cmake-root`
- used that extracted `cmake` binary directly without modifying the system installation
- a separate downloaded portable CMake tree was also observed as an accidental local artifact inside the repository and should be treated as disposable environment residue, not project content

Important extracted tool path:

- `/tmp/cmake-root/usr/bin/cmake`

Important runtime library path:

- `/tmp/cmake-root/usr/lib/x86_64-linux-gnu`
- `/tmp/cmake-root/lib/x86_64-linux-gnu`

## CLI Build Output

Built desktop CLI path:

- `/mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/bin/llama-cli`

Build notes:

- `llama.cpp` now uses CMake instead of the old Makefile build
- in this source version, `llama-cli` is only generated when `LLAMA_BUILD_SERVER=ON`

Configuration pattern used:

```bash
export LD_LIBRARY_PATH=/tmp/cmake-root/usr/lib/x86_64-linux-gnu:/tmp/cmake-root/lib/x86_64-linux-gnu
/tmp/cmake-root/usr/bin/cmake \
  -S /mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp \
  -B /mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_BUILD_TOOLS=ON

/tmp/cmake-root/usr/bin/cmake \
  --build /mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli \
  --target llama-cli -j2
```

## Desktop Run Command

Current run pattern:

```bash
export LD_LIBRARY_PATH=/mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/bin:/tmp/cmake-root/usr/lib/x86_64-linux-gnu:/tmp/cmake-root/lib/x86_64-linux-gnu
/mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/bin/llama-cli \
  -m /mnt/c/Users/JXZ/AndroidStudioProjects/MyApplication2/Llama-3.2-1B-Instruct-Q4_K_M.gguf \
  -p "Hello" \
  -n 16 \
  --no-warmup \
  --simple-io
```

Validated successful run from PowerShell:

```powershell
wsl.exe bash -lc "export LD_LIBRARY_PATH=/mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/bin:/mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/lib:/tmp/cmake-root/usr/lib/x86_64-linux-gnu:/tmp/cmake-root/lib/x86_64-linux-gnu; /mnt/c/Users/JXZ/AndroidStudioProjects/llama.cpp/build-wsl-cli/bin/llama-cli -m /mnt/c/Users/JXZ/AndroidStudioProjects/MyApplication2/Llama-3.2-1B-Instruct-Q4_K_M.gguf -p 'Hello' -n 8 --no-warmup --simple-io -t 2"
```

Observed result:

- model loaded successfully
- interactive prompt started successfully
- prompt `Hello` produced a normal text reply
- observed throughput was about `110.1 t/s` for prompt processing and `31.4 t/s` for generation in this run
- a WSL localhost-proxy warning appeared, but it did not block runtime execution

## Current Interpretation

What is already confirmed:

- the GGUF can be parsed on the computer through `gguf-py`
- a desktop `llama-cli` binary has been built successfully in WSL
- the same GGUF has now completed a real text-generation run through desktop `llama-cli`

Therefore:

- the desktop-side environment is now good enough for both direct model inspection and real local execution
- the GGUF file itself should now be treated as runtime-validated on the computer
- the next desktop-side step is optional deeper benchmarking, not basic viability confirmation

## Repository Hygiene Notes

Artifacts that should remain untracked:

- `.venv-gguf/`
- temporary downloaded `.deb` files such as `cmake-data_3.28.3-1build7_all.deb`
- accidental tool-drop directories such as `CUsersJXZ/`

Why this matters:

- these files belong to the local setup path, not to the portable project history

## Practical Value

This desktop environment is useful for separating two classes of failures:

1. bad model artifact problems
2. Android-side runtime or integration problems

At this point, the evidence is leaning toward Android-side loading/runtime behavior rather than an obviously broken GGUF file.

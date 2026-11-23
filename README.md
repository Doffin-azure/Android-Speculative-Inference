# Android–Windows Speculative Decoding

This undergraduate thesis project splits large-language-model decoding across an Android phone and a Windows PC. The phone uses a small draft model to propose token IDs. The PC checks the proposal with a larger target model and sends back the accepted count and the correction or continuation token. Both devices use that result to continue from the same prefix.

## Run the phone demo

You need an ARM64 Android phone with USB debugging enabled, Android Studio with the Android SDK and NDK, Python 3 on Windows, and WSL with CMake, a C++ compiler, and OpenSSL development headers. Use checkout and model paths without spaces for the PowerShell runner.

1. Clone this project and [llama.cpp](https://github.com/ggml-org/llama.cpp). The demo was built against llama.cpp revision `7c203670f8d746382247ed369fea7fbf10df8ae0`. Copy [gradle-local.template.properties](gradle-local.template.properties) to `gradle-local.properties` and set `llamaCppSourceDir` to the Windows path of the llama.cpp checkout, for example `C:/src/llama.cpp`.
2. From this project's root in WSL, build the desktop runtime. Set `llama` to the WSL path of the same llama.cpp checkout.

   ```bash
   llama=/mnt/c/src/llama.cpp
   cmake -S "$llama" -B "$llama/build-wsl-cli" -DCMAKE_BUILD_TYPE=Release \
     -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
     -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_SERVER=ON
   cmake --build "$llama/build-wsl-cli" --target llama-cli --parallel 4
   bash tools/build_desktop_target_runtime.sh
   ```

3. Put compatible Llama 3.2 Instruct Q4_K_M GGUF files in `models/`. For the commands below, save the [1B draft model](https://huggingface.co/QuantFactory/Llama-3.2-1B-Instruct-GGUF/blob/main/Llama-3.2-1B-Instruct.Q4_K_M.gguf) as `Llama-3.2-1B-Instruct-Q4_K_M.gguf` and the [3B target model](https://huggingface.co/QuantFactory/Llama-3.2-3B-Instruct-GGUF/blob/main/Llama-3.2-3B-Instruct.Q4_K_M.gguf) as `Llama-3.2-3B-Instruct-Q4_K_M.gguf`. Connect and unlock the phone, then allow USB debugging.
4. Run these commands from the project root in Windows PowerShell. `adb devices` should show one device in the `device` state. If the phone prompts you to install the debug APK over USB, confirm the installation on the phone.

   ```powershell
   adb devices
   adb reverse tcp:18080 tcp:18080
   .\tools\run_android_spec_split_experiment.ps1 `
     -Port 18080 -BaseUrl 'http://127.0.0.1:18080' `
     -DraftModelName 'Llama-3.2-1B-Instruct-Q4_K_M.gguf' `
     -TargetModelPath (Resolve-Path '.\models\Llama-3.2-3B-Instruct-Q4_K_M.gguf').Path `
     -Prompt 'For large language models, speculative decoding speeds up token generation by' `
     -MaxAcceptedTokens 64 -DraftMaxTokens 4 -InitialDraftTokens 4 -DraftMinTokens 1
   adb reverse --remove tcp:18080
   ```

The runner installs the debug app, copies the draft GGUF to the phone, starts the Windows verifier, and saves the app output and a JSON summary. Read the latest `logs/android_spec_split_app_output_*.txt` for the generated text and per-round proposal and acceptance counts.

### Recorded phone run

The command above finished on an Android 17 phone connected over USB to a Windows PC. This run committed 13 tokens before the draft produced no further candidates. The 64-token setting is an upper limit.

```text
health=ok
verifierMode=llama_cpp_spec_split
steps=6
committedTokens=13
totalProposedTokens=20
overallTokensPerSecond=6.867
```

## Thesis benchmark

The thesis used Qwen2.5-Instruct Q4_K_M models (0.5B draft and 7B target) with an Android phone and Windows workstation on the same local network. The approximately 1,000-token run measured steady-state generation after setup.

| Configuration | Tokens/s |
| --- | ---: |
| Android local 7B model | 7.232 |
| Windows single-process speculative decoding | 15.707 |
| Windows two-process speculative decoding | 14.816 |
| **Android draft + Windows verifier** | **13.996** |

The split reached 94.46% of the Windows two-process throughput and improved on Android-only throughput by 93.5% in this setup. See the [throughput experiment](docs/experiments/2026-04-29-qwen-aligned-speculative-experiment.md), the [separate memory rerun](docs/experiments/2026-05-08-qwen-thesis-rerun.md), and the [documentation index](docs/README.md).

For a desktop-only walkthrough of the same draft/verify separation, see the [two-process demo](https://github.com/Doffin-azure/spec-split-demo-project).

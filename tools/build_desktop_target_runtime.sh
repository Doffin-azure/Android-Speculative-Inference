#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${REPO_ROOT}/gradle-local.properties" ]]; then
  LLAMA_CPP_DIR="$(grep '^llamaCppSourceDir=' "${REPO_ROOT}/gradle-local.properties" | sed 's/^llamaCppSourceDir=//' | sed 's#\\\\#/#g' | sed 's#^\([A-Za-z]\):#/mnt/\L\1#')"
else
  LLAMA_CPP_DIR=""
fi

if [[ -z "${LLAMA_CPP_DIR}" || ! -d "${LLAMA_CPP_DIR}" ]]; then
  echo "Unable to resolve llama.cpp source directory from gradle-local.properties" >&2
  exit 1
fi

BUILD_DIR="${LLAMA_CPP_DIR}/build-wsl-cli"
COMMON_LIB="${BUILD_DIR}/common/libcommon.a"
LLAMA_BIN_DIR="${BUILD_DIR}/bin"
OUTPUT_PATH="${SCRIPT_DIR}/desktop_target_runtime"

g++ -std=c++17 -O2 \
  -I"${LLAMA_CPP_DIR}" \
  -I"${LLAMA_CPP_DIR}/include" \
  -I"${LLAMA_CPP_DIR}/common" \
  -I"${LLAMA_CPP_DIR}/ggml/include" \
  -I"${LLAMA_CPP_DIR}/vendor" \
  "${SCRIPT_DIR}/desktop_target_runtime.cpp" \
  "${COMMON_LIB}" \
  -L"${LLAMA_BIN_DIR}" \
  -Wl,-rpath,"${LLAMA_BIN_DIR}" \
  -lllama -lggml -lggml-cpu -lggml-base \
  -lssl -lcrypto -ldl -lpthread -lm \
  -o "${OUTPUT_PATH}"

echo "Built ${OUTPUT_PATH}"

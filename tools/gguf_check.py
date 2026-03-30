from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a GGUF file using the local llama.cpp gguf-py reader."
    )
    parser.add_argument("model", type=Path, help="Path to the GGUF model file")
    parser.add_argument(
        "--llama-cpp-dir",
        type=Path,
        default=Path(r"C:\Users\JXZ\AndroidStudioProjects\llama.cpp"),
        help="Path to the local llama.cpp checkout",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    model_path = args.model.resolve()
    if not model_path.exists():
        print(f"Model file not found: {model_path}", file=sys.stderr)
        return 1

    gguf_py_dir = args.llama_cpp_dir / "gguf-py"
    if not gguf_py_dir.exists():
        print(f"gguf-py not found under: {gguf_py_dir}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(gguf_py_dir))

    from gguf.gguf_reader import GGUFReader  # noqa: PLC0415

    reader = GGUFReader(str(model_path))

    print(f"model_path={model_path}")
    print(f"size_bytes={model_path.stat().st_size}")
    print(f"tensor_count={len(reader.tensors)}")
    print(f"field_count={len(reader.fields)}")

    interesting_keys = [
        "general.architecture",
        "general.name",
        "general.basename",
        "general.file_type",
        "general.quantization_version",
        "llama.context_length",
        "llama.embedding_length",
        "tokenizer.ggml.model",
    ]

    for key in interesting_keys:
        field = reader.get_field(key)
        if field is None:
            print(f"{key}=<missing>")
            continue

        raw_parts = [str(part) for part in field.parts[:8]]
        rendered = " | ".join(raw_parts) if raw_parts else "<empty>"
        print(f"{key}={rendered}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

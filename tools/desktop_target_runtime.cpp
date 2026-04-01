#include <iostream>
#include <string>

// This helper is the native correctness-lane boundary for `llama_eagle_aligned`.
//
// Planned final responsibilities:
// - load one persistent desktop target model/runtime
// - tokenize / detokenize with the exact desktop tokenizer
// - keep persistent target sessions
// - expose full-logits `p(x | prefix_i)` reads
// - run exact paper-style `min(1, p/q)` acceptance
// - sample exact residual correction `max(p-q, 0)`
//
// The Python HTTP service talks to this process over JSON lines.
// This file is intentionally only a first skeleton node; it exists so the exact
// lane has a concrete native helper boundary and can fail closed instead of
// silently reusing the approximate llama-server verifier path.

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.find("\"command\":\"shutdown\"") != std::string::npos) {
            std::cout << "{\"ok\":true,\"status\":\"shutdown\"}" << std::endl;
            return 0;
        }

        std::cout
            << "{\"ok\":false,"
            << "\"error\":\"desktop_target_runtime.cpp skeleton is present but exact native helper commands are not implemented yet.\"}"
            << std::endl;
    }

    return 0;
}

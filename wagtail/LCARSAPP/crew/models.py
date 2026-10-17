"""Known local models: picker labels and per-model settings."""

# Known models: a readable label and server settings. Any other .gguf still works with defaults.
MODEL_PROFILES = {
    "Qwen3.5-9B-Q4_K_M": {"label": "Qwen3.5 9B"},
    "gemma-4-12b-it-Q4_K_M": {"label": "Gemma 4 12B"},
    # A reasoning model: it thinks out loud in its answer, so it needs a larger
    # response budget than the 1,500-token default
    "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M": {"label": "DeepSeek R1-0528 (Qwen3 8B, reasoning)",
                                          "reasoning_budget": 0, "max_tokens": 4096},
}

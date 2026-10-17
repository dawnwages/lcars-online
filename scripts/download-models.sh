#!/usr/bin/env bash
# Download local models (GGUF) for the crew. Resumable; verifies size.
#   scripts/download-models.sh qwen     # Qwen3.5-9B Q4_K_M, 5.7 GB (default; tested)
#   scripts/download-models.sh gemma    # Gemma 4 12B Q4_K_M, 7.1 GB
#   scripts/download-models.sh deepseek # DeepSeek-R1-0528-Qwen3-8B Q4_K_M, 5.0 GB (reasoning)
#   scripts/download-models.sh all
# Saves to $CREW_MODELS_DIR (default ~/models). Any .gguf there appears in the LCARS model picker.
set -euo pipefail

DIR="${CREW_MODELS_DIR:-$HOME/models}"
mkdir -p "$DIR"

download() {
  local file="$1" url="$2"
  local expected
  expected=$(curl -sIL "$url" | grep -i '^content-length' | tail -1 | tr -dc '0-9')
  if [[ -f "$DIR/$file" ]] && [[ "$(wc -c < "$DIR/$file" | tr -d ' ')" == "$expected" ]]; then
    echo "✓ $file already downloaded"
    return
  fi
  echo "↓ $file ($(( expected / 1000000000 )).$(( expected % 1000000000 / 100000000 )) GB) to $DIR"
  # Download to .part so a half-finished model never shows up in the model picker
  [[ -f "$DIR/$file" && ! -f "$DIR/$file.part" ]] && mv "$DIR/$file" "$DIR/$file.part"
  curl -L -C - --retry 10 --retry-delay 10 --retry-all-errors --progress-bar -o "$DIR/$file.part" "$url"
  local got
  got=$(wc -c < "$DIR/$file.part" | tr -d ' ')
  [[ "$got" == "$expected" ]] || { echo "✗ $file is $got bytes, expected $expected. Run again to resume."; exit 1; }
  mv "$DIR/$file.part" "$DIR/$file"
  echo "✓ $file"
}

qwen()  { download Qwen3.5-9B-Q4_K_M.gguf https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/Qwen3.5-9B-Q4_K_M.gguf; }
gemma() { download gemma-4-12b-it-Q4_K_M.gguf https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/resolve/main/gemma-4-12b-it-Q4_K_M.gguf; }
deepseek() { download DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf https://huggingface.co/unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF/resolve/main/DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf; }

case "${1:-qwen}" in
  qwen) qwen ;;
  gemma) gemma ;;
  deepseek) deepseek ;;
  all) qwen; gemma; deepseek ;;
  *) echo "Usage: $0 [qwen|gemma|deepseek|all]"; exit 2 ;;
esac

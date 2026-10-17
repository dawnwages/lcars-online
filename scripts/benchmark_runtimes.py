"""Compare llama.cpp and MLX on this machine with the crew's real workload.

    cd wagtail/LCARSAPP
    uv run --with mlx-lm python ../../scripts/benchmark_runtimes.py \
        --gguf ~/models/Qwen3.5-9B-Q4_K_M.gguf --mlx ~/models/mlx/Qwen3.5-9B-4bit

Runs each runtime's OpenAI-compatible server in turn (never both: memory), sends the
same prompts, and reports time to first token, generation speed, total time, and
whether a tool call comes back. Results print as a table and save to docs/.
MLX runs on Apple Silicon only.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "wagtail" / "LCARSAPP"
sys.path.insert(0, str(APP))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "LCARSAPP.settings.dev")

PORT = 8090  # not the crew's 8089, so a running crew model is never disturbed
OUTPUT_TOKENS = 256
TOOL = {"type": "function", "function": {
    "name": "count_population", "description": "Count planets after applying filters in order",
    "parameters": {"type": "object", "properties": {"filters": {"type": "array", "items": {
        "type": "object", "properties": {"column": {"type": "string"}, "op": {"type": "string"},
                                         "value": {}}, "required": ["column", "op"]}}},
        "required": ["filters"]}}}


def crew_prompt():
    """The Science Officer's real instructions and inputs for one planning step."""
    import django
    django.setup()
    from crew import agents, science
    df, _ = science.load_snapshot()
    card = science.data_card(df)
    hazards = [
        {"id": "H1", "name": "Discovery-method selection bias",
         "evidence": f"median period {card['median_orbital_period_days_by_method']}",
         "implication": "Restrict to or compare by discovery method"},
        {"id": "H2", "name": "Inferred masses",
         "evidence": f"{card['mass_from_mass_radius_relation_pct']}% from the mass-radius relation",
         "implication": "Do not treat mass as measured"},
        {"id": "H3", "name": "Radius precision", "evidence": f"{card['radius_relative_error_quantiles']}",
         "implication": "Consider a precision cut"},
    ]
    user = (f"Question: Is there a gap in the sizes of small planets?\n\n"
            f"{agents.planning_facts(card)}\n\n{agents.hazard_checklist(hazards)}\n\n"
            f"Columns: {card['columns']}\n\nWrite out your reasoning about the population "
            "you would choose and why, step by step.")
    return [{"role": "system", "content": agents.SCIENCE}, {"role": "user", "content": user}]


WORKLOADS = {
    "short prompt": [{"role": "user", "content":
                      "Explain in a few paragraphs what an exoplanet transit is and what it measures."}],
}


def wait_ready(seconds=240):
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            return time.monotonic() - start
        except Exception:
            time.sleep(1)
    raise RuntimeError("server did not start")


def fresh(messages):
    """Prefix a unique tag so no runtime can reuse a cached prompt (warm-up included)."""
    import uuid
    first = dict(messages[0])
    first["content"] = f"[run {uuid.uuid4().hex[:12]}] " + first["content"]
    return [first] + messages[1:]


def stream(model, messages, max_tokens=OUTPUT_TOKENS):
    """Return (time to first token, total time, completion tokens) for one streamed request."""
    messages = fresh(messages)
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.monotonic()
    first, tokens, chunks = None, None, 0
    with urllib.request.urlopen(req, timeout=900) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            data = json.loads(line[5:])
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            # Runtimes stream thinking under different names; any generated text counts
            text = (delta.get("content") or delta.get("reasoning_content")
                    or delta.get("reasoning") or delta.get("thinking"))
            if text and first is None:
                first = time.monotonic() - start
            if text:
                chunks += 1
            if data.get("usage"):
                tokens = data["usage"].get("completion_tokens")
    total = time.monotonic() - start
    return first or total, total, tokens or chunks


def tool_call(model):
    body = {"model": model, "temperature": 0, "max_tokens": 300, "tools": [TOOL], "messages": [{
        "role": "user", "content": "How many transit-discovered planets are there? Call "
                                   "count_population with column disc_method, op eq, value tran."}]}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        msg = json.load(urllib.request.urlopen(req, timeout=300))["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        return f"{calls[0]['function']['name']}" if calls else "no tool call returned"
    except Exception as exc:
        return f"error: {exc}"[:80]


def run(name, cmd, model_id):
    print(f"\n== {name}: starting server")
    log = open(REPO / "wagtail" / "LCARSAPP" / "run" / f"bench-{name}.log", "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        load = wait_ready()
        print(f"   ready in {load:.0f}s")
        results = {"load_seconds": round(load, 1), "workloads": {}}
        for label, messages in WORKLOADS.items():
            stream(model_id, messages, max_tokens=16)  # warm-up
            ttft, total, tokens = stream(model_id, messages)
            gen_rate = (tokens - 1) / (total - ttft) if total - ttft > 0.5 and tokens > 1 else None
            results["workloads"][label] = {
                "time_to_first_token_s": round(ttft, 2), "total_s": round(total, 1),
                "output_tokens": tokens,
                "generation_tokens_per_s": round(gen_rate, 1) if gen_rate else None,
                "end_to_end_tokens_per_s": round(tokens / total, 1)}
            print(f"   {label}: first token {ttft:.1f}s, generation "
                  f"{gen_rate and round(gen_rate, 1)} tok/s, total {total:.1f}s for {tokens} tokens")
        results["tool_call"] = tool_call(model_id)
        print(f"   tool call: {results['tool_call']}")
        return results
    finally:
        os.killpg(proc.pid, 15)
        proc.wait(timeout=30)
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gguf", required=True, type=Path)
    parser.add_argument("--mlx", required=True, type=Path)
    args = parser.parse_args()
    WORKLOADS["crew planning prompt"] = crew_prompt()
    (APP / "run").mkdir(exist_ok=True)

    llama = shutil.which("llama-server") or "/opt/homebrew/bin/llama-server"
    results = {
        "llama.cpp": run("llama.cpp", [llama, "-m", str(args.gguf.expanduser()), "--port", str(PORT),
                                       "--host", "127.0.0.1", "-c", "16384", "-ngl", "99", "-fa", "on",
                                       "-np", "1", "--jinja", "--reasoning-budget", "0",
                                       "--alias", "bench"], "bench"),
        "MLX": run("MLX", [sys.executable, "-m", "mlx_lm.server", "--model",
                           str(args.mlx.expanduser()), "--port", str(PORT), "--host", "127.0.0.1"],
                   str(args.mlx.expanduser())),
    }
    machine = f"{platform.machine()} {subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True).stdout.strip()}"
    print(f"\nRuntime comparison on {machine}")
    print(f"{'workload':24} {'runtime':10} {'first token':>12} {'gen tok/s':>10} {'total':>8} {'end-to-end tok/s':>17}")
    for label in WORKLOADS:
        for runtime, r in results.items():
            w = r["workloads"][label]
            print(f"{label:24} {runtime:10} {w['time_to_first_token_s']:>11}s "
                  f"{str(w['generation_tokens_per_s']):>10} {w['total_s']:>7}s {w['end_to_end_tokens_per_s']:>17}")
    out = REPO / "docs" / "runtime-benchmark.json"
    out.write_text(json.dumps({"machine": machine, "date": time.strftime("%Y-%m-%d"),
                               "gguf": str(args.gguf.name), "mlx": str(args.mlx.name),
                               "output_tokens": OUTPUT_TOKENS, "results": results}, indent=2))
    print(f"Saved {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()

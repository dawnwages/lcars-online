"""Start and stop the local model server and mission processes for the bridge.

One model and one mission at a time: a 16 GB machine can't hold more.
Process IDs and logs live in RUN_DIR (gitignored).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

from crew.agents import MODEL_KEY

PROJECT_DIR = Path(__file__).resolve().parents[1]          # wagtail/LCARSAPP
REPO_DIR = PROJECT_DIR.parents[1]
RUN_DIR = PROJECT_DIR / "run"
MODELS_DIR = Path(os.environ.get("CREW_MODELS_DIR", Path.home() / "models")).expanduser()
MODEL_PORT = 8089
TEST_MODEL = "test"

# The model server needs llama.cpp on PATH; Homebrew installs it here
SERVER_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"])


def _pid_file(name):
    RUN_DIR.mkdir(exist_ok=True)
    return RUN_DIR / f"{name}.pid"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def _read_pid(name):
    try:
        pid = int(_pid_file(name).read_text())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def list_models():
    models = [{"name": TEST_MODEL, "label": "Test model (no LLM, random output)", "size_gb": 0}]
    for path in sorted(MODELS_DIR.glob("*.gguf")):
        models.append({"name": path.stem, "label": path.stem,
                       "size_gb": round(path.stat().st_size / 1e9, 1)})
    return models


def loaded_model():
    """The model the server is serving, or None if it isn't up (yet)."""
    req = urllib.request.Request(f"http://127.0.0.1:{MODEL_PORT}/v1/models",
                                 headers={"Authorization": f"Bearer {MODEL_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=1) as resp:
            return json.load(resp)["data"][0]["id"]
    except Exception:
        return None


def model_status():
    pid = _read_pid("model-server")
    loaded = loaded_model()
    return {"process_running": bool(pid), "loaded": loaded,
            "starting": bool(pid) and loaded is None}


def stop_model():
    pid = _read_pid("model-server")
    if pid:
        os.killpg(pid, signal.SIGTERM)
    _pid_file("model-server").unlink(missing_ok=True)


def start_model(name):
    """Serve the named model, stopping any other model first."""
    path = MODELS_DIR / f"{name}.gguf"
    if name not in {m["name"] for m in list_models()} or not path.exists():
        raise ValueError(f"Unknown model: {name}")
    if _read_pid("model-server") and loaded_model() == name:
        return
    stop_model()
    RUN_DIR.mkdir(exist_ok=True)
    with open(RUN_DIR / "model-server.log", "ab") as log:
        proc = subprocess.Popen(
            [_caffeinate(), "-is", str(REPO_DIR / "scripts" / "model-server.sh"), str(path)]
            if shutil.which("caffeinate") else [str(REPO_DIR / "scripts" / "model-server.sh"), str(path)],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, "PATH": SERVER_PATH, "CREW_MODEL_KEY": MODEL_KEY})
    _pid_file("model-server").write_text(str(proc.pid))


def _caffeinate():
    return shutil.which("caffeinate") or "caffeinate"


# Commands that run the crew against the model and log as missions
CREW_COMMANDS = ("run_mission", "bakeoff", "red_team")


def mission_processes_running():
    """True if any crew process is alive (mission, bake-off or red team), from here or a terminal."""
    pattern = "manage.py (" + "|".join(CREW_COMMANDS) + ")"
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return bool(out.stdout.strip())


def launch_mission(mission):
    """Run the mission in its own process, kept awake, logging to RUN_DIR."""
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1"}
    if mission.model_name == TEST_MODEL:
        env["CREW_MODEL_URL"] = "test"
    else:
        env["CREW_MODEL"] = mission.model_name
    cmd = [sys.executable, "manage.py", "run_mission", "--mission-id", str(mission.pk),
           "--wait-for-model", "180"]
    if shutil.which("caffeinate"):
        cmd = [_caffeinate(), "-is"] + cmd
    RUN_DIR.mkdir(exist_ok=True)
    with open(RUN_DIR / f"mission-{mission.pk}.log", "ab") as log:
        proc = subprocess.Popen(cmd, cwd=PROJECT_DIR, env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    _pid_file("mission").write_text(str(proc.pid))
    return proc.pid


def ingest_running():
    out = subprocess.run(["pgrep", "-f", "manage.py ingest_archive"], capture_output=True, text=True)
    return bool(out.stdout.strip())


def launch_ingest():
    """Fetch the archive now, recorded on the persistent Prefect server when it is up."""
    env = dict(os.environ)
    api = env.get("PREFECT_API_URL", "http://127.0.0.1:4200/api")
    try:
        urllib.request.urlopen(f"{api}/health", timeout=2)
        env["PREFECT_API_URL"] = api
    except Exception:
        pass  # no persistent server: Prefect uses a temporary one for this run
    RUN_DIR.mkdir(exist_ok=True)
    with open(RUN_DIR / "ingest.log", "ab") as log:
        subprocess.Popen([sys.executable, "manage.py", "ingest_archive"], cwd=PROJECT_DIR, env=env,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

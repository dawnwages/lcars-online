# Recording missions

The talk uses recorded missions, not live demos. Every mission, recorded or not, is logged in the Django admin under **Missions** with its full event log, gates, plan, results, and review.

## Before recording

1. **Plug in the power adapter and keep the Mac awake.** macOS sleeps an idle laptop, which pauses the model mid-mission. Wrap long runs in `caffeinate -is`.
2. **Close everything you don't need.** On a 16 GB M1, the model takes about 6 GB. Leave room for the browser, the Django server, and the screen recorder.
3. **Start the model server** (port 8089):

   ```bash
   caffeinate -is scripts/model-server.sh ~/models/Qwen3.5-9B-Q4_K_M.gguf
   ```

4. **Start Django** in another terminal (from `wagtail/LCARSAPP`):

   ```bash
   uv run python manage.py runserver
   ```

5. **Optional: a persistent Prefect UI.** Missions run on a temporary Prefect server by default, which disappears afterward. To show flow runs in the Prefect UI, start one first and point the crew at it:

   ```bash
   uv run prefect server start
   export PREFECT_API_URL=http://127.0.0.1:4200/api
   ```

## Two ways to record a mission

**With live approvals (best for the talk video).** The mission waits at each gate, and you approve it on camera in the admin under Missions → Gates → select the gate → "Approve selected gates (make it so)".

```bash
cd wagtail/LCARSAPP
CREW_MODEL=Qwen3.5-9B-Q4_K_M CREW_OUTPUT_MODE=tool caffeinate -is uv run python manage.py run_mission
```

**Unattended.** Every gate is pre-approved, and the log records who pre-approved it and how.

```bash
CREW_MODEL=Qwen3.5-9B-Q4_K_M CREW_OUTPUT_MODE=tool caffeinate -is uv run python manage.py run_mission --approve-as "Dawn Wages"
```

Add `--negative-control` to record the run where the crew should find nothing.

## Capture

- Use macOS Screenshot (Shift-Command-5) → Record Selected Portion, or OBS.
- A mission takes several minutes on the M1. Record the whole run, then speed up the waiting stretches in editing. Say on screen that the footage is sped up.
- After uploading, paste the video link into the mission's **Recording URL** field in the admin, so each recording points back to its exact run: model, data snapshot hash, seed, git commit, and every decision.

## After recording

Grade the recorded missions:

```bash
uv run deepeval test run evals/test_missions.py
```

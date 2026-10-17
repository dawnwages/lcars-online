# Recording missions

The talk uses recorded missions, not live demos. Every mission, recorded or not, is kept in the mission log (the bridge's **Missions** view and the Django admin) with its full event log, gates, plan, results, and review.

## Before recording

1. **Plug in the power adapter.** `scripts/start.sh` keeps the Mac awake while services run, but long missions on battery are slow.
2. **Close what you don't need.** On a 16 GB M1 the model uses about 6 GB; leave room for the browser and the screen recorder.
3. **Start everything and log in:**

   ```bash
   scripts/start.sh
   ```

   Log in at http://localhost:8000/admin as `captain` (password in `wagtail/LCARSAPP/.env.local`), then open http://localhost:8080 → **Missions**.
4. **Fetch fresh data** (optional): **New mission → Fetch latest data**. The panel shows the planet count and what changed.

## Recording a mission (best for the talk)

1. **New mission**: keep the question, choose **Qwen3.5-9B**, type **Analysis**, seed **0**, then **Engage**. The model loads in about 10 seconds.
2. Watch the event stream. At each gate, read what's being approved (the data card's hazards; the plan and how it answers each hazard), then **Make it so**. Add a note; it goes in the log.
3. A mission takes about 15–20 minutes on an M1. Record the whole run, then speed up the waiting in editing, and say on screen that it's sped up.
4. Record a second mission with type **Negative control**. The crew should find no valley.

Moments worth keeping in the edit:

- The Science Officer's plan being **returned** by the validator ("H3 points to a filter on pl_rade…") and the revised plan.
- Engineering's specification curve and negative control.
- Tactical's verdict, and the draft Captain's Log you publish at the last gate.

## Unattended recordings

From `wagtail/LCARSAPP`, with every gate pre-approved (the log records who pre-approved it and how):

```bash
CREW_MODEL=Qwen3.5-9B-Q4_K_M uv run python manage.py run_mission --approve-as "Dawn Wages"
```

This needs the model server running: launch any mission from the bridge first, or run `scripts/model-server.sh ~/models/Qwen3.5-9B-Q4_K_M.gguf`.

## After recording

- Paste the video link into the mission's **Recording URL** in the Django admin, so each recording points back to its exact run: model, data snapshot and hash, seed, git commit, and every decision.
- Grade the missions:

  ```bash
  cd wagtail/LCARSAPP && uv run deepeval test run evals/test_missions.py
  ```

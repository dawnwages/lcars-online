# Talk plan: To Boldly Go

**Slot:** Tuesday, October 20, 2026, 10:30 to 11:00 a.m. ET, All Things Open, Raleigh. Plan for 25 minutes of content and 5 minutes of Q&A.
**Time left from October 7:** 13 days.

## What the abstract promises

Attendees signed up for these things, so the talk has to show each one at least briefly:

1. LCARS Online, a Star Trek interface that is a working system, not just a skin
2. A multi-agent Python backend
3. Data ingestion
4. Anomaly detection
5. Natural-language querying
6. Report generation
7. What "agentic" means in data science: specialized agents with tools, memory, and decision-making that take over part of a data scientist's workload

## Scope rule

**One dataset, four crew members, one demo path. Everything else goes on a slide.**

### In scope (must work live)

- [ ] **Ops:** load the exoplanet snapshot. The live API fetch is a bonus; the saved snapshot is what the demo depends on.
- [ ] **Computer:** answer 3 rehearsed questions with read-only SQL, with each query shown on screen.
- [ ] **Science Officer:** flag the strangest planets and explain each flag in a sentence.
- [ ] **Log:** write a Captain's Log as a Wagtail draft, publish it in the admin, and show it appear in LCARS.
- [ ] **Bridge:** route a request to the right crew member.
- [ ] **One validation moment:** an eval with a known answer catches a wrong answer from the Computer.

### Slide only (mention, don't build live)

- Prefect scheduling of "away missions" (build it if there's time; it's one screenshot of a flow run)
- Tracing with OpenTelemetry
- Red teaming
- Deployment

### Out of scope

- Multiple datasets
- Free-form questions from the audience during the demo (take them in Q&A instead)
- Authentication or multi-user features

## Talk structure (25 minutes)

| Time | Section | What's on screen |
|---|---|---|
| 0:00–3:00 | **Cold open.** "Computer, which worlds are the strangest?" Live answer, no slides yet. | LCARS |
| 3:00–7:00 | **What agentic means in data science.** A crew instead of one chatbot: narrow jobs, allowed tools, memory, decisions. | Slides |
| 7:00–9:00 | **The mission and the data.** 6,375 planets, 34 years of discoveries. Ops brings them aboard. | LCARS + code |
| 9:00–12:00 | **Computer: plain-English questions.** Show the generated SQL and why it's read-only. | LCARS + code |
| 12:00–15:00 | **Science Officer: anomalies.** Deterministic statistics find the outliers; the agent explains them. | LCARS |
| 15:00–18:00 | **Captain's Log: reports.** The agent writes a draft, you publish it, and it appears on the bridge. | Wagtail admin → LCARS |
| 18:00–22:00 | **Trust, but verify.** The eval suite catches a wrong answer. The rules live in code: read-only, drafts only, a human publishes. | Terminal |
| 22:00–25:00 | **What to take home.** The pattern works for any dataset. Repo link and QR code. "Make it so." | Slides |

## Build schedule

| Date | Goal |
|---|---|
| Wed Oct 7 | Lock scope, create the repo, save the data snapshot |
| Thu Oct 8 | Ops: snapshot loader and a `Planet` table |
| Fri Oct 9 | Computer: read-only SQL tool, with 3 demo questions passing |
| Sat Oct 10 | Science Officer: outlier scan and explanations |
| Sun Oct 11 | Log: draft Wagtail pages; LCARS panel for logs |
| Mon Oct 12 | Bridge routing; LCARS question input |
| **Tue Oct 13** | **Eval suite with ~15 known-answer questions. Feature freeze at end of day.** |
| Wed Oct 14 | Slides |
| Thu Oct 15 | Record a backup video of the full demo |
| Fri Oct 16 | First full timed rehearsal |
| Sat–Sun Oct 17–18 | Rehearse; fix bugs only, no new features |
| Mon Oct 19 | Arrive; test the projector and room setup; confirm the offline mode works |
| Tue Oct 20 | Give the talk; make the repo public |

**If you fall behind,** cut in this order: Prefect (make it a slide), the live API fetch (use the snapshot), the Bridge (call the crew directly), and LCARS input (ask questions from the terminal).

## Demo risks

| Risk | Mitigation |
|---|---|
| Conference Wi-Fi | Use the saved data snapshot; a local model or cached responses as a fallback; the backup video |
| Model gives a different answer on stage | Rehearse fixed questions and pin the model version and temperature |
| Live coding takes too long | Pre-write the code and narrate it; never type it live |
| Projector resolution breaks the LCARS layout | Test at 1920×1080 and 1280×720 before Oct 19 |

## Open decisions

- **Model provider.** It's open; PydanticAI works with any provider. Decide by Oct 9.
- **Data store for the snapshot.** It's open; decide by Oct 8.
- **Repo visibility.** Private until the talk, then make it public for the slide link.

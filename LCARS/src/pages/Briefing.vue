<template>
  <div class="briefing">
    <nav class="briefing-nav">
      <button v-for="s in sections" :key="s.id" :class="{ active: current === s.id }"
              @click="go(s.id)">{{ s.label }}</button>
    </nav>

    <div class="briefing-body" ref="body">
      <section id="crew">
        <h2>The crew</h2>
        <p>
          Five stations work one question. Four are AI agents, each a narrow
          <a href="https://ai.pydantic.dev/" target="_blank" rel="noopener">PydanticAI</a> agent
          running on a local model, and one is plain code. <b>No agent ever computes a number:</b>
          agents decide what to run and explain the results; deterministic Python does the math.
          You are the sixth station: the captain, who approves each step.
        </p>
        <div class="cards">
          <div class="card" v-for="a in crew" :key="a.name" :style="{ borderColor: a.color }">
            <div class="card-title" :style="{ color: a.color }">{{ a.name }}</div>
            <div class="card-role">{{ a.role }}</div>
            <p>{{ a.job }}</p>
            <dl>
              <dt>Produces</dt><dd>{{ a.output }}</dd>
              <dt>Tools</dt><dd>{{ a.tools }}</dd>
              <dt>Held to</dt><dd>{{ a.rules }}</dd>
            </dl>
          </div>
        </div>
      </section>

      <section id="mission">
        <h2>A mission, step by step</h2>
        <p>
          A mission is one
          <a href="https://www.prefect.io/" target="_blank" rel="noopener">Prefect</a> flow. Every
          tool call, model output, decision and approval is written to an append-only mission log
          (the event stream in Missions), with timing and token counts.
        </p>
        <ol class="steps">
          <li v-for="(s, i) in steps" :key="i" :class="{ gate: s.gate }">
            <div class="step-head"><span class="step-n">{{ s.gate ? '◆' : i + 1 }}</span>{{ s.title }}</div>
            <p>{{ s.text }}</p>
          </li>
        </ol>
        <p class="note">
          <b>Negative-control missions</b> run the same steps but replace the planet radii with a
          synthetic single-peak sample. A correct crew finds no valley. <b>Unattended</b> missions
          pre-approve every gate, and the log records who pre-approved it and how.
        </p>
      </section>

      <section id="analysis">
        <h2>The analysis: a gap in planet sizes</h2>
        <h3>The science</h3>
        <p>
          Planets between Earth's size and about four times Earth's size fall into two groups:
          <b>super-Earths</b> near 1.3 Earth radii, rocky with little atmosphere, and
          <b>sub-Neptunes</b> near 2.4 Earth radii, rocky cores in thick gas envelopes. Planets
          in between, about 1.5 to 2.0 Earth radii, are rare. This <b>radius valley</b> was first
          measured clearly by Fulton et al. (2017); the leading explanation is that starlight or
          the planet's own core heat strips the atmosphere from smaller close-in planets. Because
          the answer is known, it tests whether the crew does the analysis well.
        </p>

        <h3>The data</h3>
        <p>
          The NASA Exoplanet Archive's <code>pscomppars</code> table: one row per confirmed planet,
          with the best available value for each of 20 columns (radius and its error, mass and where
          it came from, orbital period, discovery method, host star). A Prefect flow fetches it daily
          at 06:00 Eastern, validates it, and saves a snapshot with its SHA-256 hash and what changed.
          Missions analyze the newest snapshot and record which one.
          <span v-if="snapshot"> Current data: <b>{{ snapshot.rows?.toLocaleString() }} planets</b>,
            fetched {{ new Date(snapshot.data_fetched_at).toLocaleDateString() }}.</span>
        </p>

        <h3>The method (Engineering, in code)</h3>
        <ol class="method">
          <li v-for="m in method" :key="m.title"><b>{{ m.title }}.</b> <span v-html="m.text"></span></li>
        </ol>

        <h3>Reading the results</h3>
        <table>
          <thead><tr><th>You see</th><th>It means</th></tr></thead>
          <tbody>
            <tr v-for="r in readings" :key="r.see"><td>{{ r.see }}</td><td>{{ r.means }}</td></tr>
          </tbody>
        </table>

        <h3>What the data shows</h3>
        <p>
          Computed with this code on the archive snapshot of October 7, 2026, transit-discovered
          planets only: with radius error under 10% (1,421 planets in the window), Silverman's test
          gives p &lt; 0.003 and the valley sits at 1.75 Earth radii (95% interval 1.66 to 1.82). The
          valley appears at 1.72 to 1.76 Earth radii at every precision cut, but it is significant
          only where enough planets remain: at the strictest 5% cut (about 575 planets) p is about
          0.2. The negative control finds nothing (p about 0.5).
        </p>
      </section>

      <section id="guardrails">
        <h2>Guardrails in code</h2>
        <p>Each of these exists because a real mission failed without it.</p>
        <ul class="guards">
          <li v-for="g in guardrails" :key="g.title"><b>{{ g.title }}.</b> {{ g.text }}</li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script>
import MissionService from '../services/MissionService'

const CREW = [
  { name: 'Ops', role: 'Data audit', color: 'var(--lcars-color-a1)',
    job: 'Reads a data card computed by code (discovery-method counts, missing values, how masses were obtained, radius precision, what changed since the last fetch) and lists the hazards an analyst must handle.',
    output: 'A brief and numbered hazards (H1, H2, ...), each with evidence from the data card',
    tools: 'None; everything it sees is computed by code',
    rules: 'A response budget; schema-checked output' },
  { name: 'Science Officer', role: 'Planner', color: 'var(--lcars-color-b6)',
    job: 'Writes the analysis plan before any results exist: which planets to study, the smoothing bandwidth, the significance level, what result would falsify the hypothesis, alternatives rejected, risks, and a response to every hazard.',
    output: 'A typed AnalysisPlan',
    tools: 'count_population, breakdown_population, column_summary',
    rules: 'Every hazard answered (filter, accepted risk, or not applicable); valid filters; at most 10 tool calls' },
  { name: 'Engineering', role: 'Code, no model', color: 'var(--lcars-color-b2)',
    job: 'Runs the approved plan exactly and computes every statistic, then states in code what each result means. Refuses plans with invalid filters or too few planets.',
    output: 'Results and their interpretation',
    tools: 'pandas and NumPy (crew/science.py)',
    rules: 'Deterministic; seeded; data checked against its hash' },
  { name: 'Tactical', role: 'Adversarial reviewer', color: 'var(--lcars-color-a6)',
    job: 'Looks for reasons not to believe the result: selection bias, circular use of inferred values, p-hacking, low power, robustness. Can accept, ask for one revision, or reject.',
    output: 'A Review with issues and a verdict',
    tools: 'breakdown_population, count_population',
    rules: 'May cite only numbers it was given or counted; at most 8 tool calls' },
  { name: "Captain's Log", role: 'Report', color: 'var(--lcars-color-b5)',
    job: 'Writes the mission report for data scientists: the finding with its statistics, how the population was chosen, what the reviewer raised, and the limitations.',
    output: 'A draft Wagtail page you decide whether to publish',
    tools: 'None',
    rules: 'Must cite the result statistics and invent none; "not significant at this sample size" is not "no evidence"' },
  { name: 'Captain', role: 'You', color: 'var(--lcars-color-b1)',
    job: 'Approves the data card, the plan, any revised plan, and publishing, from the bridge or the admin. Every decision is logged with who made it and how.',
    output: 'Approvals and notes', tools: 'Make it so / Belay that', rules: 'Login, permission, CSRF token' },
]

const STEPS = [
  { title: 'Launch', text: 'From New mission: a question, a model, a mission type and a seed. The model server starts if needed (one model in memory at a time).' },
  { title: 'Ops audits the data', text: 'Load the newest snapshot (hash-checked), compute the data card, and have Ops list the hazards with evidence.' },
  { title: 'Gate: approve the data card', gate: true, text: 'You see the hazards and the data facts before anything is planned.' },
  { title: 'The Science Officer plans', text: 'It may count planets and inspect columns first. A plan that leaves a hazard unanswered, points to an invalid filter, or filters on a column the method never uses is sent back with a specific correction (logged as "Plan returned").' },
  { title: 'Gate: approve the plan', gate: true, text: 'Pre-registration: the plan is fixed before any result exists, so filters can\'t be chosen after seeing p-values.' },
  { title: 'Engineering runs it', text: 'Apply the filters, estimate the size distribution, test for a valley, bootstrap its location, run the precision-cut sweep and the negative control, and state what it all means.' },
  { title: 'Tactical reviews', text: 'An adversarial review. If it asks for a revision, the Science Officer plans again (once), you approve the revision, and Engineering reruns. If a revision can\'t be produced, the report uses the approved result and says the reviewer\'s issues are unresolved.' },
  { title: "The Captain's Log", text: 'The report is written as a draft page; its numbers are checked against the results.' },
  { title: 'Gate: publish', gate: true, text: 'Publish and the report appears under View Posts. Evals then grade the mission from its log.' },
]

const METHOD = [
  { title: 'Population', text: 'Apply the plan\'s filters in order; keep planets between 1 and 4 Earth radii; refuse fewer than 200.' },
  { title: 'Size distribution', text: 'A Gaussian kernel density estimate of log<sub>10</sub>(radius) on 400 points across the window, at the plan\'s bandwidth (0.02 to 0.08 dex) and at 0.03 and 0.05 dex for comparison.' },
  { title: "Silverman's test", text: 'H<sub>0</sub>: at most one mode. Find the critical bandwidth h<sub>crit</sub>, the smallest bandwidth with one mode (bisection). Draw 500 smoothed bootstrap samples at h<sub>crit</sub> with Silverman\'s variance correction; p is the share that still have more than one mode. Small p means a valley. The test is conservative.' },
  { title: 'Valley location', text: 'The lowest point between the two highest peaks, its depth relative to the peaks, and a 95% percentile interval from 500 bootstrap resamples (plus how often a valley appears at all).' },
  { title: 'Specification curve', text: 'Always run, whatever the plan says: repeat the analysis with no precision cut and with radius error under 20%, 15%, 10%, 8% and 5%. A conclusion must hold across the sweep, not at one hand-picked cut.' },
  { title: 'Negative control', text: 'Replace the radii with a log-normal sample of the same size, mean and spread (one peak by construction) and rerun the test. It should find nothing.' },
  { title: 'Interpretation', text: 'Engineering states, in code, whether the main test is significant at the plan\'s alpha, whether the negative control passed, and how many precision cuts agree.' },
]

const READINGS = [
  { see: 'p below alpha, valley at 1.5 to 2.1 Earth radii, tight interval, holds across the sweep, control passes', means: 'Evidence for two groups of planet sizes, consistent with the published valley.' },
  { see: 'A valley is visible but p is at or above alpha', means: 'Not evidence of no valley. Usually too few planets for the test; report "not significant at this sample size".' },
  { see: 'Significant at one precision cut but not its neighbors', means: 'Fragile. Choosing that cut after the fact would be p-hacking.' },
  { see: 'Significant only when all discovery methods are mixed', means: 'Suspect: mixed selection effects can create or hide structure.' },
  { see: 'The negative control finds a valley', means: 'The method is broken; trust nothing from that mission.' },
  { see: 'Plan refused', means: 'Invalid filter or too few planets; Engineering won\'t run a test that can\'t mean anything.' },
]

const GUARDRAILS = [
  { title: 'Hazards must be answered', text: 'Ops\' hazards are numbered and every plan must answer each one. Without this, the planner ignored selection effects in every run.' },
  { title: 'Not applicable is an option', text: 'A hazard about a column the method doesn\'t use (mass) is marked not applicable, not filtered. Filtering for it once cut the sample from 3,352 to 621 planets and the crew reported "no evidence".' },
  { title: 'Tools explain errors', text: 'A filter with no value, a non-number on a numeric column, or a text value that never occurs (\'transit\' instead of \'tran\') is refused with the reason and the real values. Silently matching zero planets once cost a 34-minute loop.' },
  { title: 'Required fields', text: 'A filter\'s value is a required field; when it was optional, constrained tool calls left it out even when the model\'s own text said what it should be.' },
  { title: 'Numbers must be sourced', text: 'Reviews and reports may only cite numbers found in the results, the data card or counts the agent ran. This catches invented numbers, but not a real number attributed to the wrong analysis.' },
  { title: 'Meaning stated in code', text: 'Engineering labels the negative control PASSED or FAILED; a reviewer once read a passing control as a failure.' },
  { title: 'Bounded work', text: 'Each station has a budget of model requests, tool calls, 1,500-token responses and 4-minute requests, so a confused model fails fast with its output logged.' },
  { title: 'Approvals in code', text: 'Gates block until a person decides; reports are drafts until published; every decision is logged. The model server needs a key, and bridge actions need login, permission and a CSRF token.' },
]

export default {
  name: 'briefing',
  data() {
    return {
      sections: [
        { id: 'crew', label: 'The crew' },
        { id: 'mission', label: 'A mission' },
        { id: 'analysis', label: 'The analysis' },
        { id: 'guardrails', label: 'Guardrails' },
      ],
      current: 'crew', crew: CREW, steps: STEPS, method: METHOD, readings: READINGS,
      guardrails: GUARDRAILS, snapshot: null
    }
  },
  methods: {
    go(id) {
      this.current = id
      const el = this.$refs.body.querySelector(`#${id}`)
      if (el) this.$refs.body.scrollTo({ top: el.offsetTop - this.$refs.body.offsetTop, behavior: 'smooth' })
    }
  },
  async mounted() {
    try { this.snapshot = (await MissionService.crewStatus()).snapshot } catch (err) { /* offline */ }
  }
}
</script>

<style scoped>
.briefing {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  padding-bottom: 8px;
  box-sizing: border-box;
}
.briefing-nav { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.briefing-nav button {
  font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 20px;
  border: 0; border-radius: 16px; padding: 3px 18px; cursor: pointer;
  background: var(--lcars-color-a3); color: #000;
}
.briefing-nav button:hover { background: var(--lcars-color-a2); }
.briefing-nav button.active { background: var(--lcars-color-a5); }

.briefing-body {
  overflow-y: auto;
  min-height: 0;
  padding-right: 10px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif;
  text-transform: none;
  font-size: 16px;
  line-height: 1.55;
  color: #e4e4e4;
}
section { margin-bottom: 34px; max-width: 1100px; }
h2 {
  font-family: 'lcars', sans-serif; text-transform: uppercase; font-weight: normal;
  font-size: 34px; color: var(--lcars-color-a1); margin: 0 0 8px;
}
h3 {
  font-family: 'lcars', sans-serif; text-transform: uppercase; font-weight: normal;
  font-size: 22px; color: var(--lcars-color-a8); margin: 18px 0 4px;
}
p { margin: 0 0 10px; max-width: 75ch; }
b { color: #fff; }
a { color: var(--lcars-color-b6); }
code { font-family: ui-monospace, Menlo, monospace; font-size: 0.9em; color: var(--lcars-color-b1); }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { border-left: 12px solid; border-radius: 12px 0 0 12px; background: #151515; padding: 8px 12px; }
.card-title { font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 24px; }
.card-role { color: #999; font-size: 13px; margin-bottom: 4px; }
.card p { font-size: 15px; }
dl { margin: 0; font-size: 14px; display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; }
dt { color: var(--lcars-color-a8); font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 16px; }
dd { margin: 0; color: #ccc; }

.steps { list-style: none; padding: 0; margin: 0 0 10px; max-width: 80ch; }
.steps li { border-left: 4px solid var(--lcars-color-a3); padding: 2px 0 2px 12px; margin-bottom: 6px; }
.steps li.gate { border-left-color: var(--lcars-color-b3); }
.step-head { font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 20px; color: var(--lcars-color-b1); }
.steps li.gate .step-head { color: var(--lcars-color-b3); }
.step-n { display: inline-block; min-width: 26px; color: var(--lcars-color-a5); }
.steps p { margin: 0; font-size: 15px; }
.note { color: #bbb; font-size: 15px; }

.method { padding-left: 22px; max-width: 80ch; }
.method li { margin-bottom: 6px; }
table { border-collapse: collapse; max-width: 90ch; font-size: 15px; margin-bottom: 10px; }
th { font-family: 'lcars', sans-serif; text-transform: uppercase; font-weight: normal; font-size: 18px;
  color: var(--lcars-color-a8); text-align: left; padding: 4px 10px; border-bottom: 2px solid #333; }
td { padding: 6px 10px; border-bottom: 1px solid #222; vertical-align: top; }
td:first-child { color: #fff; width: 45%; }
.guards { padding-left: 20px; max-width: 85ch; }
.guards li { margin-bottom: 7px; }
</style>

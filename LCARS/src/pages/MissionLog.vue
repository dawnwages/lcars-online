<template>
  <div class="mission-log">
    <!-- Missions -->
    <nav class="missions">
      <div class="lcars-heading">Missions</div>
      <LaunchPanel :session="session" :crew="crew" @launched="onLaunched" @changed="loadCrew" />
      <div v-if="loadError" class="load-error">{{ loadError }}</div>
      <div
        v-for="m in missions" :key="m.id"
        class="mission-row" :class="[m.status, { selected: m.id === selectedId }]"
        @click="select(m.id)"
      >
        <span class="mission-id">{{ String(m.id).padStart(3, '0') }}</span>
        <span class="mission-kind">{{ kindLabel(m.kind) }}</span>
        <span class="mission-status">{{ m.status_display }}</span>
        <span class="mission-gates" v-if="m.pending_gates">◆ {{ m.pending_gates }}</span>
      </div>
    </nav>

    <!-- Selected mission -->
    <section class="detail" v-if="detail">
      <header class="detail-header">
        <div class="lcars-heading">Mission {{ detail.id }} · Stardate {{ detail.stardate }}</div>
        <div class="question">{{ detail.question }}</div>
        <div class="meta">
          <span><b>Status</b> {{ detail.status_display }}</span>
          <span v-if="detail.model_name"><b>Model</b> {{ detail.model_name }}</span>
          <span v-if="detail.snapshot"><b>Data</b> {{ detail.snapshot.rows?.toLocaleString() }} planets, {{ new Date(detail.snapshot.data_fetched_at).toLocaleDateString() }} ({{ detail.snapshot.sha256.slice(0, 8) }})</span>
          <span v-else-if="detail.snapshot_sha256"><b>Data</b> {{ detail.snapshot_sha256.slice(0, 8) }}</span>
          <span><b>Seed</b> {{ detail.seed }}</span>
          <span v-if="detail.code_version"><b>Commit</b> {{ detail.code_version }}</span>
          <span v-if="detail.duration_s"><b>Duration</b> {{ formatDuration(detail.duration_s) }}</span>
        </div>
        <div class="verdict" v-if="detail.verdict">{{ detail.verdict }}</div>
        <div class="waiting" v-if="pendingGates.length">
          ◆ Awaiting captain: {{ pendingGates.map(g => g.label).join(', ') }}
        </div>
      </header>

      <div class="gates" v-if="detail.gates.length">
        <!-- What needs a decision comes first; decided gates collapse to one line -->
        <GatePanel
          v-for="g in pendingGates" :key="g.id + g.status"
          :gate="g" :session="session" @decided="refreshNow"
        />
        <div class="decided-gate" v-for="g in decidedGates" :key="g.id" :class="g.status">
          <span class="decided-label">{{ g.label }}</span>
          <span class="decided-status">{{ g.status }}</span>
          <span class="decided-by">{{ g.decided_by || 'unattended' }} via {{ g.decided_via }}<span v-if="g.note">: “{{ g.note }}”</span></span>
        </div>
      </div>

      <div class="events" ref="events">
        <div v-for="e in events" :key="e.seq" class="event" :class="[e.station, e.kind]">
          <span class="seq">{{ String(e.seq).padStart(3, '0') }}</span>
          <span class="station">{{ e.station_display }}</span>
          <span class="body">
            <span class="kind">{{ kindText(e.kind) }}</span>
            <span class="title">{{ e.title }}</span>
            <span class="timing" v-if="e.duration_ms">{{ (e.duration_ms / 1000).toFixed(1) }} s</span>
            <div class="rationale" v-if="e.rationale">{{ e.rationale }}</div>
            <ul class="alternatives" v-if="e.alternatives && e.alternatives.length">
              <li v-for="(a, i) in e.alternatives" :key="i">Rejected: {{ a.option }}, {{ a.why_not }}</li>
            </ul>
          </span>
        </div>
        <div v-if="isLive" class="live">● Receiving telemetry</div>
      </div>
    </section>
    <section class="detail empty" v-else>
      <div class="lcars-heading">No mission selected</div>
      <p>Launch one with <code>manage.py run_mission</code>; every run appears here.</p>
    </section>
  </div>
</template>

<script>
import MissionService from '../services/MissionService'
import GatePanel from '../common/GatePanel.vue'
import LaunchPanel from '../common/LaunchPanel.vue'
import { sounds } from '../assets/sounds'

const LIVE = ['running', 'awaiting_approval', 'planned']
const GATE_ORDER = ['data_card', 'plan', 'plan_revision', 'publish']

export default {
  name: 'mission-log',
  components: { GatePanel, LaunchPanel },
  emits: ['pending-gates'],
  data() {
    return {
      missions: [], selectedId: null, detail: null, events: [], lastSeq: 0,
      session: null, crew: null, loadError: '', timer: null
    }
  },
  computed: {
    isLive() { return this.detail && LIVE.includes(this.detail.status) },
    orderedGates() {
      return [...this.detail.gates].sort((a, b) => GATE_ORDER.indexOf(a.name) - GATE_ORDER.indexOf(b.name))
    },
    pendingGates() { return this.orderedGates.filter(g => g.status === 'pending') },
    decidedGates() { return this.orderedGates.filter(g => g.status !== 'pending') }
  },
  methods: {
    kindLabel(kind) {
      return { analysis: 'Analysis', negative_control: 'Control', eval: 'Eval', red_team: 'Red team' }[kind] || kind
    },
    kindText(kind) {
      return {
        decision: 'Decision', tool_call: 'Tool ▸', tool_result: 'Tool ◂', model_output: 'Model',
        gate: 'Gate', note: 'Note', error: 'Error'
      }[kind] || kind
    },
    formatDuration(s) { return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s` },
    async loadList() {
      try {
        this.missions = await MissionService.list()
        this.loadError = ''
        this.$emit('pending-gates', this.missions.reduce((n, m) => n + m.pending_gates, 0))
        if (!this.selectedId && this.missions.length) this.select(this.missions[0].id)
      } catch (err) {
        this.loadError = 'Cannot reach the mission log. Is Django running on port 8000?'
      }
    },
    async select(id) {
      this.selectedId = id
      this.events = []
      this.lastSeq = 0
      this.detail = null
      await this.loadDetail()
      sounds.panelBeep03?.play()
    },
    async loadDetail() {
      if (!this.selectedId) return
      const id = this.selectedId
      const data = await MissionService.detail(id, this.lastSeq)
      if (id !== this.selectedId) return // selection changed while loading
      const hadPending = this.detail?.gates.some(g => g.status === 'pending')
      this.detail = data
      if (data.events.length) {
        this.events.push(...data.events)
        this.lastSeq = data.events[data.events.length - 1].seq
        this.$nextTick(() => {
          const el = this.$refs.events
          if (el) el.scrollTop = el.scrollHeight
        })
      }
      if (!hadPending && data.gates.some(g => g.status === 'pending')) sounds.panelBeep14?.play()
    },
    async refreshNow() {
      await Promise.all([this.loadDetail(), this.loadList()])
    },
    async loadCrew() {
      try {
        this.crew = await MissionService.crewStatus()
      } catch (err) {
        this.crew = null
      }
    },
    async loadSession() {
      try {
        this.session = await MissionService.session()
      } catch (err) {
        this.session = null
      }
    },
    async onLaunched(id) {
      await this.loadList()
      await this.select(id)
    },
    async tick() {
      await Promise.all([this.loadList(), this.loadCrew()])
      if (this.isLive) await this.loadDetail()
    }
  },
  async mounted() {
    await this.loadSession()
    await Promise.all([this.loadList(), this.loadCrew()])
    this.timer = setInterval(this.tick, 2000)
    // Logging in happens in another tab; pick it up when the captain returns
    window.addEventListener('focus', this.loadSession)
  },
  beforeUnmount() {
    clearInterval(this.timer)
    window.removeEventListener('focus', this.loadSession)
  }
}
</script>

<style scoped>
.mission-log {
  display: grid;
  grid-template-columns: minmax(220px, 280px) 1fr;
  grid-template-rows: minmax(0, 1fr);
  gap: 16px;
  height: 100%;
  min-height: 0;
  color: #ddd;
}
.lcars-heading {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  color: var(--lcars-color-a1);
  font-size: 30px;
  margin-bottom: 6px;
}
.missions { overflow-y: auto; min-height: 0; padding-right: 6px; }
.mission-row {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  gap: 6px;
  align-items: center;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 20px;
  padding: 3px 12px 3px 8px;
  margin-bottom: 4px;
  border-radius: 0 16px 16px 0;
  background: var(--lcars-color-a3);
  color: #000;
  cursor: pointer;
}
.mission-row:hover { background: var(--lcars-color-a2); }
.mission-row.selected { background: var(--lcars-color-a5); }
.mission-row.complete { background: var(--lcars-color-b6); }
.mission-row.complete.selected { background: var(--lcars-color-b1); }
.mission-row.failed, .mission-row.rejected { background: var(--lcars-color-a6); }
.mission-row.awaiting_approval { background: var(--lcars-color-b3); animation: blink 1.2s infinite; }
.mission-status { grid-column: 2; font-size: 16px; }
.mission-kind { grid-column: 2; grid-row: 1; }
.mission-gates { grid-column: 3; grid-row: 1 / span 2; }
@keyframes blink { 50% { opacity: 0.6; } }
.load-error { color: #ff7777; font-family: system-ui, sans-serif; text-transform: none; }

.detail { display: flex; flex-direction: column; min-height: 0; overflow-y: auto; }
.detail.empty p { font-family: system-ui, sans-serif; text-transform: none; }
.question { font-size: 20px; color: var(--lcars-color-b1); font-family: system-ui, sans-serif; margin-bottom: 6px; }
.meta { display: flex; flex-wrap: wrap; gap: 14px; font-family: system-ui, sans-serif; font-size: 14px; color: #aaa; }
.meta b { font-family: 'lcars', sans-serif; text-transform: uppercase; color: var(--lcars-color-a8); font-weight: normal; font-size: 17px; margin-right: 4px; }
.verdict { margin: 6px 0; color: var(--lcars-color-b6); font-family: system-ui, sans-serif; }
.gates { margin: 10px 0; }
.waiting {
  margin-top: 6px;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 22px;
  color: var(--lcars-color-b3);
  animation: blink 1.2s infinite;
}
.decided-gate {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 10px;
  align-items: baseline;
  border-left: 10px solid var(--lcars-color-b6);
  border-radius: 10px 0 0 10px;
  padding: 2px 10px;
  margin-bottom: 4px;
  background: #151515;
}
.decided-gate.rejected { border-left-color: #cc4444; }
.decided-label, .decided-status {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 18px;
  color: var(--lcars-color-b6);
}
.decided-gate.rejected .decided-label, .decided-gate.rejected .decided-status { color: #ff7777; }
.decided-by { font-family: system-ui, sans-serif; font-size: 13px; color: #999; }

.events {
  flex: 1;
  min-height: 160px;
  overflow-y: auto;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  text-transform: none;
  border-top: 4px solid var(--lcars-color-a3);
  padding-top: 6px;
}
.event { display: grid; grid-template-columns: 36px 120px 1fr; gap: 8px; padding: 3px 0; border-bottom: 1px solid #1d1d1d; }
.seq { color: #666; }
.station {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 17px;
  border-radius: 10px;
  padding: 0 8px;
  color: #000;
  background: var(--lcars-color-a8);
  height: fit-content;
  text-align: right;
}
.event.ops .station { background: var(--lcars-color-a1); }
.event.science .station { background: var(--lcars-color-b6); }
.event.engineering .station { background: var(--lcars-color-b2); }
.event.tactical .station { background: var(--lcars-color-a6); }
.event.log .station { background: var(--lcars-color-b5); }
.event.captain .station { background: var(--lcars-color-b1); }
.kind { color: var(--lcars-color-a5); margin-right: 6px; }
.event.decision .title { color: var(--lcars-color-b1); }
.event.error .title, .event.error .kind { color: #ff7777; }
.timing { color: #666; margin-left: 8px; }
.rationale { color: #aaa; white-space: pre-wrap; margin-top: 2px; }
.alternatives { color: #888; margin: 2px 0 0 18px; padding: 0; }
.live { color: var(--lcars-color-b3); padding: 6px 0; animation: blink 1.2s infinite; }
</style>

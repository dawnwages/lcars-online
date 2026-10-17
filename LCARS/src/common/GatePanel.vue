<template>
  <div class="gate" :class="gate.status">
    <div class="gate-header">
      <span class="gate-label">{{ gate.label }}</span>
      <span class="gate-status">{{ statusText }}</span>
    </div>

    <!-- What is being approved -->
    <div class="gate-summary" v-if="summary">
      <template v-if="summary.hypothesis">
        <p><span class="key">Hypothesis</span> {{ summary.hypothesis }}</p>
        <p v-if="summary.null_hypothesis"><span class="key">Null</span> {{ summary.null_hypothesis }}</p>
        <div class="key">Population</div>
        <ol class="filters">
          <li v-for="(f, i) in summary.population" :key="i">
            <code>{{ f.column }} {{ opSymbol(f.op) }} {{ f.value ?? '' }}</code>
            <span class="reason">{{ f.reason }}</span>
          </li>
        </ol>
        <p>
          <span class="key">Bandwidth</span> {{ summary.bandwidth_dex }} dex
          <span class="key">Alpha</span> {{ summary.significance_level }}
        </p>
        <p><span class="key">Falsified if</span> {{ summary.falsification }}</p>
        <div v-if="summary.alternatives_considered?.length">
          <div class="key">Alternatives rejected</div>
          <ul><li v-for="(a, i) in summary.alternatives_considered" :key="i">{{ a.option }}: {{ a.why_not }}</li></ul>
        </div>
      </template>
      <template v-else-if="summary.brief">
        <p>{{ summary.brief.summary }}</p>
        <div class="key">Hazards</div>
        <ul>
          <li v-for="(h, i) in summary.brief.hazards" :key="i">
            <b>{{ h.name }}</b>: {{ h.evidence }}. <span class="reason">{{ h.implication }}</span>
          </li>
        </ul>
      </template>
      <template v-else-if="summary.title">
        <p><span class="key">Report</span> {{ summary.title }}</p>
      </template>
    </div>

    <!-- Decision -->
    <div class="gate-actions" v-if="gate.status === 'pending'">
      <template v-if="session && session.can_decide">
        <input v-model="note" class="note" placeholder="Note for the log (optional)" />
        <button class="approve" :disabled="busy" @click="decide('approved')">Make it so</button>
        <button class="reject" :disabled="busy" @click="decide('rejected')">Belay that</button>
      </template>
      <a v-else class="authorize" :href="loginUrl" target="_blank" rel="noopener">
        Authorization required: log in to the admin, then return
      </a>
      <div class="error" v-if="error">{{ error }}</div>
    </div>
    <div class="gate-decided" v-else>
      {{ gate.decided_by || 'unattended' }} via {{ gate.decided_via }}
      <span v-if="gate.note">: “{{ gate.note }}”</span>
    </div>
  </div>
</template>

<script>
import MissionService from '../services/MissionService'
import { sounds } from '../assets/sounds'

const OPS = { eq: '=', ne: '≠', lt: '<', le: '≤', gt: '>', ge: '≥', notna: 'is present' }

export default {
  name: 'gate-panel',
  props: { gate: Object, session: Object },
  emits: ['decided'],
  data() {
    return { note: '', busy: false, error: '' }
  },
  computed: {
    summary() { return this.gate.summary },
    statusText() {
      return { pending: 'Awaiting captain', approved: 'Approved', rejected: 'Rejected' }[this.gate.status]
    },
    loginUrl() { return MissionService.loginUrl() }
  },
  methods: {
    opSymbol(op) { return OPS[op] || op },
    async decide(decision) {
      this.busy = true
      this.error = ''
      try {
        const gate = await MissionService.decide(this.gate.id, decision, this.note)
        sounds.panelBeep08?.play()
        this.$emit('decided', gate)
      } catch (err) {
        sounds.denyBeep1?.play()
        this.error = err.response?.data?.error || 'Decision failed'
      } finally {
        this.busy = false
      }
    }
  }
}
</script>

<style scoped>
.gate {
  border-left: 18px solid var(--lcars-color-a5);
  border-radius: 18px 0 0 18px;
  padding: 8px 14px;
  margin-bottom: 10px;
  background: #151515;
  font-family: system-ui, sans-serif;
  text-transform: none;
  font-size: 15px;
  color: #ddd;
}
.gate.approved { border-left-color: var(--lcars-color-b6); }
.gate.rejected { border-left-color: #cc4444; }
.gate-header {
  display: flex;
  justify-content: space-between;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 24px;
  color: var(--lcars-color-a5);
}
.gate.approved .gate-header { color: var(--lcars-color-b6); }
.gate.rejected .gate-header { color: #ff7777; }
.key {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  color: var(--lcars-color-a8);
  font-size: 18px;
  margin-right: 6px;
}
.filters { margin: 4px 0 8px; padding-left: 24px; }
code { color: var(--lcars-color-b1); }
.reason { color: #999; margin-left: 6px; }
.gate-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.note { flex: 1; min-width: 200px; background: #000; color: #eee; border: 1px solid #444; padding: 6px; }
button {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 22px;
  border: 0;
  border-radius: 18px;
  padding: 4px 22px;
  cursor: pointer;
}
button:disabled { opacity: 0.5; cursor: wait; }
.approve { background: var(--lcars-color-a5); }
.approve:hover { background: var(--lcars-color-b1); }
.reject { background: var(--lcars-color-a6); }
.reject:hover { background: #ff7777; }
.authorize { color: var(--lcars-color-a5); font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 20px; }
.error { color: #ff7777; width: 100%; }
.gate-decided { color: #999; margin-top: 4px; }
</style>

<template>
  <div class="launch">
    <button class="toggle" @click="open = !open">{{ open ? '▾' : '▸' }} New mission</button>

    <div v-if="open" class="form">
      <template v-if="session && session.can_launch">
        <label>Question
          <textarea v-model="question" rows="3" maxlength="500"></textarea>
        </label>

        <label>Model
          <select v-model="model">
            <option v-for="m in models" :key="m.name" :value="m.name">
              {{ m.label }}{{ m.size_gb ? ` · ${m.size_gb} GB` : '' }}
            </option>
          </select>
        </label>

        <div class="row">
          <label>Type
            <select v-model="kind">
              <option value="analysis">Analysis</option>
              <option value="negative_control">Negative control</option>
            </select>
          </label>
          <label>Seed
            <input type="number" v-model.number="seed" min="0" step="1" />
          </label>
        </div>

        <div class="data">
          <div class="data-title">NASA Exoplanet Archive</div>
          <template v-if="snapshot">
            <div>{{ snapshot.rows?.toLocaleString() }} planets · data from {{ formatTime(snapshot.data_fetched_at) }}</div>
            <div v-if="!snapshot.baseline" class="changes">
              +{{ snapshot.added }} new · {{ snapshot.revised }} revised · −{{ snapshot.removed }} removed
            </div>
            <div class="muted">Last checked {{ formatTime(snapshot.last_checked_at) }}</div>
          </template>
          <div v-if="crew?.last_fetch?.status === 'failed'" class="error">
            Last fetch failed: {{ crew.last_fetch.error }}
          </div>
          <button class="small" :disabled="busy || crew?.fetching" @click="fetchData">
            {{ crew?.fetching ? 'Fetching…' : 'Fetch latest data' }}
          </button>
        </div>

        <div class="server">
          <span class="dot" :class="serverState"></span>
          <span>{{ serverText }}</span>
          <button v-if="server.process_running" class="small" :disabled="busy || activeMission"
                  @click="stopModel">Stop model</button>
        </div>

        <button class="engage" :disabled="busy || !!activeMission || !question.trim()" @click="engage">
          {{ activeMission ? `Mission ${activeMission} under way` : 'Engage' }}
        </button>
        <div class="hint" v-if="model !== 'test' && !activeMission">
          Loading a model takes about 15 s and uses most of this Mac's free memory. Any other model is stopped first.
        </div>
      </template>
      <a v-else class="authorize" :href="loginUrl" target="_blank" rel="noopener">
        Authorization required: log in to the admin to launch missions
      </a>
      <div class="error" v-if="error">{{ error }}</div>
    </div>
  </div>
</template>

<script>
import MissionService from '../services/MissionService'
import { sounds } from '../assets/sounds'

export default {
  name: 'launch-panel',
  props: { session: Object, crew: Object },
  emits: ['launched', 'changed'],
  data() {
    return {
      open: false,
      question: 'Is there a gap in the sizes of small planets?',
      kind: 'analysis',
      seed: 0,
      model: '',
      busy: false,
      error: ''
    }
  },
  computed: {
    models() { return this.crew?.models || [] },
    snapshot() { return this.crew?.snapshot },
    server() { return this.crew?.model_server || {} },
    activeMission() { return this.crew?.active_mission },
    loginUrl() { return MissionService.loginUrl() },
    serverState() {
      if (this.server.loaded) return 'online'
      if (this.server.starting) return 'starting'
      return 'offline'
    },
    serverText() {
      if (this.server.loaded) return `Model online: ${this.server.loaded}`
      if (this.server.starting) return 'Model loading…'
      return 'No model loaded'
    }
  },
  watch: {
    models: {
      immediate: true,
      handler(models) {
        if (!this.model && models.length) {
          // Default to the loaded model, else the first real model, else the test model
          const real = models.find(m => m.name !== 'test')
          this.model = this.server.loaded || (real ? real.name : models[0].name)
        }
      }
    }
  },
  methods: {
    async run(fn) {
      this.busy = true
      this.error = ''
      try {
        return await fn()
      } catch (err) {
        sounds.denyBeep1?.play()
        this.error = err.response?.data?.error || 'Request failed'
      } finally {
        this.busy = false
        this.$emit('changed')
      }
    },
    async engage() {
      const mission = await this.run(() => MissionService.launch({
        question: this.question, model: this.model, kind: this.kind, seed: this.seed
      }))
      if (mission) {
        sounds.panelBeep13?.play()
        this.open = false
        this.$emit('launched', mission.id)
      }
    },
    formatTime(iso) {
      return iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''
    },
    async fetchData() {
      await this.run(() => MissionService.fetchData())
    },
    async stopModel() {
      await this.run(() => MissionService.stopModel())
    }
  }
}
</script>

<style scoped>
.launch { margin-bottom: 10px; }
.toggle, .engage, .small {
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  border: 0;
  cursor: pointer;
}
.toggle {
  width: 100%;
  text-align: left;
  font-size: 22px;
  padding: 4px 12px;
  border-radius: 0 16px 16px 0;
  background: var(--lcars-color-a5);
}
.toggle:hover { background: var(--lcars-color-b1); }
.form {
  margin-top: 6px;
  padding: 8px 10px;
  border-left: 10px solid var(--lcars-color-a5);
  border-radius: 10px 0 0 10px;
  background: #151515;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-family: system-ui, sans-serif;
  text-transform: none;
  font-size: 14px;
  color: #ddd;
}
label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 16px;
  color: var(--lcars-color-a8);
}
textarea, select, input {
  font-family: system-ui, sans-serif;
  text-transform: none;
  font-size: 14px;
  background: #000;
  color: #eee;
  border: 1px solid #444;
  padding: 4px 6px;
}
.row { display: grid; grid-template-columns: 1fr 80px; gap: 8px; }
.data {
  border-top: 1px solid #333;
  border-bottom: 1px solid #333;
  padding: 6px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}
.data-title { font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 16px; color: var(--lcars-color-a8); }
.changes { color: var(--lcars-color-b6); }
.muted { color: #888; font-size: 12px; }
.server { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #555; }
.dot.online { background: var(--lcars-color-b6); }
.dot.starting { background: var(--lcars-color-b3); animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0.4; } }
.small { font-size: 15px; padding: 2px 10px; border-radius: 10px; background: var(--lcars-color-a6); margin-top: 4px; }
.engage {
  font-size: 26px;
  padding: 4px 0;
  border-radius: 18px;
  background: var(--lcars-color-a5);
}
.engage:hover:not(:disabled) { background: var(--lcars-color-b1); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.hint { color: #888; font-size: 12px; }
.authorize { color: var(--lcars-color-a5); font-family: 'lcars', sans-serif; text-transform: uppercase; font-size: 18px; }
.error { color: #ff7777; }
</style>

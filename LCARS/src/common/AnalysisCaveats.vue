<template>
  <aside class="caveats" :class="{ open }">
    <button class="caveats-toggle" @click="open = !open" :aria-expanded="open">
      {{ open ? '▾' : '▸' }} Disclaimer: what an expert would critique
    </button>
    <div v-if="open" class="caveats-body">
      <p class="lede">
        This is a demonstration of agent guardrails, not a new scientific result. Read every
        mission with these limits in mind:
      </p>
      <ul>
        <li v-for="c in caveats" :key="c.title"><b>{{ c.title }}.</b> {{ c.text }}</li>
      </ul>
    </div>
  </aside>
</template>

<script>
const CAVEATS = [
  {
    title: 'No completeness correction',
    text: 'The crew counts the planets in the catalog, not the true population. Published work ' +
      '(Fulton et al. 2017) corrects for which planets a survey could detect; this analysis does not.',
  },
  {
    title: 'Selection effects',
    text: 'Each discovery method finds different planets (transit favors short orbits; radial ' +
      'velocity, long ones). Transit dominates the sample, so a "valley" can partly reflect what ' +
      'surveys can detect.',
  },
  {
    title: 'A composite catalog',
    text: 'Values come from many studies and pipelines, and about half the masses are inferred from ' +
      'radius rather than measured. This method uses radius only, but the mix still adds noise.',
  },
  {
    title: 'A conservative test, and a power trade-off',
    text: "Silverman's test can miss shallow valleys. Stricter precision cuts sharpen the valley but " +
      'shrink the sample, so "not significant" at a strict cut can mean too few planets, not no valley.',
  },
  {
    title: 'A known answer',
    text: 'The radius valley is a published result. Rediscovering it tests the process; it is not ' +
      'a discovery.',
  },
  {
    title: 'A small local model',
    text: 'Every number is computed by code and checked, but a 9-billion-parameter model can still ' +
      'misread or misattribute results in its prose. Read the event log, not just the report.',
  },
]

export default {
  name: 'analysis-caveats',
  data() {
    let open = true
    try { open = localStorage.getItem('lcars-caveats-open') !== 'false' } catch (err) { /* private mode */ }
    return { open, caveats: CAVEATS }
  },
  watch: {
    open(value) {
      try { localStorage.setItem('lcars-caveats-open', String(value)) } catch (err) { /* ignore */ }
    }
  }
}
</script>

<style scoped>
.caveats {
  margin: 8px 0;
  border-left: 10px solid var(--lcars-color-b3);
  border-radius: 10px 0 0 10px;
  background: #151515;
  padding: 4px 10px;
  font-family: system-ui, sans-serif;
  text-transform: none;
  color: #ccc;
  font-size: 13px;
}
.caveats-toggle {
  background: none;
  border: 0;
  padding: 2px 0;
  cursor: pointer;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 18px;
  color: var(--lcars-color-b3);
  text-align: left;
}
.lede { margin: 2px 0 4px; color: #aaa; }
ul { margin: 0 0 4px; padding-left: 18px; }
li { margin: 3px 0; line-height: 1.35; }
b { color: var(--lcars-color-b1); font-weight: 600; }
</style>

<template>
  <aside class="caveats" :class="{ open }">
    <button class="caveats-toggle" @click="open = !open" :aria-expanded="open">
      {{ open ? '▾' : '▴' }} Disclaimer: what an expert would critique
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
    // An accordion: collapsed by default, its title always visible
    return { open: false, caveats: CAVEATS }
  }
}
</script>

<style scoped>
.caveats {
  position: fixed;
  left: 20px;
  right: 20px;
  bottom: 0;
  z-index: 20;
  background: #151515;
  border-top: 6px solid var(--lcars-color-b3);
  border-radius: 18px 18px 0 0;
  font-family: system-ui, sans-serif;
  text-transform: none;
  color: #ccc;
  font-size: 14px;
  box-shadow: 0 -6px 18px rgba(0, 0, 0, 0.6);
}
.caveats-toggle {
  width: 100%;
  background: none;
  border: 0;
  padding: 6px 18px;
  cursor: pointer;
  font-family: 'lcars', sans-serif;
  text-transform: uppercase;
  font-size: 20px;
  color: var(--lcars-color-b3);
  text-align: left;
}
.caveats-toggle:hover { color: var(--lcars-color-b1); }
.caveats-body {
  max-height: 45vh;
  overflow-y: auto;
  padding: 0 18px 12px;
}
.lede { margin: 2px 0 6px; color: #aaa; }
ul { margin: 0; padding-left: 18px; columns: 2 360px; column-gap: 28px; }
li { margin: 0 0 8px; line-height: 1.4; break-inside: avoid; }
b { color: var(--lcars-color-b1); font-weight: 600; }
</style>

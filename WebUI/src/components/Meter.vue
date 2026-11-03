<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: Number, default: null },
  max: { type: Number, default: 100 },
  level: { type: String, default: 'accent' },
  marker: { type: Number, default: null },
  markerLabel: { type: String, default: '' },
})

const pct = computed(() => (props.value === null ? 0 : Math.max(0, Math.min(100, (props.value / props.max) * 100))))
const markerPct = computed(() => (props.marker === null ? null : (props.marker / props.max) * 100))
</script>

<template>
  <div class="meter" :class="level" role="meter" :aria-valuenow="value" aria-valuemin="0" :aria-valuemax="max">
    <div class="fill" :style="{ width: pct + '%' }"></div>
    <div v-if="markerPct !== null" class="marker" :style="{ left: markerPct + '%' }" :title="markerLabel"></div>
  </div>
</template>

<style scoped>
.meter {
  --c: var(--accent);
  position: relative;
  height: 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--c) 18%, var(--surface-2));
}
.fill {
  height: 100%;
  border-radius: 999px;
  background: var(--c);
  transition: width 0.4s ease;
}
.marker {
  position: absolute;
  top: -3px;
  bottom: -3px;
  width: 2px;
  margin-left: -1px;
  background: var(--text);
  border-radius: 1px;
  box-shadow: 0 0 0 2px var(--surface);
}
.good { --c: var(--good); }
.warning { --c: var(--warning); }
.serious { --c: var(--serious); }
.critical { --c: var(--critical); }
.neutral { --c: var(--neutral); }
</style>

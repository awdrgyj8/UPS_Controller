<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  level: { type: String, default: 'neutral' },
  label: { type: String, required: true },
  size: { type: String, default: 'md' },
})

const ICONS = { good: 'check', warning: 'alert', serious: 'alert', critical: 'x', neutral: 'minus', info: 'info' }
const icon = computed(() => ICONS[props.level] || 'minus')
</script>

<template>
  <span class="pill" :class="[level, size]">
    <span class="dot"><Icon :name="icon" :size="size === 'lg' ? 12 : 10" :stroke="3" /></span>
    {{ label }}
  </span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px 2px 3px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: color-mix(in srgb, var(--c) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--c) 35%, transparent);
  color: var(--text);
  white-space: nowrap;
  --c: var(--neutral);
}
.pill.lg {
  font-size: 14px;
  padding: 4px 12px 4px 4px;
}
.dot {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--c);
  color: #fff;
}
.lg .dot {
  width: 20px;
  height: 20px;
}
.good { --c: var(--good); }
.warning { --c: var(--warning); }
.warning .dot { color: #0b0b0b; }
.serious { --c: var(--serious); }
.critical { --c: var(--critical); }
.info { --c: var(--info); }
.neutral { --c: var(--neutral); }
</style>

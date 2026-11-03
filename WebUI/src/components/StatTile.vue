<script setup>
import Icon from './Icon.vue'

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '-' },
  sub: { type: String, default: '' },
  icon: { type: String, default: '' },
  level: { type: String, default: '' },
})
</script>

<template>
  <div class="tile card" :class="level">
    <div class="label">
      <Icon v-if="icon" :name="icon" :size="14" />
      {{ label }}
    </div>
    <div class="value">{{ value }}</div>
    <slot />
    <div v-if="sub" class="sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.tile {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  overflow: hidden;
}
.tile::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--c, transparent);
}
.tile.good { --c: var(--good); }
.tile.warning { --c: var(--warning); }
.tile.serious { --c: var(--serious); }
.tile.critical { --c: var(--critical); }
.label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
}
.value {
  font-size: 24px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.01em;
}
.sub {
  font-size: 12px;
  color: var(--text-2);
}
</style>

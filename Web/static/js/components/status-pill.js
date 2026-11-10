// 狀態籤：level 用後端的 good / neutral / warning / serious / critical / info
export default {
  name: 'StatusPill',
  props: {
    level: { type: String, default: 'neutral' },
    label: { type: String, required: true },
    size: { type: String, default: 'md' },
  },
  template: /* html */ `<span class="pill" :class="[level, size]"><span class="dot"></span>{{ label }}</span>`,
}

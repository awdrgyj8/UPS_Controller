import { clock } from '../format.js'
import { SOURCES, cleanMessage } from '../store.js'

// 事件清單：時間、來源、訊息
export default {
  name: 'EventList',
  props: {
    events: { type: Array, default: () => [] },
  },
  setup() {
    return { clock, SOURCES, cleanMessage }
  },
  template: /* html */ `
    <ol class="ev">
      <li v-for="event in events" :key="event.id" :class="event.level">
        <time>{{ clock(event.ts) }}</time>
        <span class="who">{{ SOURCES[event.source] || event.source }}</span>
        <span class="what">{{ cleanMessage(event.message) }}</span>
      </li>
      <li v-if="!events.length" class="empty" style="display: block">還沒有事件</li>
    </ol>`,
}

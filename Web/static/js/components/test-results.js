import { computed } from 'vue'
import { TEST_STATUS, cleanMessage } from '../store.js'

// 自檢 / 演練的結果：依群組列出每一項檢查
export default {
  name: 'TestResults',
  props: {
    results: { type: Array, default: () => [] },
  },
  setup(props) {
    const groups = computed(() => {
      const map = new Map()
      for (const result of props.results) {
        if (!map.has(result.group)) map.set(result.group, [])
        map.get(result.group).push(result)
      }
      return [...map.entries()].map(([name, items]) => ({ name, items }))
    })
    const statusOf = (item) => TEST_STATUS[item.status] || TEST_STATUS.pending
    return { groups, statusOf, cleanMessage }
  },
  template: /* html */ `
    <div class="results">
      <section v-for="group in groups" :key="group.name">
        <h3>{{ group.name }}</h3>
        <ul>
          <li v-for="item in group.items" :key="item.id" :class="statusOf(item).level" :data-test-id="item.id">
            <Icon v-if="item.status === 'running'" name="loader" :size="14" :stroke="3" class="lead" />
            <span v-else class="dot lead"></span>
            <span class="name">{{ item.label }}<span v-if="item.dry_run" class="dry">乾跑</span></span>
            <span class="state">{{ statusOf(item).label }}</span>
            <span v-if="item.detail" class="detail">{{ cleanMessage(item.detail) }}</span>
          </li>
        </ul>
      </section>
    </div>`,
}

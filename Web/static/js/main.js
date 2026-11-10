import { createApp } from 'vue'
import App from './app.js'
import Icon from './components/icon.js'
import StatusPill from './components/status-pill.js'
import LineChart from './components/line-chart.js'
import EventList from './components/event-list.js'
import FlowStepper from './components/flow-stepper.js'

// 各頁都會用到的小元件直接全域註冊，template 裡可以直接寫 <Icon />、<StatusPill /> ...
createApp(App)
  .component('Icon', Icon)
  .component('StatusPill', StatusPill)
  .component('LineChart', LineChart)
  .component('EventList', EventList)
  .component('FlowStepper', FlowStepper)
  .mount('#app')

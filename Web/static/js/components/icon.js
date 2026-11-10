// 線條風格圖示（24×24）。用法：<Icon name="zap" :size="18" />
const PATHS = {
  zap: ['M13 2 3 14h9l-1 8 10-12h-9l1-8z'],
  battery: ['M4 7h12a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z', 'M22 11v2'],
  server: ['M4 2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z',
    'M4 14h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2z', 'M6 6h.01', 'M6 18h.01'],
  cpu: ['M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z', 'M9 9h6v6H9z',
    'M9 1v3', 'M15 1v3', 'M9 20v3', 'M15 20v3', 'M20 9h3', 'M20 14h3', 'M1 9h3', 'M1 14h3'],
  database: ['M3 5c0-1.7 4-3 9-3s9 1.3 9 3-4 3-9 3-9-1.3-9-3z', 'M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5',
    'M3 12c0 1.7 4 3 9 3s9-1.3 9-3'],
  panel: ['M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z', 'M3 9h18', 'M9 21V9'],
  plug: ['M12 22v-5', 'M9 8V2', 'M15 8V2', 'M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z'],
  check: ['M20 6 9 17l-5-5'],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  alert: ['M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z', 'M12 9v4', 'M12 17h.01'],
  play: ['M6 3l14 9-14 9V3z'],
  pause: ['M6 4h4v16H6z', 'M14 4h4v16h-4z'],
  stop: ['M6 6h12v12H6z'],
  refresh: ['M21 12a9 9 0 1 1-3-6.7L21 8', 'M21 3v5h-5'],
  flask: ['M9 3h6', 'M10 3v6L4.2 19.5A1 1 0 0 0 5.1 21h13.8a1 1 0 0 0 .9-1.5L14 9V3', 'M7 15h10'],
  list: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01'],
  topology: ['M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    'M18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M8.6 13.5l6.8 4', 'M15.4 6.5l-6.8 4'],
  gauge: ['M12 14l4-4', 'M3.3 19a10 10 0 1 1 17.4 0'],
  sun: ['M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 2v2', 'M12 20v2', 'M4.9 4.9l1.4 1.4', 'M17.7 17.7l1.4 1.4',
    'M2 12h2', 'M20 12h2', 'M6.3 17.7l-1.4 1.4', 'M19.1 4.9l-1.4 1.4'],
  moon: ['M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z'],
  clock: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 6v6l4 2'],
  power: ['M12 2v10', 'M18.4 6.6a9 9 0 1 1-12.8 0'],
  shield: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', 'M9 12l2 2 4-4'],
  activity: ['M22 12h-4l-3 9L9 3l-3 9H2'],
  game: ['M4 6h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z', 'M6 12h4', 'M8 10v4',
    'M15 13h.01', 'M18 11h.01'],
  minus: ['M5 12h14'],
  circle: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z'],
  loader: ['M21 12a9 9 0 1 1-6.2-8.6'],
  key: ['M15.5 7.5a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0z', 'M13 11l8 8', 'M18 16l2-2', 'M15 13l2-2'],
  wifi: ['M5 12.6a10 10 0 0 1 14 0', 'M8.5 16.1a5 5 0 0 1 7 0', 'M2 9a15 15 0 0 1 20 0', 'M12 20h.01'],
  thermometer: ['M14 14.8V4a2 2 0 1 0-4 0v10.8a4 4 0 1 0 4 0z'],
  info: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 16v-4', 'M12 8h.01'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z', 'M21 21l-4.3-4.3'],
  external: ['M15 3h6v6', 'M10 14 21 3', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'],
}

export default {
  name: 'Icon',
  props: {
    name: { type: String, required: true },
    size: { type: [Number, String], default: 16 },
    stroke: { type: [Number, String], default: 2 },
  },
  computed: {
    paths() {
      return PATHS[this.name] || PATHS.circle
    },
  },
  template: /* html */ `
    <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         :stroke-width="stroke" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
         :class="{ spin: name === 'loader' }" style="flex: none">
      <path v-for="(d, i) in paths" :key="i" :d="d" />
    </svg>`,
}

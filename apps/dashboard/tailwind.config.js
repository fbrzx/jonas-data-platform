/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['IBM Plex Mono', 'monospace'],
        sans: ['IBM Plex Sans', 'sans-serif'],
      },
      colors: {
        'j-bg':           '#0a0c10',
        'j-surface':      '#111318',
        'j-surface2':     '#181c24',
        'j-border':       '#1e2430',
        'j-border-b':     '#2a3344',
        'j-text':         '#c8d0dc',
        'j-dim':          '#5a6478',
        'j-bright':       '#edf2f8',
        'j-accent':       '#4a9eff',
        'j-accent-dim':   '#1a3a5c',
        'j-green':        '#2dcc7a',
        'j-green-dim':    '#0d2e1c',
        'j-red':          '#ff4a6b',
        'j-red-dim':      '#2e0d18',
        'j-amber':        '#f5a623',
        'j-amber-dim':    '#2e1f06',
        'j-purple':       '#9b6dff',
        'j-purple-dim':   '#1c1230',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
      },
    },
  },
  plugins: [],
}

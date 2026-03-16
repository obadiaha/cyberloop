/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: '#0a0a0f',
          surface: '#111118',
          card: '#16161f',
          border: '#1e1e2a',
          'border-bright': '#2a2a3a',
          cyan: '#00e5ff',
          'cyan-dim': '#00a3b4',
          'cyan-glow': 'rgba(0, 229, 255, 0.15)',
          green: '#00ff88',
          'green-dim': '#00b860',
          'green-glow': 'rgba(0, 255, 136, 0.15)',
          amber: '#ffb300',
          red: '#ff3d57',
          text: '#e0e0e8',
          'text-dim': '#8888a0',
          'text-muted': '#55556a',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'cyber-cyan': '0 0 20px rgba(0, 229, 255, 0.1)',
        'cyber-green': '0 0 20px rgba(0, 255, 136, 0.1)',
      },
    },
  },
  plugins: [],
};

/**
 * Design tokens for the OmniAI console.
 *
 * The product is an operations console: someone watches four inboxes and
 * decides what a machine is allowed to do unsupervised. So the palette is
 * built like instrumentation — a quiet graphite ground, one warm signal
 * colour for anything that needs a human, and channel colours used strictly
 * as data encoding rather than decoration.
 *
 * Type has three roles, and each carries meaning:
 *   display  Space Grotesk  — headings and metric values
 *   body     Inter          — everything a person reads as prose
 *   mono     JetBrains Mono — machine-produced values only: confidence,
 *                             lead scores, ids, latency. If it's in mono,
 *                             a model or a platform produced it.
 */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Graphite ground — cool, low chroma, so the signal colour reads loud.
        ink: {
          950: '#0B0E13',
          900: '#12161C',
          800: '#181D25',
          700: '#212833',
          600: '#2C3542',
          500: '#3A4250',
          400: '#5A6474',
          300: '#8B93A1',
          200: '#B9C0CB',
          100: '#DEE2E8',
          50: '#F4F6F9',
        },
        // The one accent. Reserved for "a person is needed here".
        signal: {
          DEFAULT: '#FFB020',
          soft: '#FFC759',
          dim: '#8A5F12',
        },
        // Outcome colours — used for state, never for emphasis.
        ok: '#2ED17F',
        warn: '#FFB020',
        risk: '#FF5A5A',
        // Channel identity. These are the platforms' own colours because
        // operators already recognise them at a glance.
        channel: {
          whatsapp: '#25D366',
          instagram: '#E1306C',
          facebook: '#1877F2',
          x: '#8B93A1',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.06em' }],
        meta: ['0.75rem', { lineHeight: '1.125rem' }],
        metric: ['1.75rem', { lineHeight: '2rem', letterSpacing: '-0.02em' }],
      },
      borderRadius: { card: '10px', control: '7px' },
      boxShadow: {
        raise: '0 1px 2px rgba(0,0,0,.30), 0 8px 24px -12px rgba(0,0,0,.55)',
        glow: '0 0 0 1px rgba(255,176,32,.35), 0 0 24px -6px rgba(255,176,32,.35)',
      },
      transitionDuration: { DEFAULT: '160ms' },
      keyframes: {
        'slide-up': { from: { opacity: 0, transform: 'translateY(6px)' }, to: { opacity: 1, transform: 'none' } },
        'pulse-dot': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.35 } },
      },
      animation: {
        'slide-up': 'slide-up 200ms cubic-bezier(.2,.8,.3,1) both',
        'pulse-dot': 'pulse-dot 1.8s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */

/**
 * Tailwind configuration for Veritas — the AI Output Auditor UI.
 *
 * Colors are semantic tokens driven by CSS variables (see `src/index.css`), as
 * RGB triplets so Tailwind's `/<alpha-value>` opacity modifier keeps working.
 * A single set of component classes therefore themes itself in light and dark
 * with no `dark:` variants — the variables swap, the classes do not.
 */

function withVar(variable) {
  return `rgb(var(${variable}) / <alpha-value>)`;
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces & text (theme-driven).
        canvas: withVar('--c-canvas'),
        surface: withVar('--c-surface'),
        elevated: withVar('--c-elevated'),
        border: withVar('--c-border'),
        hairline: withVar('--c-hairline'),
        content: {
          DEFAULT: withVar('--c-text'),
          muted: withVar('--c-text-muted'),
          subtle: withVar('--c-text-subtle'),
        },
        // Brand accent.
        brand: {
          DEFAULT: withVar('--c-brand'),
          soft: withVar('--c-brand-soft'),
          contrast: withVar('--c-brand-contrast'),
        },
        accent: withVar('--c-accent'),
        // Verdict semantics (Evaluation Framework §6).
        verdict: {
          excellent: withVar('--c-excellent'),
          good: withVar('--c-good'),
          revision: withVar('--c-revision'),
          fail: withVar('--c-fail'),
          unverified: withVar('--c-unverified'),
        },
        // Finding severity.
        severity: {
          critical: withVar('--c-critical'),
          major: withVar('--c-major'),
          minor: withVar('--c-minor'),
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        soft: '0 1px 2px rgb(0 0 0 / 0.04), 0 4px 16px -4px rgb(0 0 0 / 0.10)',
        card: '0 1px 3px rgb(0 0 0 / 0.06), 0 12px 32px -12px rgb(0 0 0 / 0.18)',
        lift: '0 2px 6px rgb(0 0 0 / 0.08), 0 24px 48px -16px rgb(0 0 0 / 0.30)',
        glow: '0 0 0 1px rgb(var(--c-brand) / 0.25), 0 8px 40px -8px rgb(var(--c-brand) / 0.45)',
      },
      backgroundImage: {
        'grid-fade':
          'radial-gradient(circle at 1px 1px, rgb(var(--c-hairline) / 0.7) 1px, transparent 0)',
      },
      keyframes: {
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-6px)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s infinite',
        'fade-up': 'fade-up 0.5s cubic-bezier(0.22,1,0.36,1) both',
        float: 'float 6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

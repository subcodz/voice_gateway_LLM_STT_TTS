import flattenColorPalette from 'tailwindcss/lib/util/flattenColorPalette';

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  safelist: [
    'inset-sm',
    'inset-md',
    'inset-lg',
    'shadow-inset-sm',
    'shadow-inset-md',
    'shadow-inset-lg',
    'inset-shadow-2xs',
    'inset-shadow-xs',
    'inset-shadow-sm',
    'inset-shadow',
    'inset-shadow-md',
    'inset-shadow-lg',
    'inset-shadow-xl',
    'inset-shadow-2xl',
    'inset-shadow-neutral-500',
    'inset-shadow-neutral-400',
    'inset-shadow-gray-500',
    'inset-shadow-zinc-500',
    'inset-shadow-white',
    'inset-shadow-black',
    'inset-shadow-gray-600/60',
    'border-neutral-600/75',
    'inset-gray-500',
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#08080a',
          surface0: '#08080a',
          surface1: '#0e0e11',
          surface2: '#151518',
        },
        hairline: 'rgba(255, 255, 255, 0.09)',
        hairline2: 'rgba(255, 255, 255, 0.20)',
        txt: {
          primary: '#fafafa',
          secondary: '#a1a1aa',
          muted: '#71717a',
        }
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'Menlo', 'monospace'],
      },
      insetShadow: {
        '2xs': 'inset 0 1px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.15))',
        'xs': 'inset 0 1px 1px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.18))',
        'sm': 'inset 0 1px 2px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.22)), inset 0 1px 1px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.15))',
        DEFAULT: 'inset 0 2px 4px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.25)), inset 0 1px 2px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.18))',
        'md': 'inset 0 2px 4px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.25)), inset 0 1px 2px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.18))',
        'lg': 'inset 0 4px 8px -1px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.3)), inset 0 2px 4px -2px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.2))',
        'xl': 'inset 0 8px 16px -2px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.35)), inset 0 4px 6px -3px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.25))',
        '2xl': 'inset 0 16px 24px -4px var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.4))',
        'inner': 'inset 0 2px 4px 0 var(--tw-inset-shadow-color, rgba(255, 255, 255, 0.25))',
        'none': '0 0 #0000',
      },
      boxShadow: {
        'inset-md': 'inset 0 2px 4px rgba(255, 255, 255, 0.25), inset 0 1px 2px rgba(255, 255, 255, 0.18)',
        'inset-sm': 'inset 0 1px 2px rgba(255, 255, 255, 0.22)',
        'inset-lg': 'inset 0 4px 8px -1px rgba(255, 255, 255, 0.3)',
      },
      inset: {
        'md': '1rem',
      }
    },
  },
  plugins: [
    function({ matchUtilities, addUtilities, theme }) {
      matchUtilities(
        {
          'inset-shadow': (value) => ({
            '--tw-inset-shadow': value,
            'box-shadow': 'var(--tw-inset-shadow, 0 0 #0000), var(--tw-ring-offset-shadow, 0 0 #0000), var(--tw-ring-shadow, 0 0 #0000), var(--tw-shadow, 0 0 #0000) !important',
          }),
          'shadow-inset': (value) => ({
            '--tw-inset-shadow': value,
            'box-shadow': 'var(--tw-inset-shadow, 0 0 #0000), var(--tw-ring-offset-shadow, 0 0 #0000), var(--tw-ring-shadow, 0 0 #0000), var(--tw-shadow, 0 0 #0000) !important',
          }),
        },
        { values: theme('insetShadow'), type: ['shadow', 'any'] }
      );

      matchUtilities(
        {
          'inset-shadow': (value) => ({
            '--tw-inset-shadow-color': value,
          }),
          'inset': (value) => ({
            '--tw-inset-shadow-color': value,
          }),
        },
        { values: flattenColorPalette(theme('colors')), type: ['color', 'any'] }
      );
    },
  ],
}

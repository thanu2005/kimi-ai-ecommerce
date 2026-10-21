/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: '#f9fbff',
        'surface-dim': '#d0deff',
        'surface-container-low': '#e8eeff',
        'surface-container': '#dde8ff',
        'surface-container-high': '#eff4ff',
        'surface-container-highest': '#1041f5',
        'on-surface': '#241a0f',
        'on-surface-variant': '#4d463b',
        'outline': '#7e766a',
        'outline-variant': '#cfc5b7',
        primary: '#6f5c36',
        'on-primary': '#ffffff',
        'primary-container': '#c2a97d',
        'secondary-container': '#f9dfb5',
        secondary : '#41b1c5',
        'on-secondary': '#41b1c5',
        error: '#ba1a1a',
        'error-container': '#ffdad6',
        success: '#2e7d32',
        'success-container': '#c8e6c9',
      },
      fontFamily: {
        sans: ['"Annie Use Your Telescope"', 'cursive'],
        nabla: ['Nabla', 'cursive'],
        'chelsea-market': ['"Chelsea Market"', 'cursive'],
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'dot-bounce': {
          '0%, 80%, 100%': { transform: 'scale(0.8)', opacity: '0.5' },
          '40%': { transform: 'scale(1.1)', opacity: '1' },
        },
      },
      animation: {
        blink: 'blink 1.2s step-end infinite',
        'fade-in': 'fade-in 0.25s ease-out',
        'dot-1': 'dot-bounce 1.4s ease-in-out 0s infinite',
        'dot-2': 'dot-bounce 1.4s ease-in-out 0.2s infinite',
        'dot-3': 'dot-bounce 1.4s ease-in-out 0.4s infinite',
      },
    },
  },
  plugins: [],
};

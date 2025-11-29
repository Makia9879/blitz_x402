import { defineConfig } from 'windicss/helpers'

export default defineConfig({
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          primary: '#3DD2FF',
          accent: '#7C3AED',
          muted: '#0F172A',
        },
      },
      boxShadow: {
        glow: '0 0 45px rgba(61, 210, 255, 0.25)',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
})

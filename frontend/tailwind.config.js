/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Heebo', 'Assistant', 'Segoe UI', 'Arial', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#eef6ff',
          100: '#d9eaff',
          500: '#2f7de1',
          600: '#1f63c0',
          700: '#184f9a',
        },
      },
    },
  },
  plugins: [],
}

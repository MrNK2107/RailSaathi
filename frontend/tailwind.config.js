/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rail: { 50: '#eef4fb', 100: '#d5e4f5', 600: '#1d4f91', 700: '#163d70', 800: '#102c52' },
        // Mobile app palette (matched to the reference design)
        brand: { 50: '#eef4ff', 100: '#dbe7ff', 200: '#bcd2ff', 500: '#2f6bf2', 600: '#1a56db', 700: '#1645b5', 900: '#0f2a6b' },
        ink: { 900: '#0f1f45', 700: '#33405e', 500: '#64708a', 300: '#c9d1e3', 100: '#eef1f7' },
        // 700 shades carry white badge text (at least 4.5:1); 600 / 500 are for icons and rings.
        match: { 700: '#15803d', 600: '#16a34a', 50: '#ecfdf3' },
        cheap: { 600: '#2563eb', 50: '#eff6ff' },
        fast: { 700: '#c2410c', 500: '#f97316', 50: '#fff4ec' },
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans Tamil', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: { card: '0 2px 10px rgba(15, 42, 107, 0.08)' },
    },
  },
  plugins: [],
}

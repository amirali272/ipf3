/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0f1012",
          900: "#141518",
          850: "#17191c",
          800: "#1c1e22",
          750: "#22252a",
          700: "#2a2d33",
          600: "#3a3e46",
          500: "#5a5f69",
          400: "#8a8f99",
          300: "#b4b8c0",
          200: "#d6d8dd",
          100: "#eceef1",
        },
        emerald: {
          300: "#6ee7b7",
          400: "#34d399",
          500: "#10b981",
          600: "#0ea271",
          700: "#047857",
          900: "#064e3b",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: { card: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)" },
    },
  },
  plugins: [],
};

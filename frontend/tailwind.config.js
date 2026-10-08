/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: { accent: { 50: "#eef4ff", 100: "#dbe7ff", 500: "#2f6fec", 600: "#1f5bd6", 700: "#1a49ad" } },
      fontFamily: { mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};

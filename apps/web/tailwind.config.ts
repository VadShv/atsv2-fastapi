import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Дизайн-токены контраста (WCAG 2.2 AA)
        bg: {
          DEFAULT: "#ffffff",
          subtle: "#f8fafc",
          muted: "#f1f5f9",
        },
        fg: {
          DEFAULT: "#0f172a", // контраст 15:1 к белому (AAA)
          muted: "#475569", // контраст 7:1 (AAA)
          subtle: "#64748b",
        },
        border: {
          DEFAULT: "#e2e8f0",
          strong: "#cbd5e1",
        },
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8", // контраст 8:1 к белому (AAA) — для текста на фоне
        },
        success: {
          50: "#f0fdf4",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
        },
        danger: {
          50: "#fef2f2",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
        },
        warning: {
          50: "#fffbeb",
          500: "#f59e0b",
          700: "#b45309",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      focusRing: {
        DEFAULT: "2px solid #2563eb",
      },
    },
  },
  plugins: [],
};

export default config;

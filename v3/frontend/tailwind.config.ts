import type { Config } from "tailwindcss";

// colours live in CSS variables (see globals.css) so light/dark share one set of class names
const withAlpha = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: withAlpha("bg"),
        sidebar: withAlpha("sidebar"),
        panel: withAlpha("panel"),
        line: withAlpha("line"),
        ink: withAlpha("ink"),
        muted: withAlpha("muted"),
        accent: withAlpha("accent"),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        serif: ["ui-serif", "Georgia", "'Iowan Old Style'", "'Times New Roman'", "serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

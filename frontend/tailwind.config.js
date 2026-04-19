/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        "background-soft": "var(--background-soft)",
        foreground: "var(--foreground)",
        "foreground-muted": "var(--foreground-muted)",
        card: {
          DEFAULT: "var(--card)",
          elevated: "var(--card-elevated)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          hover: "var(--primary-hover)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          hover: "var(--muted-hover)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        "input-bg": "var(--input-background)",
        ring: "var(--ring)",
        success: "var(--success)",
        warning: "var(--warning)",
        danger: "var(--danger)",
      },
      borderRadius: {
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(230,106,138,0.35), 0 20px 60px -20px rgba(230,106,138,0.35)",
        card: "0 1px 0 rgba(255,255,255,0.04) inset, 0 20px 40px -24px rgba(0,0,0,0.6)",
      },
      backgroundImage: {
        "cosmic-banner":
          "linear-gradient(90deg, #5b4b8a 0%, #8b78c7 45%, #e66a8a 100%)",
        "cosmic-text":
          "linear-gradient(90deg, #e66a8a 0%, #c197e6 50%, #8b78c7 100%)",
      },
    },
  },
  plugins: [],
}

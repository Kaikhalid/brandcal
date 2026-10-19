"use client"

import { Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"

// Both icons stay in the DOM and cross-fade (scale 0.25 to 1, opacity, 4px blur); the dark:
// variants follow the class on <html>, so there is no state to hydrate.
const swap =
  "absolute inset-0 m-auto size-5 transition-[opacity,filter,scale] duration-300 ease-[cubic-bezier(0.2,0,0,1)]"

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <button
      type="button"
      aria-label="Switch between light and dark"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="press relative inline-flex size-10 items-center justify-center rounded-full border border-control bg-surface text-ink hover:bg-muted"
    >
      <Sun
        aria-hidden="true"
        strokeWidth={1.5}
        className={`${swap} scale-100 opacity-100 blur-none dark:scale-[0.25] dark:opacity-0 dark:blur-[4px]`}
      />
      <Moon
        aria-hidden="true"
        strokeWidth={1.5}
        className={`${swap} scale-[0.25] opacity-0 blur-[4px] dark:scale-100 dark:opacity-100 dark:blur-none`}
      />
    </button>
  )
}

export { ThemeToggle }

"use client"

import * as React from "react"

/** Does the media query match? False until the browser has answered (the first paint is empty
 *  anyway: every view waits for its data). */
export function useMedia(query: string): boolean {
  const [matches, setMatches] = React.useState(false)
  React.useEffect(() => {
    const list = window.matchMedia(query)
    const update = () => setMatches(list.matches)
    update()
    list.addEventListener("change", update)
    return () => list.removeEventListener("change", update)
  }, [query])
  return matches
}

"use client"

import * as React from "react"

/** The content width of an element, kept current by a ResizeObserver; null until it is measured.
 *  Layout that follows the space a box really has (the post panel opening takes width from the
 *  calendar) reads this, not the viewport. Render the safe layout while it is null. */
export function useElementWidth<T extends HTMLElement>(): [React.RefCallback<T>, number | null] {
  const [width, setWidth] = React.useState<number | null>(null)
  const observer = React.useRef<ResizeObserver | null>(null)
  const ref = React.useCallback((node: T | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!node) return
    setWidth(node.clientWidth)
    observer.current = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width))
    })
    observer.current.observe(node)
  }, [])
  return [ref, width]
}

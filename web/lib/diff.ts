// A small line diff (longest common subsequence). No library: the inputs are a post's few lines.

export type DiffLine = { sign: "+" | "-" | " "; text: string }

export function diffLines(a: string[], b: string[]): DiffLine[] {
  const n = a.length
  const m = b.length
  // t[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const t = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ sign: " ", text: a[i] })
      i++
      j++
    } else if (t[i + 1][j] >= t[i][j + 1]) {
      out.push({ sign: "-", text: a[i++] })
    } else {
      out.push({ sign: "+", text: b[j++] })
    }
  }
  while (i < n) out.push({ sign: "-", text: a[i++] })
  while (j < m) out.push({ sign: "+", text: b[j++] })
  return out
}

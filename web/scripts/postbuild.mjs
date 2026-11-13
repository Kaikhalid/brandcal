// After `next build`: copy web/out/ into src/brandcal/web_next/ and write csp.json, the
// sha256 of every inline <script>, <style> and style="" value of each HTML page, so that
// `brandcal serve` can send a Content-Security-Policy without 'unsafe-inline'.
import { createHash } from "node:crypto"
import { cpSync, existsSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { dirname, join, relative, sep } from "node:path"
import { fileURLToPath } from "node:url"

const web = join(dirname(fileURLToPath(import.meta.url)), "..")
const out = join(web, "out")
const dest = join(web, "..", "src", "brandcal", "web_next")

const sha256 = (text) => `sha256-${createHash("sha256").update(text, "utf8").digest("base64")}`
const unique = (items) => [...new Set(items.map(sha256))].sort()

// What a browser hashes for a style="" attribute is the decoded value.
function decodeEntities(value) {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" }
  return value.replace(/&(?:#x([0-9a-f]+)|#(\d+)|([a-z]+));/gi, (all, hex, dec, name) => {
    if (hex) return String.fromCodePoint(parseInt(hex, 16))
    if (dec) return String.fromCodePoint(parseInt(dec, 10))
    return named[name.toLowerCase()] ?? all
  })
}

function inlineHashes(html) {
  const scripts = []
  for (const [, attrs, body] of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (!/\bsrc\s*=/i.test(attrs)) scripts.push(body)
  }
  const styles = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map((m) => m[1])
  // Attribute search must skip script and style bodies (the RSC payload quotes markup).
  const markup = html.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, "")
  const attrs = [...markup.matchAll(/\sstyle="([^"]*)"/gi)].map((m) => decodeEntities(m[1]))
  return { script: unique(scripts), style: unique(styles), style_attr: unique(attrs) }
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => (a.name < b.name ? -1 : 1))
    .flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]))
}

if (!existsSync(join(out, "index.html"))) {
  throw new Error("web/out/index.html is missing: run `next build` first")
}
rmSync(dest, { recursive: true, force: true })
cpSync(out, dest, { recursive: true })

const manifest = {}
for (const file of walk(dest).filter((f) => f.endsWith(".html"))) {
  const rel = relative(dest, file).split(sep).join("/")
  manifest[rel] = inlineHashes(readFileSync(file, "utf8"))
}
writeFileSync(join(dest, "csp.json"), `${JSON.stringify(manifest, null, 2)}\n`)
console.log(`postbuild: ${Object.keys(manifest).length} page(s) copied to src/brandcal/web_next/`)

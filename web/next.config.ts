import type { NextConfig } from "next"

// Static export: `npm run build` writes plain files to web/out/, which
// `brandcal serve` will later serve (no Node needed at runtime).
const nextConfig: NextConfig = {
  output: "export",
  // Emit /route/index.html so a plain static file server resolves /route/ without rewrites.
  trailingSlash: true,
  images: { unoptimized: true },
}

export default nextConfig

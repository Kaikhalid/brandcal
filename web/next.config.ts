import type { NextConfig } from "next"

// Static export: `npm run build` writes plain files to web/out/, and scripts/postbuild.mjs
// copies them into src/brandcal/web_next/, which `brandcal serve` serves (no Node at runtime).
const nextConfig: NextConfig = {
  output: "export",
  // Emit /route/index.html so a plain static file server resolves /route/ without rewrites.
  trailingSlash: true,
  images: { unoptimized: true },
  // A fixed id keeps the committed build byte-identical from one run to the next.
  generateBuildId: async () => "brandcal-ui",
}

export default nextConfig

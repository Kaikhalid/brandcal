import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

// Tests supply what the repo deliberately does not hold: the display offset (the repo has no
// timezone default) and a fake secret. The padding around the secret checks that it is trimmed.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          DISPLAY_UTC_OFFSET: "+03:00",
          RELAY_SECRET: "  test-relay-secret-not-real\n",
        },
      },
    }),
  ],
  test: { include: ["test/**/*.test.ts"] },
});

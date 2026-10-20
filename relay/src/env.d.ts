declare namespace Cloudflare {
  interface Env {
    RELAY: DurableObjectNamespace<import("./relay_do").Relay>;
    PUBLIC_HOST: string;
    RELAY_HOST: string;
    /** Set in the private deployment config, for example "+03:00". There is no default. */
    DISPLAY_UTC_OFFSET?: string;
    /** A secret: set it with `wrangler secret put`, never in a file in the repo. */
    RELAY_SECRET: string;
  }
}

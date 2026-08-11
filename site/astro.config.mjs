// @ts-check
import { defineConfig } from "astro/config";

// The site is a static publication of what the pipeline already computed.
// It performs no computation: no AI, embedding, ingestion, or third-party API
// call at build time or request time (AD-1). Its only input is the JSON under
// data/briefings/, which the pipeline writes (AD-2).
export default defineConfig({
  output: "static",
  build: {
    // One file per route rather than a directory with index.html, so the
    // published Briefing paths stay legible.
    format: "file",
  },
});

// Story 5.2: registers site/public/sw.js on every page. Unlike
// language-detect.ts (deliberately /-only, Story 4.7's own scoping
// decision for the browser-language redirect), the service worker must
// intercept requests on every route, so this script loads from
// BriefingPage.astro's own always-loaded <script> tag, not the
// /-only extra-scripts slot.
//
// Feature-detected and guarded so a browser without service-worker
// support (or one that blocks registration for any reason) degrades
// silently -- the reading experience never depends on this succeeding;
// every page already works with zero JS at all (Story 4.1's own no-JS
// guarantee).
import { OFFLINE_BANNER_META_NAME } from "./sw-logic";

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    // Swallow -- a failed registration must not be visible to the
    // reader or break anything else on the page.
  });
}

// Story 5.4 (AC1): the service worker injects this <meta> tag into a
// page's HTML only when serving it from the offline-cache fallback (a
// real network failure occurred) -- its presence is a normal DOM read,
// available immediately on page load, since HTTP response headers
// aren't readable by page JS after a real navigation has already
// completed. The banner element itself (BriefingPage.astro's own
// #offline-banner, already rendered server-side with the correct
// per-language text, just hidden via CSS by default) only needs to be
// revealed here -- no text/content to inject, no per-language logic
// needed in this script at all.
if (document.querySelector(`meta[name="${OFFLINE_BANNER_META_NAME}"]`)) {
  const banner = document.getElementById("offline-banner");
  if (banner) banner.style.display = "block";
}

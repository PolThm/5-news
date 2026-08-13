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
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    // Swallow -- a failed registration must not be visible to the
    // reader or break anything else on the page.
  });
}

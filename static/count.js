// Anonymous visit counter (our own, no cookies, no storage, no IP kept).
// Sends the page path and kind once per page view to /api/hit on our server.
(function () {
  try {
    var data = JSON.stringify({ p: location.pathname, k: document.body.dataset.pageType || "page" });
    if (navigator.sendBeacon) navigator.sendBeacon("/api/hit", new Blob([data], { type: "application/json" }));
    else fetch("/api/hit", { method: "POST", body: data, keepalive: true });
  } catch (e) {}
})();

const CACHE_NAME = "vrc-aw-shell-v1";
const OFFLINE_URL = "/static/offline.html";
const SHELL_ASSETS = [OFFLINE_URL, "/static/css/app.css", "/static/js/app.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Only intercept full-page navigations (address bar loads, reloads, link
// clicks) - a deploy restart briefly takes the origin down and Cloudflare
// serves its own generic 502 page in the meantime. Sub-resource requests
// (CSS/JS/images/API calls) pass straight through so nothing here can mask
// a real API error as a network problem.
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") {
    return;
  }
  event.respondWith(
    fetch(event.request).then(
      (response) => (response && response.status >= 500 ? caches.match(OFFLINE_URL) : response),
      () => caches.match(OFFLINE_URL)
    )
  );
});

// Web Push: the server sends a JSON payload ({title, body, url}) as the push
// message data. Falls back to generic text if a push somehow arrives with no
// data (the Push API allows that).
self.addEventListener("push", (event) => {
  let payload = { title: "VRChat Avatar Watch", body: "新しい通知があります", url: "/me" };
  if (event.data) {
    try {
      payload = { ...payload, ...event.data.json() };
    } catch (err) {
      payload.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      data: { url: payload.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url ? event.notification.data.url : "/me";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.endsWith(url) && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});

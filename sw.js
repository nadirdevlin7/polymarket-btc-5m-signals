
"use strict";

// BTC AI service worker
// Handles informational paper-trading push notifications.

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};

  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }

  const title = "BTC AI — Paper Trading";

  const options = {
    body: "A new simulated trading event is available.",
    icon: "./icon-192.png",
    badge: "./icon-192.png",
    tag: "btc-ai-paper-event",
    data: {
      url: "./"
    }
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil(
    self.clients.openWindow(
      new URL("./", self.registration.scope).href
    )
  );
});

// Service worker van de vissenlijst: toont pushmeldingen, ook als de site dicht is.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (err) { data = {body: e.data ? e.data.text() : ""}; }
  e.waitUntil(self.registration.showNotification(data.title || "Vissenlijst", {
    body: data.body || "Er is iets veranderd in het aanbod.",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: "vissenlijst",
    data: {url: data.url || "./"},
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL(e.notification.data && e.notification.data.url || "./", self.location.href).href;
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(vensters => {
    const open = vensters.find(v => v.url.split("?")[0] === url.split("?")[0]);
    return open ? open.focus() : self.clients.openWindow(url);
  }));
});

// Shared service-worker registration for installable static pages.
export function registerOffline({ serviceWorker = navigator.serviceWorker,
                                  protocol = location.protocol } = {}) {
  if (!serviceWorker || protocol === "file:") return Promise.resolve(null);
  return serviceWorker.register("/sw.js", { type: "module" }).catch((error) => {
    console.warn("Offline mode unavailable:", error.message);
    return null;
  });
}

(function () {
  const root = document.documentElement;
  const saved = localStorage.getItem("theme-mode") || "system";
  root.dataset.theme = saved;
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = root.dataset.theme === "light" ? "dark" : root.dataset.theme === "dark" ? "system" : "light";
      root.dataset.theme = next;
      localStorage.setItem("theme-mode", next);
    });
  });
})();

(function () {
  // Generic <dialog> handling: any [data-modal-close] button closes its
  // enclosing dialog, and clicking the backdrop (the dialog element itself,
  // outside its content wrapper) closes it too.
  document.addEventListener("click", (event) => {
    const closeButton = event.target.closest("[data-modal-close]");
    if (closeButton) {
      closeButton.closest("dialog")?.close();
      return;
    }
    if (event.target instanceof HTMLDialogElement) {
      event.target.close();
    }
  });
})();

// Generic helpers for the "submit a background job, then watch its progress
// in a modal" pattern used by the admin reclassify action and the BOOTH
// library import. isStatusDialogOpen(id) is meant for use inside an
// hx-trigger filter (e.g. "every 2s [isStatusDialogOpen('foo-dialog')]") so
// the live panel only polls the server while its dialog is actually open.
window.isStatusDialogOpen = function (dialogId) {
  const dialog = document.getElementById(dialogId);
  return !!dialog && dialog.open;
};

window.openStatusDialog = function (dialogId, panelId) {
  const dialog = document.getElementById(dialogId);
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  if (window.htmx && panelId) {
    window.htmx.trigger("#" + panelId, "load");
  }
};

// Lets a deploy restart's brief 502 window show our own "restarting" page
// instead of the host's generic error page - see /sw.js. Only takes effect
// on a user's second visit onward (the worker has to already be installed
// before an outage starts), so it can't help a first-time visitor.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

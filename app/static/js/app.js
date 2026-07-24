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

window.isReclassifyDialogOpen = function () {
  const dialog = document.getElementById("reclassify-dialog");
  return !!dialog && dialog.open;
};

window.openReclassifyDialog = function () {
  const dialog = document.getElementById("reclassify-dialog");
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  if (window.htmx) {
    window.htmx.trigger("#reclassify-live-panel", "load");
  }
};

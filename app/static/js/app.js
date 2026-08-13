// Merges a "prefix:value" token into a space-separated query string without
// clobbering the other tokens already there - used by the search filters
// (sale:/free:/tool:/avatar:) so multiple conditions can be active at once
// instead of each checkbox overwriting the whole query.
window.setQueryToken = function (input, prefix, value) {
  const tokens = input.value.split(/\s+/).filter(Boolean).filter((token) => !token.startsWith(prefix));
  if (value) tokens.push(prefix + value);
  input.value = tokens.join(" ");
};

(function () {
  // Popular-tag cloud (search.html): clicking a [data-tag-chip] toggles it
  // on/off and folds/removes a "tag:<name>" token via setQueryToken. Only
  // one tag can be active at a time, matching the single-value tag: filter
  // the backend already supports.
  document.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-tag-chip]");
    if (!chip) return;
    const form = chip.closest("section").querySelector("form");
    const isActive = chip.classList.toggle("active");
    chip.closest(".tag-cloud").querySelectorAll(".tag-chip").forEach((other) => {
      if (other !== chip) other.classList.remove("active");
    });
    setQueryToken(form.q, "tag:", isActive ? chip.dataset.tagChip : "");
    htmx.trigger(form, "change");
  });
})();

(function () {
  // Avatar suggest dropdown (search.html): picking a [data-avatar-name]
  // button folds the name into the hidden query string via setQueryToken
  // and re-runs search. Delegated (not inline onclick) so avatar names with
  // quotes can't break out of an HTML attribute.
  document.addEventListener("click", (event) => {
    const suggestItem = event.target.closest(".suggest-item");
    if (suggestItem) {
      const wrap = suggestItem.closest(".avatar-hint");
      const form = wrap.closest("form");
      wrap.querySelector(".avatar-hint-input").value = suggestItem.dataset.avatarName;
      setQueryToken(form.q, "avatar:", suggestItem.dataset.avatarName);
      document.getElementById("avatar-suggest-list").innerHTML = "";
      htmx.trigger(form, "change");
      return;
    }
    if (event.target.closest(".avatar-hint")) return;
    const list = document.getElementById("avatar-suggest-list");
    if (list) list.innerHTML = "";
  });
})();

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

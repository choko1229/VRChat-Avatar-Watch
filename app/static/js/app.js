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
  // Sort bar (items/sort_bar.html + search.html's own sort buttons): the
  // sort bar lives outside the #item-grid htmx swaps, so it never
  // re-renders on its own after a sort click. Toggle the active class
  // client-side immediately so the highlighted chip matches the click even
  // before (and regardless of) the grid's htmx response landing.
  document.addEventListener("click", (event) => {
    const chip = event.target.closest(".sort-chip");
    if (!chip) return;
    const bar = chip.closest(".sort-bar");
    if (!bar) return;
    bar.querySelectorAll(".sort-chip").forEach((el) => el.classList.toggle("active", el === chip));
  });
})();

(function () {
  // Grid/compare view toggle (avatars/detail.html): switches which
  // [data-view-panel] is visible within the enclosing section, purely
  // client-side (both panels are already rendered server-side).
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-view-toggle]");
    if (!toggle) return;
    const group = toggle.closest(".view-toggle");
    const container = toggle.closest("section");
    group.querySelectorAll("[data-view-toggle]").forEach((btn) => btn.classList.toggle("active", btn === toggle));
    container.querySelectorAll("[data-view-panel]").forEach((panel) => {
      panel.toggleAttribute("hidden", panel.dataset.viewPanel !== toggle.dataset.viewToggle);
    });
  });
})();

(function () {
  // Query-syntax help chips (search.html, inside the collapsible <details
  // class="query-details">): clicking a [data-insert-syntax] chip appends
  // that snippet to the text search box (with a leading space if needed)
  // and focuses it so the user can fill in the value - it doesn't auto-run
  // search, since chips like "shop:" are incomplete on their own.
  document.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-insert-syntax]");
    if (!chip) return;
    const form = chip.closest("form");
    const input = form.q;
    const sep = input.value && !input.value.endsWith(" ") ? " " : "";
    input.value += sep + chip.dataset.insertSyntax;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });
})();

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
  // Site-curated facet-tag cloud (search.html): same single-value toggle
  // pattern as the popular-tag cloud above, but folds a "facet:<slug>"
  // token instead of "tag:<name>" - kept separate so BOOTH seller tags and
  // the site's own taste/body-type/color/genre labels can't collide in the
  // query string.
  document.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-facet-chip]");
    if (!chip) return;
    const form = chip.closest("section").querySelector("form");
    const isActive = chip.classList.toggle("active");
    chip.closest(".facet-cloud").querySelectorAll(".tag-chip").forEach((other) => {
      if (other !== chip) other.classList.remove("active");
    });
    setQueryToken(form.q, "facet:", isActive ? chip.dataset.facetChip : "");
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
  // Push notification opt-in (me.html): converts the VAPID public key from
  // base64url to the Uint8Array PushManager.subscribe() expects, requests
  // browser permission, subscribes, and posts the subscription to the
  // server so notification dispatch can target it later.
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = atob(base64);
    return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-push-subscribe]");
    if (!button || button.disabled) return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      alert("お使いのブラウザはプッシュ通知に対応していません。");
      return;
    }
    button.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        button.disabled = false;
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(button.dataset.vapidKey),
      });
      const subJson = subscription.toJSON();
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          csrf: button.dataset.csrf,
          endpoint: subJson.endpoint,
          p256dh: subJson.keys.p256dh,
          auth: subJson.keys.auth,
        }),
      });
      button.textContent = "このブラウザへのプッシュ通知は有効です";
    } catch (err) {
      button.disabled = false;
      alert("プッシュ通知の有効化に失敗しました。");
    }
  });
})();

(function () {
  const root = document.documentElement;
  const saved = localStorage.getItem("theme-mode") || "system";
  root.dataset.theme = saved;
  const ICONS = { light: "light_mode", dark: "dark_mode", system: "brightness_auto" };
  function syncIcons() {
    document.querySelectorAll("[data-theme-icon]").forEach((icon) => {
      icon.textContent = ICONS[root.dataset.theme] || ICONS.system;
    });
  }
  syncIcons();
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = root.dataset.theme === "light" ? "dark" : root.dataset.theme === "dark" ? "system" : "light";
      root.dataset.theme = next;
      localStorage.setItem("theme-mode", next);
      syncIcons();
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

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

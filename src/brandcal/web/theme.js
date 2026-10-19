"use strict";
// Blocking, external, in <head>: sets the theme before first paint so there is no flash.
(() => {
  const KEY = "brandcal-theme";
  const root = document.documentElement;
  const dark = window.matchMedia("(prefers-color-scheme: dark)");

  function preference() {
    try {
      const saved = window.localStorage.getItem(KEY);
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  }

  function apply() {
    const pref = preference();
    root.dataset.themePref = pref;
    root.dataset.theme = pref === "system" ? (dark.matches ? "dark" : "light") : pref;
  }

  window.brandcalTheme = {
    preference,
    set(value) {
      try {
        window.localStorage.setItem(KEY, value);
      } catch {
        // Storage can be blocked; the choice then lasts until the page closes.
        root.dataset.themePref = value;
      }
      apply();
    },
  };
  dark.addEventListener("change", apply);
  apply();
})();

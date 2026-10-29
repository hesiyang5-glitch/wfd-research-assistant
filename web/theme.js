// Display theme (light by default; dark is opt-in). Loaded in <head> so the page never flashes the wrong theme.
// Stored only in this browser; it changes nothing on the server.
(function () {
  var th = "light";
  try { th = localStorage.getItem("wfd_theme") === "dark" ? "dark" : "light"; } catch (e) {}
  document.documentElement.setAttribute("data-theme", th);
})();

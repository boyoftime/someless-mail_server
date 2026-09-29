// The webmail's first page after logging in, and any page drawn again (a refresh), comes in with
// its motion (webmail-app.css, body.is-arriving). Going from page to page in it (another folder,
// a message's link, a search) is quieter: only the mail settles in (html.wm-been). The login
// page (data-login) starts it over.
(function () {
  var script = document.currentScript;
  try {
    if (script && script.hasAttribute("data-login")) {
      sessionStorage.removeItem("wm_arrived");
      return;
    }
    var entry = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    var again = entry && entry.type === "reload";
    if (sessionStorage.getItem("wm_arrived") && !again) document.documentElement.classList.add("wm-been");
    sessionStorage.setItem("wm_arrived", "1");
  } catch (error) { /* (a private window: each page comes in with its motion) */ }
})();

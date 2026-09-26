// The SMTP guide: one language's example at a time, chosen with the tabs (click, or the arrow
// keys, Home and End). The browser remembers the language for the next visit. Without
// JavaScript, every example shows, one under another.
(function () {
  var tabs = Array.from(document.querySelectorAll("[data-code-tab]"));
  if (!tabs.length) return;
  var remembered = null;
  try {
    remembered = localStorage.getItem("someless-code-language");
  } catch (error) { /* no storage (private window): start with the first */ }

  function choose(tab, focus) {
    tabs.forEach(function (other) {
      var chosen = other === tab;
      other.setAttribute("aria-selected", chosen ? "true" : "false");
      other.tabIndex = chosen ? 0 : -1;
      document.getElementById(other.getAttribute("aria-controls")).hidden = !chosen;
    });
    if (focus) tab.focus();
    try {
      localStorage.setItem("someless-code-language", tab.dataset.codeTab);
    } catch (error) { /* not remembered, that's all */ }
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () { choose(tab, false); });
    tab.addEventListener("keydown", function (event) {
      var to = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
      if (to === undefined) return;
      event.preventDefault();
      choose(tabs[(to + tabs.length) % tabs.length], true);
    });
  });

  var start = tabs.filter(function (tab) { return tab.dataset.codeTab === remembered; })[0] || tabs[0];
  choose(start, false);
})();

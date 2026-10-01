// The server name's certificate, followed live (SMTP & API, Settings > Mail server name): while
// it's missing, the page asks how it stands every few seconds, and asking is itself what has it
// asked for the moment the proxy host works (engine/certificate.py). The line says so as it goes:
// waiting for the proxy host, then getting it (its mark turning), then in; then the page comes
// again, all its checks fresh. It rests while the tab is hidden, and stops with the page.
(function () {
  var row = document.querySelector("[data-certificate-watch]");
  if (!row || row.dataset.watching) return;
  row.dataset.watching = "1";
  var url = row.dataset.certificateWatch;
  var EVERY = 8000;   // ms

  function show(found) {
    var detail = row.querySelector(".ready-detail");
    if (detail && found.detail) detail.textContent = found.detail;
    row.classList.toggle("is-getting", found.state === "getting");
    if (found.state !== "ok") return;
    clearInterval(timer);
    row.classList.remove("is-missing", "is-getting");
    row.classList.add("is-ok");
    setTimeout(function () { window.location.reload(); }, 1600);   // (every check fresh: Ready to send lights up)
  }

  function look() {
    if (!row.isConnected) return clearInterval(timer);   // left the page
    if (document.hidden) return;
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (found) { if (found && row.isConnected) show(found); })
      .catch(function () { /* the next look tries again */ });
  }

  var timer = setInterval(look, EVERY);
  look();
})();

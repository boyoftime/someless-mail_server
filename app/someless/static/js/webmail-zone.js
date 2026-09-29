// The reader's time zone, for the webmail to show times in (messages.py reads the wm_tz cookie):
// set on the login page and on each page after it. When it changes (the first visit, a trip),
// the mail page (data-redraw) draws itself again once, in the right times.
(function () {
  var zone;
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (error) {
    return;
  }
  if (!zone) return;
  var had = (document.cookie.match(/(?:^|;\s*)wm_tz=([^;]*)/) || [])[1];
  if (had && decodeURIComponent(had) === zone) return;
  document.cookie = "wm_tz=" + encodeURIComponent(zone) + "; path=/; max-age=31536000; samesite=lax" +
    (location.protocol === "https:" ? "; secure" : "");
  var script = document.currentScript;
  if (!script || !script.hasAttribute("data-redraw")) return;
  try {
    if (sessionStorage.getItem("wm_tz_redrawn") === zone) return;   // once: never round and round
    sessionStorage.setItem("wm_tz_redrawn", zone);
  } catch (error) {
    return;
  }
  location.reload();
})();

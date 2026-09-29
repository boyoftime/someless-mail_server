// New mail in the webmail as it comes, without a refresh (webmail/live.py): a WebSocket stays open
// while the page is, and the webmail says when mail came to the Inbox (who it's from) or when
// anything else changed (read on a phone, moved in a mail app). New mail rings (the new-mail
// sound, unless it's switched off in Settings), shows the computer's own notification when that's
// switched on and the tab is out of sight, and comes in at the top of the list; the counts and
// the tab's title follow. When the connection drops, it tries again, a little later each time.
(function () {
  var shell = document.querySelector("[data-wm-shell]");
  if (!shell || !window.WebSocket || !window.wm) return;
  var settings = shell.dataset;
  var socket = null;
  var tries = 0;
  var refreshTimer = null;
  var sound = null;

  function address() {
    return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + settings.liveUrl;
  }

  function ring() {
    if (settings.sound !== "1") return;
    try {
      if (!sound) {
        sound = new Audio(settings.soundUrl);
        sound.preload = "auto";
      }
      sound.currentTime = 0;
      var playing = sound.play();
      if (playing && playing.catch) playing.catch(function () {});   // (before the page was clicked: the browser says no)
    } catch (error) { /* (no sound: never mind) */ }
  }

  function notify(news) {
    if (settings.notify !== "1" || !window.Notification || Notification.permission !== "granted") return;
    if (document.visibilityState === "visible" && document.hasFocus()) return;   // (the page shows it already)
    var first = news.messages[0];
    var title = news.count > 1 ? news.count + " new messages" : first.from;
    var body = news.count > 1 ? first.from + ": " + first.subject : first.subject + (first.preview ? "\n" + first.preview : "");
    try {
      var note = new Notification(title, { body: body, icon: settings.iconUrl, tag: "someless-new-mail" });
      note.onclick = function () {
        window.focus();
        var inbox = document.querySelector('[data-wm-folders] .wm-folder[data-folder="inbox"] .wm-folder-link');
        if (inbox && wm.go) wm.go(inbox.href.replace(/\/mail\/inbox$/, "/mail/inbox/" + encodeURIComponent(first.id)));
        note.close();
      };
    } catch (error) { /* (a browser without them) */ }
  }

  // the list and the counts up to date (a moment after the last change: several come together)
  function refresh(soon) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () {
      if (wm.list) wm.list.refresh({ quiet: true }).catch(function () {});
    }, soon ? 150 : 600);
  }

  function connect() {
    try {
      socket = new WebSocket(address());
    } catch (error) {
      later();
      return;
    }
    socket.addEventListener("open", function () {
      if (tries) refresh(true);   // (back after a drop: what came meanwhile)
      tries = 0;
    });
    socket.addEventListener("message", function (event) {
      var news;
      try {
        news = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (news.type === "new") {
        ring();
        notify(news);
        refresh(true);
        document.dispatchEvent(new CustomEvent("wm:new-mail", { detail: news }));
      } else if (news.type === "changed") {
        refresh(false);
      }
    });
    socket.addEventListener("close", function (event) {
      socket = null;
      if (event.code === 1008) return;   // logged out: the next request goes to the login
      later();
    });
  }

  function later() {
    tries += 1;
    setTimeout(connect, Math.min(30000, 1000 * Math.pow(2, Math.min(tries, 5))));
  }

  // back to the tab after a while (a laptop woken up): brought up to date
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") return;
    if (!socket || socket.readyState > 1) {
      tries = 0;
      connect();
    }
    refresh(true);
  });

  // the preferences, as Settings changes them (webmail-settings.js)
  window.wm.live = {
    set: function (name, on) {
      if (name === "sound") settings.sound = on ? "1" : "0";
      if (name === "notify") settings.notify = on ? "1" : "0";
    },
    ring: ring,
  };
  connect();
})();

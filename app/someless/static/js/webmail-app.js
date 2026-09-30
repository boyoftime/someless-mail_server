// The webmail (webmail-mail.html): the account card under the round initial at the top right
// (it opens and closes with a click; Escape or a click anywhere else closes it), and on narrow
// screens the folders, which slide in from the left and back.
(function () {
  var toggle = document.querySelector("[data-wm-account]");
  var card = document.getElementById("wm-account");
  if (toggle && card) {
    var setOpen = function (open) {
      card.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: {} }));
    };
    toggle.addEventListener("click", function () {
      setOpen(card.hidden);
      if (!card.hidden) countUnread();
    });
    document.addEventListener("click", function (event) {
      if (!card.hidden && !card.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || card.hidden) return;
      setOpen(false);
      toggle.focus();
    });

    // The accounts on the card (webmail/accounts.py). Each one's unread mail, asked for as the
    // card opens (at most every half a minute).
    var accountsBox = card.querySelector("[data-wm-accounts]");
    var counted = 0;
    var countUnread = function () {
      if (!accountsBox || !window.wm || Date.now() - counted < 30000) return;
      counted = Date.now();
      wm.request(accountsBox.dataset.unreadUrl, { quiet: true }).then(function (counts) {
        accountsBox.querySelectorAll("[data-wm-switch]").forEach(function (link) {
          var badge = link.querySelector("[data-wm-unread]");
          var count = counts[link.dataset.id] || 0;
          badge.textContent = count > 999 ? "999+" : String(count);
          badge.hidden = !count;
        });
      }, function () {});
    };
    // Another tapped: "Switching to …" over the page with the turning arrows, then its mail, in this tab
    card.addEventListener("click", function (event) {
      var link = event.target.closest("[data-wm-switch]");
      if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;   // (a new tab: as it is)
      event.preventDefault();
      if (link.classList.contains("is-active")) {
        setOpen(false);
        return;
      }
      setOpen(false);
      var veil = document.createElement("div");
      veil.className = "wm-switching";
      document.body.appendChild(veil);
      if (window.wm) wm.loading(veil, true, { label: "Switching to " + link.dataset.email + "…" });
      requestAnimationFrame(function () { veil.classList.add("is-in"); });
      setTimeout(function () { location.assign(link.href); }, window.wm && wm.reduceMotion ? 0 : 450);
    });
    // One taken off the list (asked first); it stays a mailbox, only not at hand here
    card.addEventListener("click", function (event) {
      var button = event.target.closest("[data-wm-remove-account]");
      if (!button || !window.wm) return;
      event.preventDefault();
      wm.confirm({ title: "Take " + button.dataset.email + " off this list?",
                   text: "It stays a mailbox, with its mail. To switch to it here again, add it again with its password.",
                   yes: "Take off", no: "Cancel", danger: true }).then(function (yes) {
        if (!yes) return;
        wm.request(button.dataset.url, { method: "POST", body: {}, failTitle: "Couldn't take it off the list" }).then(function (answer) {
          if (answer.url) {
            location.assign(answer.url);
            return;
          }
          button.closest(".wm-account-item").remove();
          wm.toast(answer.message);
        });
      });
    });
  }

  var menu = document.querySelector("[data-wm-menu]");
  var side = document.getElementById("wm-side");
  var scrim = document.querySelector("[data-wm-scrim]");
  if (menu && side && scrim) {
    var setSide = function (open) {
      side.classList.toggle("is-open", open);
      scrim.hidden = !open;
      menu.setAttribute("aria-expanded", String(open));
    };
    menu.addEventListener("click", function () { setSide(!side.classList.contains("is-open")); });
    scrim.addEventListener("click", function () { setSide(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && side.classList.contains("is-open")) setSide(false);
    });
    // (a page's own script closes it when something in it was chosen: a contact book, a day)
    document.addEventListener("wm:side-close", function () { setSide(false); });
  }
})();

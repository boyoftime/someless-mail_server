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
    toggle.addEventListener("click", function () { setOpen(card.hidden); });
    document.addEventListener("click", function (event) {
      if (!card.hidden && !card.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || card.hidden) return;
      setOpen(false);
      toggle.focus();
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

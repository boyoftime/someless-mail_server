// The back of a mailbox's Configuration details (mailboxes.html): the phone at the top right
// flashes and turns the card over, to how to set the mailbox up on a device, a tab each for
// Android, iPhone and Windows PC (the highlight glides between them; the arrow keys move too).
// Again, and it turns back. The iPhone tab asks the panel for a QR code, a link to the
// mailbox's configuration profile that works for an hour (mail_profile.py): a new one each
// time the dialog opens. The dialog always opens on the front.
(function () {
  var dialog = document.getElementById("config-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var turner = dialog.querySelector("[data-config-flip]");
  var front = dialog.querySelector('[data-config-face="details"]');
  var back = dialog.querySelector('[data-config-face="devices"]');
  var tabs = Array.from(dialog.querySelectorAll("[data-device-tab]"));
  var glider = back.querySelector(".dialog-tabs-glider");
  var code = dialog.querySelector("[data-device-qr]");
  var download = dialog.querySelector("[data-device-download]");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var mailbox = null;     // the button that opened the dialog: where its profile and link are
  var codeFor = null;     // the mailbox whose code is showing
  var turning = false;
  var phone = null;       // the animation, playing while the dialog is open

  function board(type, title, message) {
    if (window.somelessBoard) window.somelessBoard.show({ type: type, title: title, message: message });
  }

  function playPhone() {
    var holder = turner.querySelector("[data-config-lottie]");
    if (!window.lottie || !holder) return;
    if (phone) return reduceMotion || phone.play();
    phone = window.lottie.loadAnimation({ container: holder, renderer: "svg", loop: true, autoplay: !reduceMotion,
                                          path: holder.dataset.configLottie });
    phone.addEventListener("DOMLoaded", function () {
      holder.classList.add("is-playing");
      if (reduceMotion) phone.goToAndStop(Math.floor(phone.totalFrames / 2), true);
    });
  }
  dialog.addEventListener("close", function () { if (phone) phone.pause(); });

  // a change of what the dialog holds: it glides to its new height (smooth-size.js)
  function resize(change) {
    if (window.somelessResize && dialog.open) window.somelessResize(dialog, change);
    else change();
  }

  function place(atOnce) {
    var chosen = tabs.find(function (tab) { return tab.getAttribute("aria-selected") === "true"; });
    if (!chosen || !chosen.offsetWidth) return;
    glider.parentNode.classList.toggle("is-settling", !!atOnce || reduceMotion);
    glider.style.width = chosen.offsetWidth + "px";
    glider.style.transform = "translateX(" + chosen.offsetLeft + "px)";
  }

  function choose(tab, focus) {
    resize(function () {
      tabs.forEach(function (other) {
        var on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
        document.getElementById(other.getAttribute("aria-controls")).hidden = !on;
      });
    });
    if (focus) tab.focus();
    place();
    if (tab.id === "device-tab-iphone") makeCode();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () { choose(tab); });
    tab.addEventListener("keydown", function (event) {
      var step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      choose(tabs[(index + step + tabs.length) % tabs.length], true);
    });
  });

  // The QR code: a link to the profile, made for this mailbox now
  function makeCode() {
    if (!mailbox || codeFor === mailbox || !window.fetch) return;
    var asked = codeFor = mailbox;
    code.classList.remove("is-ready");
    code.innerHTML = '<span class="device-qr-wait" aria-hidden="true"></span>';
    fetch(mailbox.dataset.configLink, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("refused");
        return response.json();
      })
      .then(function (answer) {
        if (codeFor !== asked) return;   // another mailbox's dialog by now
        code.innerHTML = answer.qr;
        var picture = code.querySelector("svg");
        picture.setAttribute("role", "img");
        picture.setAttribute("aria-label", "A QR code for the iPhone's camera: a link to the profile");
        code.classList.add("is-ready");
      })
      .catch(function () {
        if (codeFor !== asked) return;
        codeFor = null;   // tried again when the tab opens again
        code.innerHTML = "";
        board("error", "Couldn't make the code", "The panel didn't answer. Check your connection and try again.");
      });
  }

  // Which side shows
  function show(side) {
    var toBack = side === "back";
    front.hidden = toBack;
    back.hidden = !toBack;
    var tip = toBack ? turner.dataset.tipBack : turner.dataset.tipFront;
    turner.setAttribute("aria-label", tip);
    turner.dataset.tip = tip;
    turner.classList.toggle("is-back", toBack);
    dialog.scrollTop = 0;
    if (!toBack) return;
    place(true);
    var chosen = tabs.find(function (tab) { return tab.getAttribute("aria-selected") === "true"; });
    if (chosen && chosen.id === "device-tab-iphone") makeCode();
  }

  function flash() {
    turner.classList.remove("is-flashing");
    void turner.offsetWidth;   // again from the start, on a quick second click
    turner.classList.add("is-flashing");
    clearTimeout(turner.flashTimer);
    turner.flashTimer = setTimeout(function () { turner.classList.remove("is-flashing"); }, 600);
  }

  // The card turns until it's edge-on, the other side comes round, and it turns back to face
  // the admin (its height changes while it's edge-on, out of sight)
  function turn() {
    if (turning) return;
    var toBack = back.hidden;
    flash();
    document.dispatchEvent(new Event("someless:tips-away"));   // its tip is about the other side
    if (reduceMotion || !dialog.animate) return show(toBack ? "back" : "front");
    turning = true;
    var way = toBack ? 1 : -1;
    var away = dialog.animate([
      { transform: "perspective(1600px) rotateY(0deg)" },
      { transform: "perspective(1600px) rotateY(" + 90 * way + "deg)" },
    ], { duration: 200, easing: "cubic-bezier(0.5, 0, 0.75, 0)", fill: "forwards" });
    away.onfinish = function () {
      show(toBack ? "back" : "front");
      var round = dialog.animate([
        { transform: "perspective(1600px) rotateY(" + -90 * way + "deg)" },
        { transform: "perspective(1600px) rotateY(0deg)" },
      ], { duration: 440, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
      away.cancel();
      round.onfinish = round.oncancel = function () { turning = false; };
    };
  }
  turner.addEventListener("click", turn);

  // Opening: on the front, for the mailbox whose button was pressed (mailboxes-page.js fills
  // in its address)
  document.querySelectorAll("[data-config-email]").forEach(function (button) {
    button.addEventListener("click", function () {
      mailbox = button;
      codeFor = null;   // a new link each time: the last one may have run out
      code.innerHTML = "";
      download.href = button.dataset.configProfile;
      show("front");
      playPhone();
    });
  });
})();

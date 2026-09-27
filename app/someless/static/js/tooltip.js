// Tips: a word of help beside something (the ? next to a domain's status), in a small card in
// the panel's own look instead of the browser's plain tooltip. Any element with data-tip shows
// it on hover (a tap on a phone too, where it stays while the element has focus), and on the
// keyboard's focus: not when a dialog opened with the mouse focuses its first button. The card
// sits on the page itself, above the element (below it when there's no room), so a table that
// clips its rows can't cut it off; in a dialog that's moving (opening, turning over), it waits
// until the dialog is still. The pointer can move onto the card to read it; moving away,
// Escape, scrolling or leaving the page puts it away. So does a "someless:tips-away" event
// (detail.element: the element whose tip it was, which then stays quiet until the pointer
// leaves it).
(function () {
  var GAP = 10;   // between the element and the card
  var EDGE = 12;  // the least room kept between the card and the window's edges
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("aria-hidden", "true"); // the element's own label says it to screen readers
  document.body.appendChild(tip);
  var shownFor = null;
  var hideTimer = null;
  var waitingFor = null;  // wanted while its dialog moves: shown once it's still, if still wanted
  var restingOn = null;   // its tip was put away (someless:tips-away): quiet until the pointer leaves it

  // the open dialog it's in (showModal), or the page: anything outside an open dialog sits under it
  function home(element) {
    var dialog = element.closest("dialog[open]");
    try {
      return dialog && dialog.matches(":modal") ? dialog : document.body;
    } catch (error) {
      return document.body; // a browser without :modal
    }
  }

  // what's moving the dialog (or the page) right now
  function moving(host) {
    return host.getAnimations ? host.getAnimations().filter(function (animation) {
      return animation.playState === "running";
    }) : [];
  }

  function show(element) {
    clearTimeout(hideTimer);
    if (shownFor === element || element === restingOn) return;
    var host = home(element);
    // where the card would land in a moving dialog isn't where it'll stay: wait until it's still
    var running = moving(host);
    if (running.length) {
      waitingFor = element;
      Promise.all(running.map(function (animation) {
        return animation.finished.catch(function () {});   // stopped short counts as done
      })).then(function () {
        if (waitingFor !== element) return;
        waitingFor = null;
        var wanted = element.matches(":hover") || (element === document.activeElement && byKeyboard(element));
        if (element.isConnected && wanted) show(element);   // it may still be moving: then it waits again
      });
      return;
    }
    shownFor = element;
    if (tip.parentNode !== host) host.appendChild(tip);
    tip.textContent = element.getAttribute("data-tip");
    tip.classList.toggle("is-long", tip.textContent.length > 160);
    tip.classList.remove("is-shown");
    tip.style.left = "0px";
    tip.style.top = "0px";
    var box = element.getBoundingClientRect();
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    var below = box.top - GAP - height < EDGE;
    var middle = box.left + box.width / 2;
    var left = Math.max(EDGE, Math.min(middle - width / 2, window.innerWidth - width - EDGE));
    // where 0, 0 lands (the window, unless something around it moves it, like an opening dialog)
    var origin = tip.getBoundingClientRect();
    tip.style.left = left - origin.left + "px";
    tip.style.top = (below ? box.bottom + GAP : box.top - GAP - height) - origin.top + "px";
    tip.style.setProperty("--arrow-x", Math.max(16, Math.min(middle - left, width - 16)) + "px");
    tip.setAttribute("data-side", below ? "below" : "above");
    void tip.offsetWidth; // fade in from where it now is
    tip.classList.add("is-shown");
  }

  // the pointer has left the quiet element, the dialog being still (turning over moves the
  // element from under the pointer, and back): its tip can show again
  function wakeIfLeft(target) {
    if (restingOn && !restingOn.contains(target) && !moving(home(restingOn)).length) restingOn = null;
  }

  // focus from the keyboard, not from a click or a script after one
  function byKeyboard(element) {
    try {
      return element.matches(":focus-visible");
    } catch (error) {
      return true; // a browser without :focus-visible
    }
  }

  function hide(soon) {
    clearTimeout(hideTimer);
    waitingFor = null;
    if (!shownFor) return;
    hideTimer = setTimeout(function () {
      shownFor = null;
      tip.classList.remove("is-shown");
    }, soon ? 140 : 0);
  }

  document.addEventListener("pointerover", function (event) {
    if (tip.contains(event.target)) return clearTimeout(hideTimer);
    wakeIfLeft(event.target);
    var element = event.target.closest("[data-tip]");
    if (element) show(element);
  });
  document.addEventListener("pointerout", function (event) {
    var from = event.target.closest("[data-tip]") || (tip.contains(event.target) ? tip : null);
    if (!from || (event.relatedTarget && (from.contains(event.relatedTarget) || tip.contains(event.relatedTarget)))) return;
    if (from === restingOn) wakeIfLeft(event.relatedTarget || document.documentElement);
    if (from === tip || from === shownFor) {
      if (shownFor && shownFor === document.activeElement) return; // focused: stays until it loses focus
      hide(true);
    }
  });
  document.addEventListener("focusin", function (event) {
    var element = event.target.closest && event.target.closest("[data-tip]");
    if (element && byKeyboard(event.target)) show(element);
  });
  document.addEventListener("focusout", function (event) {
    if (event.target === shownFor) hide(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && shownFor) hide(false);
  });
  window.addEventListener("scroll", function () { hide(false); }, { passive: true });
  window.addEventListener("resize", function () { hide(false); });
  document.addEventListener("someless:navigate", function () { hide(false); });
  // what it was for changes on the spot (a card turning over: config-devices.js)
  document.addEventListener("someless:tips-away", function (event) {
    restingOn = (event.detail && event.detail.element) || shownFor;
    clearTimeout(hideTimer);
    waitingFor = null;
    shownFor = null;
    tip.style.transition = "none";   // gone at once: fading, it would turn over with the card
    tip.classList.remove("is-shown");
    void tip.offsetWidth;
    tip.style.transition = "";
  });
})();

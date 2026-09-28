// The webmail's list of mail (webmail-mail.html): it opens with the newest 50 messages, and when
// it's scrolled to within a screen or so of its end, the next 50 come in below (webmail.py
// /messages), until there are no more. "Loading more mail…" shows at the end while they're on
// their way. When they can't come, the notice board says so, and scrolling down tries again a
// few seconds later. A session that ended (the password changed) goes back to the login.
(function () {
  var scroll = document.querySelector("[data-wm-scroll]");
  var list = document.querySelector("[data-wm-messages]");
  var more = document.querySelector("[data-wm-more]");
  if (!scroll || !list || !more || !window.fetch) return;
  var NEAR = 700;        // px from the end: the next mail is asked for before it's reached
  var WAIT_AFTER = 5000; // ms before trying again after a failure
  var loading = false;
  var triedAt = 0;       // the last failure
  var queued = false;

  function board(type, title, message) {
    if (window.somelessBoard) window.somelessBoard.show({ type: type, title: title, message: message });
  }

  function near() {
    return scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - NEAR;
  }

  function load() {
    if (loading || !more || Date.now() - triedAt < WAIT_AFTER) return;
    loading = true;
    more.hidden = false;
    fetch(more.dataset.url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (response.redirected) {   // logged out meanwhile: the login page
          location.href = response.url;
          return null;
        }
        if (!response.ok) throw new Error("refused");
        return response.json();
      })
      .then(function (answer) {
        if (!answer) return;
        list.insertAdjacentHTML("beforeend", answer.html);
        list.dispatchEvent(new CustomEvent("someless:rows"));   // (the open message may be among them: webmail-read.js)
        loading = false;
        if (answer.next) {
          more.dataset.url = answer.next;
          check();   // a tall screen can still be near the end
        } else {
          more.remove();   // all of it is here
          more = null;
          scroll.removeEventListener("scroll", onScroll);
        }
      })
      .catch(function () {
        loading = false;
        triedAt = Date.now();
        more.hidden = true;   // back when it's tried again
        board("error", "Couldn't load more mail", "The webmail didn't answer. Check your connection, then scroll down again.");
      });
  }

  function check() {
    queued = false;
    if (near()) load();
  }

  function onScroll() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(check);
  }

  scroll.addEventListener("scroll", onScroll, { passive: true });
  check();   // a screen taller than the first 50
})();

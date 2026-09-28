// The webmail's reading pane (webmail-mail.html, webmail-read.html): a message in the list opens
// here without a new page, and the address bar gets its own link (/message/<id>), so a refresh,
// the Back button or a shared link opens it again. Its row is picked out and ticked, as the
// webmails do, and loses its bold once it's open: it's read (webmail.py counts the Inbox again).
// What the message says is a page of its own in a frame, where no script runs: it's made as tall
// as the message, in the webmail's colours, or in its own light ones on white (the sun, in the
// dark theme). The arrow opens its attachments out. On narrow screens a message takes the list's
// place, with a way back to the list.
(function () {
  var reader = document.querySelector("[data-wm-reader]");
  var list = document.querySelector("[data-wm-messages]");
  if (!reader || !list || !window.fetch) return;
  var empty = reader.querySelector("[data-wm-empty]");
  var view = reader.querySelector("[data-wm-view]");
  var unread = document.querySelector("[data-wm-unread]");
  var openId = view.dataset.open || null;   // opened by its link: the page came with it
  var asking = null;                        // the message on its way
  var watching = null;                      // the frame's size

  function board(type, title, message) {
    if (window.somelessBoard) window.somelessBoard.show({ type: type, title: title, message: message });
  }

  function rowFor(id) {
    return id ? list.querySelector('.wm-message[data-id="' + CSS.escape(id) + '"]') : null;
  }

  // The open message's row: picked out and ticked; the one before goes back to how it was
  function pickOut(id) {
    list.querySelectorAll(".wm-message.is-open").forEach(function (row) {
      row.classList.remove("is-open");
      row.querySelector(".wm-message-link").removeAttribute("aria-current");
      var box = row.querySelector("input[type=checkbox]");
      if (box.hasAttribute("data-auto")) {
        box.checked = false;
        box.removeAttribute("data-auto");
      }
    });
    var row = rowFor(id);
    if (!row) return;
    row.classList.add("is-open");
    row.querySelector(".wm-message-link").setAttribute("aria-current", "true");
    var box = row.querySelector("input[type=checkbox]");
    if (!box.checked) {
      box.checked = true;
      box.setAttribute("data-auto", "");
    }
  }
  // The open message's row, brought into sight in the list when it's out of it (opened by its
  // link, or by Back and Forward): in the middle, the way the list scrolls, never the page
  function reveal(id) {
    var row = rowFor(id);
    var scroller = list.closest("[data-wm-scroll]");
    if (!row || !scroller || !scroller.clientHeight) return;
    var place = row.getBoundingClientRect();
    var box = scroller.getBoundingClientRect();
    if (place.top >= box.top && place.bottom <= box.bottom) return;   // in sight already
    scroller.scrollTop += place.top - box.top - (box.height - place.height) / 2;
  }

  // ticked or unticked by hand: it stays that way when another message opens
  list.addEventListener("change", function (event) { event.target.removeAttribute("data-auto"); });
  // more of the list came in (webmail-list.js): the open message may be in it
  list.addEventListener("someless:rows", function () { pickOut(openId); });

  // What the message says: in the webmail's colours (or its own on white), as tall as it is
  function frame() {
    return view.querySelector("[data-wm-body]");
  }

  function page() {   // the message's page, once it's there (not the empty one before it)
    var body = frame();
    var doc = body && body.contentDocument;
    return doc && doc.URL === "about:srcdoc" && doc.body ? doc : null;
  }

  function fit() {
    var doc = page();
    if (doc) frame().style.height = Math.ceil(doc.documentElement.getBoundingClientRect().height) + "px";
  }

  function colours() {
    var doc = page();
    if (!doc) return;
    var dark = document.documentElement.dataset.theme === "dark";
    var paper = dark && !!view.querySelector("[data-wm-paper][aria-pressed='true']");
    doc.documentElement.classList.toggle("is-dark", dark);
    doc.documentElement.classList.toggle("is-light", !dark);
    doc.documentElement.classList.toggle("is-paper", paper);
    fit();
  }
  document.addEventListener("someless:theme", colours);

  function setUp() {
    var body = frame();
    if (!body) return;
    function ready() {
      var doc = page();
      if (!doc) return;
      colours();
      if (doc.fonts) doc.fonts.ready.then(fit);   // its font can make it taller
    }
    body.addEventListener("load", ready);
    ready();   // there already
    if (watching) watching.disconnect();
    if (window.ResizeObserver) {   // narrower or wider: taller or shorter
      watching = new ResizeObserver(fit);
      watching.observe(body);
    }
  }

  // Opening and closing
  function setUnread(count) {
    if (!unread || typeof count !== "number") return;
    unread.textContent = count;
    unread.hidden = count === 0;
  }

  function show(html, id, subject) {
    view.innerHTML = html;
    view.hidden = false;
    empty.hidden = true;
    view.dataset.open = id;
    openId = id;
    document.body.classList.add("is-reading");
    document.title = subject + " | Someless Webmail";
    pickOut(id);
    var row = rowFor(id);
    if (row) row.classList.remove("is-unread");   // read now
    setUp();
  }

  function close() {
    if (asking) asking.abort();
    asking = null;
    view.innerHTML = "";
    view.hidden = true;
    empty.hidden = false;
    delete view.dataset.open;
    openId = null;
    document.body.classList.remove("is-reading");
    document.title = "Inbox | Someless Webmail";
    pickOut(null);
  }

  function open(url, id, remember) {
    if (asking) asking.abort();
    var ask = asking = new AbortController();
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" }, signal: ask.signal })
      .then(function (response) {
        if (response.redirected) {   // logged out meanwhile: the login page
          location.href = response.url;
          return null;
        }
        if (!response.ok) throw new Error("refused");
        return response.json();
      })
      .then(function (answer) {
        if (!answer || asking !== ask) return;
        asking = null;
        show(answer.html, id, answer.subject);
        setUnread(answer.unread);
        if (remember) history.pushState({ wmMessage: id }, "", url);
        else reveal(id);   // Back or Forward: its row may be out of sight
      })
      .catch(function (error) {
        if (error.name === "AbortError") return;   // another message was picked meanwhile
        asking = null;
        pickOut(openId);   // back to the one that's open
        board("error", "Couldn't open the message", "The webmail didn't answer. Check your connection and try again.");
      });
  }

  list.addEventListener("click", function (event) {
    var link = event.target.closest(".wm-message-link");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();   // (with a key held: a new tab, as links do)
    var id = link.closest(".wm-message").dataset.id;
    if (id === openId && !asking) return;   // open already
    pickOut(id);   // at once, while it comes
    open(link.href, id, true);
  });

  // Back and Forward: the message the address bar has, or none
  window.addEventListener("popstate", function () {
    var match = location.pathname.match(/\/message\/([^/]+)$/);
    if (match) open(location.href, decodeURIComponent(match[1]), false);
    else close();
  });

  // In the pane: back to the list (narrow screens), the attachments, the message's own colours
  reader.addEventListener("click", function (event) {
    if (event.target.closest("[data-wm-back]")) {
      close();
      history.pushState(null, "", reader.dataset.home);
      return;
    }
    var button = event.target.closest("[data-wm-files-toggle], [data-wm-paper]");
    if (!button) return;
    var on;
    if (button.hasAttribute("data-wm-files-toggle")) {
      on = button.closest("[data-wm-files]").classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(on));
    } else {
      on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      colours();
    }
    // its tip says what a click does now; the old one goes (tooltip.js)
    var tip = on ? button.dataset.tipOn : button.dataset.tipOff;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
  });

  if (openId) {   // the page came with it open (its link, a refresh)
    setUp();
    reveal(openId);
  }
})();

// Going from folder to folder in the webmail (webmail-mail.html) without a new page, as in
// PrivateEmail: the folder's page is fetched, and its list, its reading pane and the folders
// are put in place of the ones shown, so the messages being written (webmail-compose.js) stay
// open, and nothing flashes. The address bar follows (Back and Forward too). A page that isn't
// the mail (the engine out of reach, logged out) opens as a page of its own.
(function () {
  var shell = document.querySelector("[data-wm-shell]");
  var nav = document.querySelector("[data-wm-folders]");
  var section = document.querySelector("[data-wm-list]");
  if (!shell || !nav || !section || !window.wm || !window.fetch || !window.DOMParser) return;
  var asking = null;

  function ours(url) {
    return url.origin === location.origin && /^\/(mail\/[^/]+(\/[^/]+)?|search)$/.test(url.pathname);
  }

  // the folder a /mail/ address is about ("search" for the results), and the message, if any
  function parts(url) {
    var match = /^\/mail\/([^/]+)(?:\/([^/]+))?$/.exec(url.pathname);
    if (match) return { folder: decodeURIComponent(match[1]), message: match[2] ? decodeURIComponent(match[2]) : null };
    return { folder: "search", message: null };
  }

  function go(href, push) {
    var url = new URL(href, location.href);
    if (!ours(url)) {
      location.href = href;
      return;
    }
    if (asking) asking.abort();
    var ask = asking = new AbortController();
    section.classList.add("is-loading");
    document.body.classList.add("is-going");
    fetch(url.href, { credentials: "same-origin", headers: { Accept: "text/html" }, signal: ask.signal })
      .then(function (response) {
        if (response.redirected && !ours(new URL(response.url))) {
          location.href = response.url;   // logged out meanwhile: the login page
          return null;
        }
        return response.text().then(function (text) { return { ok: response.ok, text: text }; });
      })
      .then(function (got) {
        if (!got || asking !== ask) return;
        asking = null;
        var page = new DOMParser().parseFromString(got.text, "text/html");
        if (!got.ok || !page.querySelector("[data-wm-list]")) {
          location.href = url.href;   // (the mail out of reach: its own page says so)
          return;
        }
        adopt(page);
        if (push) history.pushState({ wmPage: true }, "", url.pathname + url.search);
      })
      .catch(function (error) {
        if (error.name === "AbortError") return;
        asking = null;
        wm.board("Couldn't open the folder", "The webmail didn't answer. Check your connection and try again.");
      })
      .then(function () {
        if (asking) return;
        section.classList.remove("is-loading");
        document.body.classList.remove("is-going");
      });
  }

  // the new page's list, reading pane and folders, in place of these
  function adopt(page) {
    var token = page.querySelector('meta[name="csrf-token"]');
    var mine = document.querySelector('meta[name="csrf-token"]');
    if (token && mine) mine.content = token.content;
    var nextNav = page.querySelector("[data-wm-folders]");
    nav.innerHTML = nextNav.innerHTML;
    nav.dataset.current = nextNav.dataset.current;
    nav.dataset.byName = nextNav.dataset.byName;
    var storage = document.querySelector(".wm-storage");
    var nextStorage = page.querySelector(".wm-storage");
    if (storage && nextStorage) storage.replaceWith(document.importNode(nextStorage, true));
    var search = document.querySelector("[data-wm-search]");
    var nextSearch = page.querySelector("[data-wm-search]");
    if (search && nextSearch) {
      search.dataset.folder = nextSearch.dataset.folder;
      search.dataset.folderName = nextSearch.dataset.folderName;
      search.querySelector("#wm-search").value = nextSearch.querySelector("#wm-search").value;
      search.querySelector("[data-wm-search-scope]").value = nextSearch.querySelector("[data-wm-search-scope]").value;
    }
    if (wm.list && wm.list.adopt) wm.list.adopt(page);
    if (wm.reader && wm.reader.adopt) wm.reader.adopt(page);
    document.body.classList.toggle("is-reading", page.body.classList.contains("is-reading"));
    wm.setTitle(page.title.replace(/^\(\d+\)\s*/, ""));
    var side = document.getElementById("wm-side");
    if (side && side.classList.contains("is-open")) document.querySelector("[data-wm-menu]").click();   // (a phone: the drawer closes)
    document.dispatchEvent(new CustomEvent("wm:navigated", { detail: { page: page } }));
  }

  // links to folders and to results: in place
  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    var link = event.target.closest("a[href]");
    if (!link || link.target || link.hasAttribute("download")) return;
    if (!link.matches(".wm-folder-link, .wm-logo, [data-wm-all-results], [data-wm-result], .wm-app.is-current")) return;
    var url = new URL(link.href, location.href);
    if (!ours(url)) return;
    event.preventDefault();
    go(url.href, true);
  });

  // Back and Forward: a message of this folder opens (or closes) in the pane; another folder comes in
  window.addEventListener("popstate", function () {
    var url = new URL(location.href);
    if (!ours(url)) return;
    var here = parts(url);
    var same = here.folder === section.dataset.folder && here.folder !== "search";
    if (same && here.message && wm.reader) wm.reader.open(url.href, here.message, false);
    else if (same && !here.message && wm.reader) wm.reader.close();
    else go(url.href, false);
  });

  window.wm.go = function (href) { go(href, true); };
})();

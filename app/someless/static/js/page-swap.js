// The signed-in pages change without reloading the whole page: only the main area is
// swapped. A click on a link, or a form sent from the main area, fetches the next page in
// the background and puts its main area in place of this one. The side menu, the top bar
// and their animations stay exactly as they are. The address bar, the tab title and the
// Back and Forward buttons work as usual. Meanwhile the loading bar runs and the loader
// covers the main area (loading-bar.js, page-loader.js). A form that brings back the page
// it was sent from (an error, or a save) leaves the page just as it was: what was typed,
// open cards, the place on the screen. The message comes down on the notice board.
// Anything that isn't a signed-in page (the login page once the session has ended, say)
// loads the normal way. Links marked data-full-load always do.
(function () {
  var main = document.getElementById("app-main");
  if (!main || !window.fetch || !window.DOMParser || !window.AbortController) return;
  var MIN_LOADER_MS = 350; // long enough for the loader to be seen rather than flicker
  var loading = null; // the page on its way: { controller, form }
  var shownUrl = withoutHash(location.href); // the page in the main area now
  var scrollTimer = null;

  // Each history entry remembers how far down its page was scrolled, for Back and Forward.
  history.scrollRestoration = "manual";

  function withoutHash(href) {
    var url = new URL(href, location.href);
    url.hash = "";
    return url.href;
  }

  function rememberScroll() {
    clearTimeout(scrollTimer);
    history.replaceState(Object.assign({}, history.state, { scroll: window.scrollY }), "");
  }

  window.addEventListener("scroll", function () {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(rememberScroll, 200);
  }, { passive: true });

  function linkFor(event) {
    if (event.defaultPrevented || event.button !== 0) return null;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
    var link = event.target.closest("a[href]");
    if (!link || link.hasAttribute("download") || link.hasAttribute("data-full-load")) return null;
    if (link.target && link.target !== "_self") return null;
    if (link.origin !== location.origin || link.pathname.indexOf("/static/") === 0) return null;
    if (link.hash && withoutHash(link.href) === shownUrl) return null; // a jump within the page
    return link;
  }

  document.addEventListener("click", function (event) {
    var link = linkFor(event);
    if (!link) return;
    event.preventDefault();
    rememberScroll();
    go(link.href, "GET", null, null, null);
  });

  // Forms in the main area (the settings forms). The loading bar has started already.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !main.contains(form) || form.hasAttribute("data-full-load")) return;
    event.preventDefault();
    if (loading && loading.form === form) return; // already on its way (a double click)
    rememberScroll();
    var method = (form.getAttribute("method") || "GET").toUpperCase();
    var data = new FormData(form, event.submitter);
    if (method === "GET") {
      var url = new URL(form.action);
      url.search = new URLSearchParams(data).toString();
      go(url.href, "GET", null, form, null);
    } else {
      go(form.action, method, data, form, null);
    }
  });

  // Back and Forward: the address bar already shows the page to bring in.
  window.addEventListener("popstate", function (event) {
    clearTimeout(scrollTimer); // it would note the old page's scroll on the new entry
    if (withoutHash(location.href) === shownUrl) return; // only the #part changed
    if (window.somelessLoadingBar) window.somelessLoadingBar.start(); // shows the loader too
    go(location.href, "GET", null, null, event.state || {});
  });

  // `revisit` is the history entry's state on Back and Forward (null otherwise).
  function go(url, method, body, form, revisit) {
    if (loading) loading.controller.abort();
    var controller = new AbortController();
    loading = { controller: controller, form: form };
    var started = Date.now();

    fetch(url, {
      method: method,
      body: body,
      credentials: "same-origin",
      headers: { Accept: "text/html" },
      signal: controller.signal,
    })
      .then(function (response) {
        return response.text().then(function (html) {
          var wait = Math.max(0, MIN_LOADER_MS - (Date.now() - started));
          return new Promise(function (resolve) {
            setTimeout(function () { resolve({ response: response, html: html }); }, wait);
          });
        });
      })
      .then(function (result) {
        if (controller.signal.aborted) return;
        loading = null;
        var response = result.response;
        // A form's answer can't be asked for again: if it can't be shown here, show the page
        // the form was sent from (after a logout elsewhere, that turns out to be the login page).
        var again = method === "GET" || response.redirected ? response.url : location.href;
        var doc = new DOMParser().parseFromString(result.html, "text/html");
        var newMain = doc.getElementById("app-main");
        var isPage = (response.headers.get("Content-Type") || "").indexOf("text/html") === 0;
        if (!newMain || !isPage) {
          window.location.assign(again); // not a signed-in page: load it the normal way
          return;
        }
        // A form's answer without a redirect (an error) is still the page it was sent from.
        var moved = method === "GET" || response.redirected;
        var pageChanged = moved && withoutHash(response.url) !== shownUrl;
        if (!revisit && moved) {
          // As the browser does it: a new page adds a history entry, the same page again doesn't.
          if (pageChanged) history.pushState({}, "", response.url);
          else history.replaceState({}, "", response.url);
        }
        if (moved) shownUrl = withoutHash(response.url);
        // A form that brings back the page it was sent from, with an error or after going
        // through: everything stays as it was left (a long password can be corrected instead
        // of typed again), except the form itself once it went through.
        var kept = form && method !== "GET" && !pageChanged ? keep(form, response.redirected) : null;
        var stayed = false;
        try {
          stayed = swap(doc, newMain, pageChanged, kept);
        } catch (error) {
          console.error(error);
          window.location.assign(again); // something went wrong swapping: load it for real
          return;
        }
        if (!stayed) {
          window.scrollTo(0, revisit && revisit.scroll ? revisit.scroll : 0);
          focusHeading();
        }
      })
      .catch(function (error) {
        // a newer page is on its way, so this one doesn't matter any more
        if (error.name === "AbortError" || (loading !== null && loading.controller !== controller)) return;
        loading = null;
        if (revisit) {
          window.location.reload(); // the address bar has moved on already: load it for real
          return;
        }
        done();
        if (form) form.dispatchEvent(new Event("someless:done")); // its button stops spinning
        if (window.somelessMenu) window.somelessMenu.restore();
        if (window.somelessBoard) {
          window.somelessBoard.show({
            type: "error",
            title: "Couldn't load the page",
            message: "Can't reach the server. Check your connection and try again.",
          });
        }
      });
  }

  // Returns true if the form in `kept` came back and was put back as it was left.
  function swap(doc, newMain, pageChanged, kept) {
    // Filled in and its cards opened before it goes in, so nothing animates or moves. The
    // focus leaves the old form first: taking out a focused field makes the browser lay the
    // page out while the main area is empty, and the scroll jumps to the top.
    var form = kept ? putBack(kept, newMain) : null;
    // A switch's form can come back as a different form (on becomes off): then the card it
    // sits in is what stays in place.
    var card = kept && kept.card ? newMain.querySelector("[data-card][aria-labelledby='" + kept.card + "']") : null;
    if ((form || card) && main.contains(document.activeElement)) document.activeElement.blur();
    document.title = doc.title;
    main.className = newMain.className;
    main.replaceChildren.apply(main, Array.from(document.adoptNode(newMain).childNodes));

    // A few things outside the main area show what the page knows (the admin's name).
    document.querySelectorAll("[data-swap-refresh][id]").forEach(function (el) {
      var fresh = doc.getElementById(el.id);
      if (fresh) el.replaceWith(document.adoptNode(fresh));
    });

    // The menu lights up the new page's row, and shows the account options for Settings.
    var row = doc.querySelector("#side-menu a.side-menu-item[aria-current='page']");
    if (window.somelessMenu) window.somelessMenu.setCurrent(row ? row.getAttribute("href") : null);
    if (pageChanged && row && row.closest("#account-panel") && window.somelessAccountPanel) {
      window.somelessAccountPanel.open();
    }

    // Scripts that came in with the page don't run by themselves: put in fresh copies.
    main.querySelectorAll("script").forEach(function (old) {
      var script = document.createElement("script");
      Array.from(old.attributes).forEach(function (attr) { script.setAttribute(attr.name, attr.value); });
      script.text = old.text;
      script.async = false; // one after another, as on a normal page load
      old.replaceWith(script);
    });

    if (window.somelessBoard) window.somelessBoard.fromPage(main);
    document.dispatchEvent(new CustomEvent("someless:swap", { detail: { main: main } }));
    done();
    if (!form && !card) {
      // An error page came back: shown like a new page. A form that went through and was
      // sent back to the same page (a deleted row's) keeps the place on the screen.
      if (!kept || !kept.wentThrough) return false;
      window.scrollTo(0, kept.scrollY);
      focusHeading();
      return true;
    }

    // Everything stays at the same place on the screen, with the focus where it was.
    if (form && kept.top !== null && visible(form)) window.scrollBy(0, form.getBoundingClientRect().top - kept.top);
    else if (card && kept.cardTop !== null) window.scrollBy(0, card.getBoundingClientRect().top - kept.cardTop);
    else window.scrollTo(0, kept.scrollY);
    focusAgain(kept, form, card);
    reveal();
    return true;
  }

  // Something new the page wants seen (data-swap-reveal, like the QR code once the PIN is
  // switched on): glide down just enough to show it.
  function reveal() {
    var target = main.querySelector("[data-swap-reveal]");
    if (!target || !visible(target)) return;
    var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(function () {
      target.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "nearest" });
    });
  }

  // The main area as the admin left it: what was typed in each form (the server never
  // sends that back, least of all passwords), except in the form that just went through;
  // the open cards; the focus; where the sent form sits on the screen.
  function keep(sent, wentThrough) {
    var sentCard = sent.closest("[data-card]");
    return {
      forms: Array.from(main.querySelectorAll("form")).filter(function (form) {
        return !(wentThrough && form === sent); // that one starts afresh
      }).map(function (form) {
        return {
          action: form.getAttribute("action"),
          fields: Array.from(form.elements).filter(typedIn).map(function (field) {
            return { name: field.name, value: field.value, checked: field.checked };
          }),
        };
      }),
      sent: sent.getAttribute("action"),
      wentThrough: wentThrough,
      openCards: Array.from(main.querySelectorAll("[data-card-toggle][aria-expanded='true']")).map(function (toggle) {
        return toggle.getAttribute("aria-controls");
      }),
      focus: wentThrough ? "" : focusIn(sent),
      top: visible(sent) ? sent.getBoundingClientRect().top : null,
      label: sent.querySelector("[type=submit][aria-label]") ? sent.querySelector("[type=submit][aria-label]").getAttribute("aria-label") : "",
      card: sentCard ? sentCard.getAttribute("aria-labelledby") : null,
      cardTop: sentCard ? sentCard.getBoundingClientRect().top : null,
      scrollY: window.scrollY,
    };
  }

  function typedIn(field) {
    return field.name && ["hidden", "submit", "button", "reset", "file"].indexOf(field.type) === -1;
  }

  function visible(el) {
    return el.getClientRects().length > 0;
  }

  function formIn(root, action) {
    return Array.from(root.querySelectorAll("form")).find(function (form) {
      return form.getAttribute("action") === action;
    });
  }

  // The field that has the focus, or "submit" when it was on the send button (locked while
  // sending, it may have lost it); "" when the focus has gone elsewhere.
  function focusIn(form) {
    var active = document.activeElement;
    if (active && form.contains(active) && active.id) return active.id;
    return !active || active === document.body || form.contains(active) ? "submit" : "";
  }

  // The page that came back, before it goes in: fill the forms in again and reopen the
  // cards. Returns the sent form, or nothing if something else came back (an error page).
  function putBack(kept, newMain) {
    kept.forms.forEach(function (saved) {
      var form = formIn(newMain, saved.action);
      if (!form) return;
      Array.from(form.elements).filter(typedIn).forEach(function (field) {
        saved.fields.forEach(function (typed) {
          if (typed.name !== field.name) return;
          if (field.type === "checkbox" || field.type === "radio") {
            if (typed.value === field.value) field.checked = typed.checked;
          } else {
            field.value = typed.value;
          }
        });
      });
    });
    kept.openCards.forEach(function (id) {
      var toggle = newMain.querySelector("[data-card-toggle][aria-controls='" + id + "']");
      var card = toggle && toggle.closest("[data-card]");
      if (!card) return;
      toggle.setAttribute("aria-expanded", "true");
      card.classList.add("is-open");
    });
    return formIn(newMain, kept.sent);
  }

  // Back to the field that had the focus, or the send button. A form in a dialog that has
  // closed hands it to the button that opens the dialog, as closing a dialog does. A form
  // that came back as another one (a switch) hands it to the switch with the same name.
  function focusAgain(kept, form, card) {
    var target = null;
    if (form) {
      target = kept.focus === "submit" ? form.querySelector("[type=submit]") : document.getElementById(kept.focus);
      if (!target || !form.contains(target) || !visible(target)) {
        var dialog = form.closest("dialog");
        target = dialog ? main.querySelector("[data-dialog-open='" + dialog.id + "']") : form.querySelector("[type=submit]");
      }
    } else if (card) {
      target = (kept.label && card.querySelector("[aria-label='" + kept.label + "']")) || card.querySelector("[data-card-toggle]");
    }
    if (target && visible(target)) target.focus({ preventScroll: true });
  }

  function done() {
    if (window.somelessPageLoader) window.somelessPageLoader.hide();
    if (window.somelessLoadingBar) window.somelessLoadingBar.finish();
  }

  // Screen readers start reading the new page at its heading. On a phone the menu may still
  // be sliding away (the page behind it can't take the focus until it has gone).
  function focusHeading() {
    var heading = main.querySelector("h1");
    if (!heading) return;
    heading.setAttribute("tabindex", "-1");
    var menu = document.getElementById("side-menu");
    if (menu && menu.open && !menu.classList.contains("is-docked")) {
      menu.addEventListener("close", function () {
        setTimeout(function () { heading.focus({ preventScroll: true }); }, 0);
      }, { once: true });
    } else {
      heading.focus({ preventScroll: true });
    }
  }
})();

// The webmail's reading pane (webmail-mail.html, webmail-read.html). A message in the list opens
// here without a new page, and the address bar gets its own link (/mail/<folder>/<id>), so a
// refresh, the Back button or a shared link opens it again. Its row is picked out and ticked, as
// PrivateEmail does, and loses its bold once it's open: it's read (mail.py counts again).
// What the message says is a page of its own in a frame, where no script runs: it's made as tall
// as the message, and in the dark theme its light colours are turned dark (the sun shows its own
// colours, on white). The arrow opens its attachments out; a file opens in a preview (pictures
// and PDFs) or downloads. The shield shows the links cleaned of tracking; "View source" shows
// the message as it came. On narrow screens a message takes the list's place, with a way back.
// For the other scripts, as wm.reader: open(url, id, remember), close(), current().
(function () {
  var reader = document.querySelector("[data-wm-reader]");
  var list = document.querySelector("[data-wm-messages]");
  if (!reader || !list || !window.wm) return;
  var empty = reader.querySelector("[data-wm-empty]");
  var view = reader.querySelector("[data-wm-view]");
  var choose = reader.querySelector("[data-wm-choose]");
  var openId = view.dataset.open || null;   // opened by its link: the page came with it
  var asking = null;                        // the message on its way
  var watching = null;                      // the frame's size
  var PREVIEW_LIMIT = 25 * 1024 * 1024;     // bigger files are only downloaded
  var listTitle = document.title.replace(/^\(\d+\)\s*/, "").replace(/^.* \| /, "");
  var homeTitle = (document.querySelector("#wm-list-title") || {}).textContent || "Inbox";

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
    if (row) {
      row.classList.add("is-open");
      row.querySelector(".wm-message-link").setAttribute("aria-current", "true");
      var box = row.querySelector("input[type=checkbox]");
      if (!box.checked) {
        box.checked = true;
        box.setAttribute("data-auto", "");
      }
    }
    list.dispatchEvent(new CustomEvent("wm:ticks"));
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

  // more of the list came in, or it was drawn again: the open message may be in it
  list.addEventListener("someless:rows", function () {
    var row = rowFor(openId);
    if (row && !row.classList.contains("is-open")) pickOut(openId);
  });

  // --- what the message says: as tall as it is, in the webmail's colours or its own ---
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

  // Colours: [r, g, b, a] from the browser's rgb()/rgba()
  function parse(colour) {
    var match = /rgba?\(([^)]+)\)/.exec(colour || "");
    if (!match) return null;
    var parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
  }
  function light(rgb) {   // how light it looks, 0 to 1
    function channel(value) {
      value /= 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    }
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  }
  function toHsl(rgb) {
    var r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, h = 0, s = 0;
    if (max !== min) {
      var d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h /= 6;
    }
    return [h * 360, s * 100, l * 100];
  }
  function hsl(h, s, l, a) {
    return "hsla(" + h.toFixed(0) + ", " + s.toFixed(0) + "%, " + l.toFixed(0) + "%, " + a + ")";
  }

  // The message's own light colours made dark (and its dark words light), keeping their hues:
  // what it set on white stays readable on the dark page. What was there before is kept, for
  // the sun to put back.
  function darken(doc) {
    var win = doc.defaultView;
    var changed = [];
    var all = [doc.body].concat(Array.prototype.slice.call(doc.body.querySelectorAll("*")));
    all.forEach(function (element) {
      if (/^(IMG|svg|VIDEO|PICTURE)$/i.test(element.tagName)) return;
      var style = win.getComputedStyle(element);
      var back = parse(style.backgroundColor);
      var ink = parse(style.color);
      var edits = [];
      if (back && back[3] > 0.05 && light(back) > 0.45) {
        var shade = toHsl(back);
        // near white: the card's own colour shows through; coloured: a deep shade of it
        edits.push(["background-color", shade[1] < 12 && shade[2] > 90 ? "transparent" :
          hsl(shade[0], Math.min(shade[1], 55), 14 + (100 - shade[2]) * 0.12, back[3])]);
      }
      if (ink && light(ink) < 0.4) {
        var parts = toHsl(ink);
        edits.push(["color", hsl(parts[0], Math.min(parts[1], 80), 92 - parts[2] * 0.25, ink[3])]);
      }
      var edge = parse(style.borderTopColor);
      if (edge && parseFloat(style.borderTopWidth) > 0 && light(edge) > 0.6) {
        var e = toHsl(edge);
        edits.push(["border-color", hsl(e[0], Math.min(e[1], 40), 28, edge[3])]);
      }
      if (!edits.length) return;
      changed.push([element, element.getAttribute("style")]);
      edits.forEach(function (edit) { element.style.setProperty(edit[0], edit[1], "important"); });
    });
    doc.wmDarkened = changed;
  }
  function undarken(doc) {
    (doc.wmDarkened || []).forEach(function (pair) {
      if (pair[1] === null) pair[0].removeAttribute("style");
      else pair[0].setAttribute("style", pair[1]);
    });
    doc.wmDarkened = null;
  }

  function colours() {
    var doc = page();
    if (!doc) return;
    var dark = document.documentElement.dataset.theme === "dark";
    var paper = dark && !!view.querySelector("[data-wm-paper][aria-pressed='true']");
    doc.documentElement.classList.toggle("is-dark", dark);
    doc.documentElement.classList.toggle("is-light", !dark);
    doc.documentElement.classList.toggle("is-paper", paper);
    var ours = doc.querySelector("style[data-wm-frame]");   // our scrollbars, the pictures' loading look
    if (!ours) {
      ours = doc.createElement("style");
      ours.setAttribute("data-wm-frame", "");
      (doc.head || doc.documentElement).appendChild(ours);
    }
    ours.textContent = wm.frameCss();
    if (dark && !paper) {
      if (!doc.wmDarkened) darken(doc);
    } else if (doc.wmDarkened) {
      undarken(doc);
    }
    fit();
  }
  document.addEventListener("someless:theme", colours);

  function setUp() {
    var body = frame();
    if (!body) return;
    // its page as soon as it's all there, not only once its pictures have come (the frame's load
    // waits for them): in its colours, each picture's place with the turning arrows till it's
    // there, and taller as each one comes
    function early() {
      var doc = page();
      if (!doc || doc.readyState === "loading" || doc.wmEarly) return !!(doc && doc.wmEarly);
      doc.wmEarly = true;
      wm.watchPictures(doc);
      doc.addEventListener("load", fit, true);
      colours();
      return true;
    }
    var tries = 0;
    (function soon() {
      if (frame() === body && !early() && ++tries < 600) requestAnimationFrame(soon);
    })();
    function ready() {
      var doc = page();
      if (!doc || doc.wmReady) return;
      doc.wmReady = true;
      early();
      colours();
      if (doc.fonts) doc.fonts.ready.then(fit);   // its font can make it taller
      // a link to write to someone: a new message to them, here (webmail-compose.js)
      doc.addEventListener("click", function (event) {
        var link = event.target.closest && event.target.closest('a[href^="mailto:"]');
        if (!link || !window.wm.compose) return;
        event.preventDefault();
        wm.compose.mailto(link.getAttribute("href"));
      });
    }
    body.addEventListener("load", ready);
    ready();   // there already
    if (watching) watching.disconnect();
    if (window.ResizeObserver) {   // narrower or wider: taller or shorter
      watching = new ResizeObserver(fit);
      watching.observe(body);
    }
  }

  // --- opening and closing ---
  function show(html, id, subject) {
    document.dispatchEvent(new CustomEvent("wm:leaving"));   // (a reply being written under the last one: kept)
    view.innerHTML = html;
    view.hidden = false;
    empty.hidden = true;
    if (choose) choose.hidden = true;
    view.dataset.open = id;
    openId = id;
    document.body.classList.add("is-reading");
    wm.setTitle(subject + " | Someless Webmail");
    pickOut(id);
    var row = rowFor(id);
    if (row && !row.hasAttribute("data-draft")) {   // read now
      row.classList.remove("is-unread");
      row.dataset.unread = "0";
    }
    var scroller = view.querySelector("[data-wm-read-scroll]");
    if (scroller) scroller.scrollTop = 0;
    setUp();
    document.dispatchEvent(new CustomEvent("wm:opened", { detail: { id: id } }));
  }

  function close(keepTicks) {
    if (asking) asking.abort();
    asking = null;
    if (view.innerHTML) document.dispatchEvent(new CustomEvent("wm:leaving"));
    view.innerHTML = "";
    view.hidden = true;
    if (!choose || choose.hidden) empty.hidden = false;
    delete view.dataset.open;
    openId = null;
    document.body.classList.remove("is-reading");
    wm.setTitle(homeTitle + " | Someless Webmail");
    if (!keepTicks) pickOut(null);
    document.dispatchEvent(new CustomEvent("wm:closed"));
  }

  // Deleted or moved on another device (or in a mail app) while it was open here: it closes,
  // saying so, as the list is brought up to date (webmail-list.js, live: webmail-live.js)
  var GONE_ELSEWHERE = "That message was moved or deleted on another device.";
  document.addEventListener("wm:gone-elsewhere", function (event) {
    if (openId && event.detail.ids.indexOf(openId) >= 0 && !asking) {
      close();
      history.replaceState(history.state, "", reader.dataset.home);
      wm.toast(GONE_ELSEWHERE, { warning: true });
    }
  });
  // opened at the address of one gone meanwhile (a bookmark, a refresh): its folder, saying so
  (function () {
    var address = new URL(location.href);
    var gone = address.searchParams.get("gone");
    if (!gone) return;
    address.searchParams.delete("gone");
    history.replaceState(history.state, "", address.pathname + address.search + address.hash);
    wm.toast(gone === "folder" ? "That folder isn't there any more: it was deleted or renamed, maybe on another device."
                               : GONE_ELSEWHERE, { warning: true });
  })();

  function open(url, id, remember) {
    if (asking) asking.abort();
    var ask = asking = new AbortController();
    reader.classList.add("is-loading");
    wm.loading(reader, true);
    wm.request(url, { signal: ask.signal, quiet: true })
      .then(function (answer) {
        if (asking !== ask) return;
        asking = null;
        reader.classList.remove("is-loading");
        wm.loading(reader, false);
        show(answer.html, id, answer.subject);
        wm.counts(answer.counts, answer.unread);
        if (remember) history.pushState({ wmMessage: id }, "", url);
        else reveal(id);   // Back or Forward: its row may be out of sight
      })
      .catch(function (error) {
        if (error.name === "AbortError") return;   // another message was picked meanwhile
        asking = null;
        reader.classList.remove("is-loading");
        wm.loading(reader, false);
        pickOut(openId);   // back to the one that's open
        if (error.status === 404) {   // gone meanwhile, elsewhere: out of the list, and the list brought up to date
          wm.toast(GONE_ELSEWHERE, { warning: true });
          var row = rowFor(id);
          if (row) wm.list.remove([id]);
          if (wm.list) wm.list.refresh({ quiet: true }).catch(function () {});
        } else {
          wm.board("Error occured. Email has not been loaded", error.problem || "The webmail didn't answer. Check your connection and try again.");
        }
      });
  }

  list.addEventListener("click", function (event) {
    var link = event.target.closest(".wm-message-link");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();   // (with a key held: webmail-actions.js ticks it instead)
    var id = link.closest(".wm-message").dataset.id;
    document.dispatchEvent(new CustomEvent("wm:untick-all"));   // opening one: the others' ticks go
    if (id === openId && !asking) {
      pickOut(id);
      return;   // open already
    }
    pickOut(id);   // at once, while it comes
    open(link.href, id, true);
  });

  // (Back and Forward: webmail-nav.js)

  // --- in the pane ---
  function flipTip(button, on) {   // its tip says what a click does now; the old one goes (tooltip.js)
    var tip = on ? button.dataset.tipOn : button.dataset.tipOff;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
  }

  // Save all: the zip made and brought down with the arrows turning in the button (and how far
  // along, once its size is known), then handed to the browser to keep
  function fileName(disposition) {
    var coded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || "");
    if (coded) {
      try { return decodeURIComponent(coded[1]); } catch (error) { /* (as it's written, below) */ }
    }
    var plain = /filename="?([^";]+)"?/i.exec(disposition || "");
    return plain ? plain[1] : "";
  }

  function saveFiles(link) {
    if (link.classList.contains("is-saving")) return;
    var card = link.closest("[data-wm-files]");
    var count = card ? card.querySelector(".wm-files-count") : null;
    var label = link.querySelector("span");
    var icon = link.querySelector("svg");
    var turning = wm.spinner();
    link.classList.add("is-saving");
    link.setAttribute("aria-busy", "true");
    if (card) card.classList.add("is-saving");
    if (icon) icon.replaceWith(turning);
    else link.insertBefore(turning, label);
    label.textContent = "Saving…";
    function done() {
      wm.spinner.stop(turning);
      if (icon) turning.replaceWith(icon);
      else turning.remove();
      label.textContent = "Save all";
      link.classList.remove("is-saving");
      link.removeAttribute("aria-busy");
      if (card) card.classList.remove("is-saving");
    }
    fetch(link.href, { credentials: "same-origin" }).then(function (response) {
      if (response.redirected && /\/login\b/.test(response.url)) {
        location.href = response.url;   // (signed out meanwhile)
        throw null;
      }
      if (!response.ok) throw new Error("status " + response.status);
      var name = fileName(response.headers.get("Content-Disposition")) || "attachments.zip";
      var total = Number(response.headers.get("Content-Length")) || 0;
      if (!total || !response.body || !response.body.getReader) {
        return response.blob().then(function (blob) { return { blob: blob, name: name }; });
      }
      var stream = response.body.getReader();
      var chunks = [];
      var got = 0;
      return (function next() {
        return stream.read().then(function (step) {
          if (step.done) return { blob: new Blob(chunks, { type: "application/zip" }), name: name };
          chunks.push(step.value);
          got += step.value.length;
          label.textContent = "Saving " + Math.min(99, Math.floor(got * 100 / total)) + "%";
          return next();
        });
      })();
    }).then(function (saved) {
      var url = URL.createObjectURL(saved.blob);
      var keep = document.createElement("a");
      keep.href = url;
      keep.download = saved.name;
      keep.hidden = true;
      document.body.appendChild(keep);
      keep.click();
      keep.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
      done();
      wm.toast((count ? count.textContent.trim() : "The attachments") + " saved");
    }).catch(function (error) {
      done();
      if (error === null) return;
      wm.board("Couldn't save the attachments", "Something went wrong while getting them ready. Try again in a moment.");
    });
  }

  reader.addEventListener("click", function (event) {
    if (event.target.closest("[data-wm-back]")) {
      close();
      history.pushState(null, "", reader.dataset.home);
      return;
    }
    var saveAll = event.target.closest(".wm-save-all");
    if (saveAll && window.fetch && window.URL && URL.createObjectURL) {
      event.preventDefault();
      saveFiles(saveAll);
      return;
    }
    // the arrow, or anywhere else along the bar: the files open out (or fold away)
    var files = event.target.closest("[data-wm-files-toggle]");
    var bar = !files && !event.target.closest("a, button") && event.target.closest(".wm-files-head");
    if (bar) files = bar.querySelector("[data-wm-files-toggle]");
    if (files) {
      var on = files.closest("[data-wm-files]").classList.toggle("is-open");
      files.setAttribute("aria-expanded", String(on));
      flipTip(files, on);
      return;
    }
    var paper = event.target.closest("[data-wm-paper]");
    if (paper) {
      var pressed = paper.getAttribute("aria-pressed") !== "true";
      paper.setAttribute("aria-pressed", String(pressed));
      colours();
      flipTip(paper, pressed);
      return;
    }
    var morePeople = event.target.closest("[data-wm-more-people]");
    if (morePeople) {
      var line = morePeople.closest("[data-wm-people]");
      var showing = line.classList.toggle("is-all");
      line.querySelectorAll("[data-more]").forEach(function (person) { person.hidden = !showing; });
      morePeople.textContent = showing ? morePeople.dataset.lessText : morePeople.dataset.moreText;
      return;
    }
    var preview = event.target.closest("[data-wm-preview]");
    if (preview) {
      showPreview(preview);
      return;
    }
    var shield = event.target.closest("[data-wm-shield]");
    if (shield) {
      showTrackers(shield);
      return;
    }
    var writeTo = event.target.closest("[data-wm-write-to]");
    if (writeTo && window.wm.compose && event.button === 0 && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      wm.compose.open({ to: [writeTo.dataset.wmWriteTo] });
    }
  });

  // --- a dialog of the reading pane's own: a preview, the trackers, the source ---
  function sheet(title, className) {
    var dialog = document.createElement("dialog");
    dialog.className = "wm-dialog wm-sheet" + (className ? " " + className : "");
    dialog.innerHTML = '<div class="wm-sheet-card"><header class="wm-sheet-head"><h2 class="wm-sheet-title"></h2>' +
      '<div class="wm-sheet-tools"></div><button type="button" class="wm-icon wm-sheet-close" aria-label="Close" data-tip="Close"></button></header>' +
      '<div class="wm-sheet-body"></div></div>';
    dialog.querySelector(".wm-sheet-title").textContent = title;
    dialog.querySelector(".wm-sheet-close").appendChild(wm.icon("close"));
    function shut() {
      dialog.classList.add("is-leaving");
      setTimeout(function () {
        if (dialog.open) dialog.close();
        dialog.remove();
      }, wm.reduceMotion ? 0 : 160);
    }
    dialog.querySelector(".wm-sheet-close").addEventListener("click", shut);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      shut();
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) shut();
    });
    document.body.appendChild(dialog);
    dialog.showModal();
    return { dialog: dialog, body: dialog.querySelector(".wm-sheet-body"), tools: dialog.querySelector(".wm-sheet-tools"), close: shut };
  }

  function note(body, title, text) {
    body.innerHTML = '<div class="wm-preview-note"><p class="wm-preview-note-title"></p><p class="wm-preview-note-text"></p></div>';
    body.querySelector(".wm-preview-note-title").textContent = title;
    body.querySelector(".wm-preview-note-text").textContent = text;
  }

  // Attachment preview: a picture or a PDF on the page; anything else, or too big, is downloaded
  function showPreview(button) {
    var shown = sheet(button.dataset.name, "wm-preview");
    var meta = document.createElement("span");
    meta.className = "wm-preview-meta";
    meta.textContent = button.dataset.size;
    shown.tools.appendChild(meta);
    var save = document.createElement("a");
    save.className = "wm-button is-small";
    save.href = button.dataset.download;
    save.setAttribute("download", button.dataset.name);
    save.appendChild(wm.icon("download"));
    save.appendChild(document.createTextNode("Download"));
    shown.tools.appendChild(save);
    var kind = button.dataset.kind;
    if (kind === "other" || !button.dataset.view) {
      note(shown.body, "Preview is not available", "This file type cannot be shown here. Download it to open on your device.");
      return;
    }
    if (Number(button.dataset.bytes) > PREVIEW_LIMIT) {
      note(shown.body, "This file is too large to preview", "Files over 25 MB can only be downloaded.");
      return;
    }
    var turning = loadingNote(shown.body, "Loading the preview");
    var failed = function () {
      wm.spinner.stop(turning);
      note(shown.body, "The preview could not be loaded", "Something went wrong while opening this file. Download it to open on your device.");
    };
    if (kind === "image") {
      var picture = new Image();
      picture.className = "wm-preview-image";
      picture.alt = button.dataset.name;
      picture.onload = function () {
        wm.spinner.stop(turning);
        shown.body.innerHTML = "";
        shown.body.appendChild(picture);
      };
      picture.onerror = failed;
      picture.src = button.dataset.view;
    } else {
      var pdf = document.createElement("iframe");
      pdf.className = "wm-preview-pdf";
      pdf.title = button.dataset.name;
      pdf.addEventListener("load", function () {
        wm.spinner.stop(turning);
        var loading = shown.body.querySelector(".wm-preview-loading");
        if (loading) loading.remove();
      });
      pdf.src = button.dataset.view;
      shown.body.appendChild(pdf);
    }
  }

  // what's coming, in a sheet: the turning arrows and a word (the arrows, to stop when it's come)
  function loadingNote(holder, label) {
    holder.innerHTML = "";
    var line = document.createElement("div");
    line.className = "wm-preview-loading";
    line.setAttribute("role", "status");
    var art = wm.spinner();
    art.classList.remove("is-small");
    line.appendChild(art);
    var words = document.createElement("span");
    words.textContent = label;
    line.appendChild(words);
    holder.appendChild(line);
    return art;
  }

  // The shield: the links cleaned of tracking, each as it was, as it is, and what came off it
  function showTrackers(shield) {
    var holder = view.querySelector("[data-wm-trackers]");
    if (!holder) return;   // none: its tip says so
    var count = holder.content.querySelectorAll(".wm-tracker").length;
    var shown = sheet("Links cleaned from tracking: " + count, "wm-trackers");
    shown.body.innerHTML = '<p class="wm-trackers-text">This email contained tracking links, designed to send information ' +
      "(like when you open the email and your location) back to the sender.</p>" +
      '<p class="wm-trackers-text">We removed the tracking from the links to safeguard your privacy, without any loss of ' +
      "functionality when you open the email.</p>";
    var items = document.createElement("ul");
    items.className = "wm-tracker-list";
    items.appendChild(holder.content.cloneNode(true));
    shown.body.appendChild(items);   // (each link's copy button: copy-button.js)
  }

  // View source: the message as it came, headers and all, with its headers to copy
  function showSource(url) {
    var shown = sheet("Mail source:", "wm-source");
    var copy = document.createElement("button");
    copy.type = "button";
    copy.className = "wm-button is-small is-ghost";
    copy.appendChild(wm.icon("copy"));
    copy.appendChild(document.createTextNode("Copy email headers"));
    copy.disabled = true;
    shown.tools.appendChild(copy);
    var turning = loadingNote(shown.body, "Loading…");
    fetch(url, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("refused");
        return response.text();
      })
      .then(function (text) {
        var pre = document.createElement("pre");
        pre.className = "wm-source-text";
        pre.textContent = text;
        wm.spinner.stop(turning);
        shown.body.innerHTML = "";
        shown.body.appendChild(pre);
        var headers = text.split(/\r?\n\r?\n/)[0];
        copy.disabled = false;
        copy.addEventListener("click", function () {
          wm.copy(headers).then(function () {   // (the older way too, on a plain http:// address)
            // said on the button, in sight: a toast would be under the sheet
            copy.replaceChildren(wm.icon("check"), document.createTextNode("Copied"));
            copy.classList.add("is-copied");
            clearTimeout(copy.wmCopiedTimer);
            copy.wmCopiedTimer = setTimeout(function () {
              copy.replaceChildren(wm.icon("copy"), document.createTextNode("Copy email headers"));
              copy.classList.remove("is-copied");
            }, 1800);
          }, function () {
            wm.board("Couldn't copy", "Select the headers and copy them yourself.");
          });
        });
      })
      .catch(function () {
        wm.spinner.stop(turning);
        shown.close();
        wm.board("Couldn't show the source", "The webmail didn't answer. Check your connection and try again.");
      });
  }

  // another folder's page (webmail-nav.js): its reading pane in place of this one
  function adopt(page) {
    var nextReader = page.querySelector("[data-wm-reader]");
    reader.dataset.home = nextReader.dataset.home;
    homeTitle = (page.querySelector("#wm-list-title") || {}).textContent || homeTitle;
    var tools = choose && choose.querySelector(".wm-choose-tools");
    var nextTools = nextReader.querySelector(".wm-choose-tools");
    if (tools && nextTools) tools.innerHTML = nextTools.innerHTML;
    if (choose) choose.hidden = true;
    var nextView = nextReader.querySelector("[data-wm-view]");
    if (asking) asking.abort();
    asking = null;
    reader.classList.remove("is-loading");
    wm.loading(reader, false);
    if (nextView && nextView.dataset.open) {
      document.dispatchEvent(new CustomEvent("wm:leaving"));
      view.innerHTML = nextView.innerHTML;
      view.hidden = false;
      empty.hidden = true;
      view.dataset.open = nextView.dataset.open;
      openId = nextView.dataset.open;
      pickOut(openId);
      setUp();
      reveal(openId);
      document.dispatchEvent(new CustomEvent("wm:opened", { detail: { id: openId } }));
    } else {
      close(true);
      pickOut(null);
    }
  }

  window.wm.reader = {
    adopt: adopt, open: open, close: close, pickOut: pickOut, showSource: showSource,
    current: function () { return openId; },
    element: function () { return view.querySelector("[data-wm-read]"); },
    reload: function () {   // (a flag changed elsewhere: the bar shows it)
      var row = rowFor(openId);
      var link = row && row.querySelector(".wm-message-link");
      if (openId) open(link ? link.href : location.href, openId, false);
    },
  };

  if (openId) {   // the page came with it open (its link, a refresh)
    setUp();
    reveal(openId);
  }
})();

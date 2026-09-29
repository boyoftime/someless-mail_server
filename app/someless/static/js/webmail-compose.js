// Writing mail in the webmail (webmail-mail.html, webmail-composer.html, compose.py), as in
// PrivateEmail. Compose opens a window at the bottom right; several can be open (up to five),
// each minimized to a bar or opened to full screen. A reply or a forward from the reading pane
// is written right under the message (Maximize takes it to a window of its own).
//
// A composer: From (the mailbox's addresses), To, Cc and Bcc (each address a chip; what's typed
// is looked up among the people the mailbox writes to and hears from), the subject, and what it
// says, in a page of its own (a frame where no script runs) with the formatting bar (Aa): fonts,
// sizes, bold and the rest, colours, lists, alignment, quotes, tables and links. Files attach
// with the paper clip or by dropping them on it; pictures go in what it says. Its signature can
// be changed; it can be marked important. It's saved to Drafts as it's written, and on closing
// (it asks); Send checks it first (an address, a subject) and says when it went.
//
// For the other scripts, as wm.compose: open({kind, id, to}), fromMessage(kind, id), mailto(href).
(function () {
  var holder = document.querySelector("[data-wm-composers]");
  var template = document.getElementById("wm-composer");
  if (!holder || !template || !window.wm) return;
  var overlay = document.querySelector("[data-wm-compose-overlay]");
  var csrf = document.querySelector('meta[name="csrf-token"]');
  var MAX_WINDOWS = 5;
  var WIDE = 1200;             // px: below it, a composer takes the whole screen
  var SAVE_AFTER = 15000;      // ms after the last change: saved to Drafts on its own
  var FONTS = [["Arial", "Arial, Helvetica, sans-serif"], ["Georgia", "Georgia, serif"], ["Tahoma", "Tahoma, Verdana, sans-serif"],
               ["Times New Roman", "'Times New Roman', Times, serif"], ["Trebuchet MS", "'Trebuchet MS', sans-serif"],
               ["Verdana", "Verdana, Geneva, sans-serif"], ["Courier New", "'Courier New', Courier, monospace"]];
  var SIZES = [["Small", "2"], ["Normal", "3"], ["Large", "5"], ["Huge", "6"]];
  var COLORS = ["#000000", "#434343", "#666666", "#999999", "#cccccc", "#ffffff", "#e03131", "#f76707", "#f59f00", "#2f9e44",
                "#1971c2", "#6741d9", "#c2255c", "#ffc9c9", "#ffe8cc", "#fff3bf", "#d3f9d8", "#d0ebff", "#e5dbff", "#fcc2d7"];
  var composers = [];          // every composer open: in windows, and the one under a message
  var counter = 0;

  function data() {
    return holder.dataset;
  }
  function narrow() {
    return window.innerWidth < WIDE;
  }
  function human(bytes) {
    if (bytes < 1024) return bytes + " B";
    var units = ["KB", "MB", "GB"], size = bytes / 1024, unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit++;
    }
    return (Math.round(size * 100) / 100) + " " + units[unit];
  }
  function newCid() {   // a picture's name inside the message it goes with
    return Math.random().toString(16).slice(2) + Date.now().toString(16) + "@someless";
  }

  // --- the page of what it says (a frame, where no script runs; this script works it) ---
  function editorPage() {
    var dark = document.documentElement.dataset.theme === "dark";
    return '<!doctype html><html class="' + (dark ? "is-dark" : "is-light") + '"><head><meta charset="utf-8"><style>' +
      "html{color-scheme:" + (dark ? "dark" : "light") + "}" +
      "body{margin:0;padding:14px 16px 18px;min-height:calc(100vh - 32px);box-sizing:border-box;font:14px/1.55 Arial,Helvetica,sans-serif;" +
      "color:" + (dark ? "#e3e7f4" : "#1c1f24") + ";overflow-wrap:anywhere;outline:none}" +
      "body.is-empty::before{content:'Write your message here';position:absolute;color:" + (dark ? "#7c87a9" : "#878d98") + ";pointer-events:none}" +
      "p{margin:0}a{color:" + (dark ? "#8cb4ff" : "#3b63e6") + "}img{max-width:100%;height:auto}" +
      "blockquote{margin:0 0 0 .4em;padding-left:.9em;border-left:2px solid " + (dark ? "#3b4777" : "#c9ced8") + "}" +
      "blockquote.wm-quote{margin:16px 0 0;padding:16px 0 0;border:0;border-top:1px solid " + (dark ? "#1f2a55" : "#e6e8ed") + "}" +
      ".wm-quote-title{margin:0 0 8px;color:" + (dark ? "#a7b0cd" : "#5d636e") + "}.wm-quote-head{margin-bottom:12px;color:" +
      (dark ? "#a7b0cd" : "#5d636e") + "}table{border-collapse:collapse}td,th{border:1px solid " + (dark ? "#3b4777" : "#c9ced8") +
      ";padding:4px 8px;min-width:40px}.wm-signature{color:inherit}" +
      "img.wm-picked{outline:2px solid #3b82f6;outline-offset:2px}" +
      ".wm-write-here::before{content:'Write your message here';position:absolute;color:" + (dark ? "#7c87a9" : "#878d98") + ";pointer-events:none}" +
      "body.wm-quote-folded blockquote.wm-quote{display:none}" + wm.frameCss() +
      "</style></head><body contenteditable=\"true\" spellcheck=\"true\" class=\"is-empty\"></body></html>";
  }

  // --- a composer ---
  function Composer(options) {
    var self = this;
    this.id = ++counter;
    this.options = options;
    this.element = template.content.firstElementChild.cloneNode(true);
    this.element.dataset.composer = this.id;
    this.frame = this.element.querySelector("[data-cm-editor]");
    this.title = this.element.querySelector("[data-cm-title]");
    this.subject = this.element.querySelector("[data-cm-subject]");
    this.filesList = this.element.querySelector("[data-cm-files]");
    this.status = this.element.querySelector("[data-cm-status]");
    this.fields = {};
    this.files = [];            // {key, name, size, type, blobId, cid, inline, uploading, element}
    this.draft = null;          // the draft in Drafts, once saved
    this.reply = null;          // what it answers: {kind, id, inReplyTo, references, title}
    this.from = null;
    this.froms = [];
    this.important = false;
    this.signatures = [];
    this.changed = false;       // since it was last saved
    this.touched = false;       // since it opened
    this.saveTimer = null;
    this.ready = false;
    this.pendingHtml = "";
    ["to", "cc", "bcc"].forEach(function (field) { self.fields[field] = new Tags(self, field); });
    this.wire();
  }

  Composer.prototype.doc = function () {
    var doc = this.frame.contentDocument;
    return doc && doc.body && doc.body.isContentEditable ? doc : null;
  };

  // the frame drawn (again: moving it in the page draws it anew), with what it says put back
  Composer.prototype.mountEditor = function (html) {
    var self = this;
    this.ready = false;
    this.pendingHtml = html || "";
    this.frame.addEventListener("load", function onLoad() {
      self.frame.removeEventListener("load", onLoad);
      var doc = self.frame.contentDocument;
      doc.body.innerHTML = self.pendingHtml;
      wm.watchPictures(doc);   // (a draft's pictures, a reply's: the turning arrows till each is there)
      self.ready = true;
      self.wireEditor(doc);
      self.checkEmpty();
      self.foldQuote(!!self.quoteFolded);
      self.fit();
    });
    this.frame.srcdoc = editorPage();
  };

  Composer.prototype.html = function () {
    var doc = this.doc();
    return doc ? wm.contentOf(doc.body) : this.pendingHtml;
  };

  Composer.prototype.checkEmpty = function () {
    var doc = this.doc();
    if (!doc) return;
    var empty = !doc.body.textContent.trim() && !doc.body.querySelector("img, table, li, blockquote, .wm-signature");
    doc.body.classList.toggle("is-empty", empty);
    // with a signature or what it answers below it: the empty line at the top says where to write
    var first = doc.body.firstElementChild;
    var below = doc.body.querySelector(".wm-signature, blockquote.wm-quote");
    Array.prototype.forEach.call(doc.querySelectorAll(".wm-write-here"), function (one) {
      if (one !== first) one.classList.remove("wm-write-here");
    });
    if (first) {
      var hint = !empty && !!below && first !== below && first.tagName === "P" && !first.textContent.trim() && !first.querySelector("img, table");
      first.classList.toggle("wm-write-here", hint);
      if (!first.classList.length) first.removeAttribute("class");
    }
  };

  // A reply under the message: what it answers folded away behind ⋯, so Send is just under the
  // words being written; ⋯ shows it again. It goes with the reply either way.
  Composer.prototype.foldQuote = function (folded) {
    var doc = this.doc();
    var button = this.element.querySelector('[data-cm="quote"]');
    this.quoteFolded = folded;
    button.hidden = !doc || !doc.querySelector("blockquote.wm-quote") || !this.element.classList.contains("is-inline");
    if (doc) doc.body.classList.toggle("wm-quote-folded", folded && !button.hidden);
    button.setAttribute("aria-expanded", String(!folded));
    var tip = folded ? button.dataset.tipOff : button.dataset.tipOn;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
    this.fit();
  };

  // under a message: the frame as tall as what it says
  Composer.prototype.fit = function () {
    if (!this.element.classList.contains("is-inline")) {
      this.frame.style.height = "";
      return;
    }
    var doc = this.doc();
    if (!doc) return;
    doc.body.style.minHeight = "0";
    this.frame.style.height = Math.max(180, Math.ceil(doc.documentElement.scrollHeight) + 4) + "px";
  };

  Composer.prototype.changedNow = function () {
    this.changed = true;
    this.touched = true;
    this.setStatus("");
    var self = this;
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(function () { self.save(true); }, SAVE_AFTER);
  };

  Composer.prototype.setStatus = function (text) {
    this.status.textContent = text;
  };

  Composer.prototype.setTitle = function () {
    var subject = this.subject.value.trim();
    this.title.textContent = subject || "Compose Email";
    this.element.setAttribute("aria-label", subject || "Compose Email");
  };

  Composer.prototype.setFrom = function (address) {
    this.from = address;
    var shown = this.froms.filter(function (one) { return one.email === address; })[0];
    this.element.querySelector("[data-cm-from-text]").textContent = shown && shown.name ? shown.name + " <" + address + ">" : address;
    this.element.querySelector("[data-cm-from-row]").hidden = this.froms.length < 2 && !narrow();
  };

  Composer.prototype.fill = function (started) {
    var self = this;
    this.froms = started.froms || [];
    this.setFrom(started.from);
    ["to", "cc", "bcc"].forEach(function (field) {
      (started[field] || []).forEach(function (person) { self.fields[field].add(person, true); });
    });
    if ((started.cc || []).length || (started.bcc || []).length) this.showCcBcc();
    this.subject.value = started.subject || "";
    this.setTitle();
    this.draft = started.draft || null;
    this.reply = started.reply || null;
    this.signatures = started.signatures || [];
    this.limits = started.limits || { file: 50 * 1024 * 1024, all: 50 * 1024 * 1024, recipients: 50 };   // (the mailbox's own: compose.py)
    this.setImportant(!!started.important);
    (started.attachments || []).forEach(function (part) {
      self.addFile({ name: part.name, size: part.size, type: part.type, blobId: part.blobId, cid: part.cid, inline: part.inline });
    });
    this.mountEditor(started.html || "");
    if (this.reply) {   // a reply or a forward: the formatting bar out from the start, Aa lit
      var format = this.element.querySelector('[data-cm="format"]');
      format.setAttribute("aria-pressed", "true");
      format.classList.add("is-on");
      this.element.querySelector("[data-cm-toolbar]").hidden = false;
    }
    this.changed = false;
    this.touched = false;
  };

  // Cc and Bcc, opened by their link: they open down into place (as it opens with some: there)
  Composer.prototype.showCcBcc = function (smoothly) {
    var element = this.element;
    ["cc", "bcc"].forEach(function (field) {
      var row = element.querySelector('[data-cm-row="' + field + '"]');
      if (smoothly) wm.reveal(row, true);
      else row.hidden = false;
    });
    element.querySelector('[data-cm="ccbcc"]').hidden = true;
  };

  Composer.prototype.setImportant = function (on) {
    this.important = on;
    var button = this.element.querySelector('[data-cm="important"]');
    button.setAttribute("aria-pressed", String(on));
    button.classList.toggle("is-on", on);
    var tip = on ? button.dataset.tipOn : button.dataset.tipOff;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
  };

  // --- its files ---
  Composer.prototype.totalSize = function () {
    return this.files.reduce(function (sum, file) { return sum + (file.size || 0); }, 0);
  };

  Composer.prototype.addFile = function (file) {
    file.key = file.key || "f" + (++counter);
    this.files.push(file);
    if (!file.inline) this.drawFile(file);
    return file;
  };

  Composer.prototype.drawFile = function (file) {
    var self = this;
    var item = document.createElement("li");
    item.className = "wm-cm-file" + (file.uploading ? " is-uploading" : "");
    if (file.uploading) {   // on its way: the turning arrows, then its kind's icon
      file.spinner = wm.spinner();
      item.appendChild(file.spinner);
    } else {
      item.appendChild(kindIcon(file));
    }
    var text = document.createElement("span");
    text.className = "wm-cm-file-text";
    var name = document.createElement("span");
    name.className = "wm-cm-file-name";
    name.textContent = file.name;
    name.title = file.name;
    var size = document.createElement("span");
    size.className = "wm-cm-file-size";
    size.textContent = file.uploading ? "Uploading…" : human(file.size || 0);
    text.appendChild(name);
    text.appendChild(size);
    item.appendChild(text);
    var bar = document.createElement("span");
    bar.className = "wm-cm-file-bar";
    bar.innerHTML = "<span></span>";
    item.appendChild(bar);
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "wm-cm-file-x";
    remove.setAttribute("aria-label", "Remove " + file.name);
    remove.appendChild(wm.icon("close"));
    remove.addEventListener("click", function () { self.removeFile(file); });
    item.appendChild(remove);
    file.element = item;
    this.filesList.appendChild(item);
    this.filesList.hidden = false;
  };

  function kindIcon(file) {
    return wm.icon((file.type || "").indexOf("image/") === 0 ? "image" : file.type === "application/pdf" ? "pdf" : "file");
  }
  var SHRUNK = /^(image\/png|image\/jpeg|application\/pdf)$/;   // (made smaller on the way: webmail/shrink.py)

  Composer.prototype.removeFile = function (file) {
    if (file.request) file.request.abort();
    this.files = this.files.filter(function (other) { return other !== file; });
    if (file.element) file.element.remove();
    this.filesList.hidden = !this.filesList.children.length;
    this.changedNow();
  };

  Composer.prototype.upload = function (source, picture) {
    var self = this;
    if (source.size > this.limits.file) {
      wm.board("Files upload failed", "Maximum allowed file size " + human(this.limits.file));
      return null;
    }
    if (this.totalSize() + source.size > this.limits.all) {
      wm.board("Files upload failed", "All files should not exceed " + human(this.limits.all));
      return null;
    }
    var file = this.addFile({ name: source.name || "picture", size: source.size, type: source.type || "application/octet-stream",
                              uploading: true, inline: !!picture });
    return new Promise(function (resolve) {
      var form = new FormData();
      form.append("file", source, source.name || "picture.png");
      if (picture) form.append("picture", "1");
      var request = new XMLHttpRequest();
      file.request = request;
      request.open("POST", data().uploadUrl);
      request.setRequestHeader("Accept", "application/json");
      if (csrf) request.setRequestHeader("X-CSRFToken", csrf.content);
      request.upload.addEventListener("progress", function (event) {
        if (!event.lengthComputable || !file.element) return;
        file.element.querySelector(".wm-cm-file-bar span").style.width = Math.round(event.loaded * 100 / event.total) + "%";
        if (event.loaded >= event.total && SHRUNK.test(file.type)) {   // all sent: the webmail makes it smaller now
          file.element.querySelector(".wm-cm-file-size").textContent = "Compressing…";
        }
      });
      request.addEventListener("load", function () {
        file.request = null;
        var answer = {};
        try {
          answer = JSON.parse(request.responseText);
        } catch (error) { /* (not the webmail's answer) */ }
        if (request.status === 401 && answer.login) {
          location.href = answer.login;
          return;
        }
        if (request.status !== 200 || !answer.blobId) {
          self.files = self.files.filter(function (other) { return other !== file; });
          if (file.element) file.element.remove();
          self.filesList.hidden = !self.filesList.children.length;
          wm.board("Files upload failed", answer.problem || "Try again in a moment.");
          resolve(null);
          return;
        }
        file.uploading = false;
        file.blobId = answer.blobId;
        file.type = answer.type;
        file.size = answer.size;
        if (file.element) {
          file.element.classList.remove("is-uploading");
          if (file.spinner) {
            file.spinner.replaceWith(kindIcon(file));
            wm.spinner.stop(file.spinner);
            file.spinner = null;
          }
          var sizeText = file.element.querySelector(".wm-cm-file-size");
          sizeText.textContent = human(file.size);
          if (answer.original > answer.size) {
            sizeText.title = "Made smaller, nothing lost: " + human(answer.original) + " → " + human(answer.size);
          }
        }
        self.changedNow();
        resolve(file);
      });
      request.addEventListener("error", function () {
        file.request = null;
        self.files = self.files.filter(function (other) { return other !== file; });
        if (file.element) file.element.remove();
        self.filesList.hidden = !self.filesList.children.length;
        wm.board("Files upload failed", "The webmail didn't answer. Check your connection and try again.");
        resolve(null);
      });
      request.send(form);
    });
  };

  // a picture put in what it says: uploaded, then shown where the cursor was (and sent with it)
  Composer.prototype.insertPicture = function (source) {
    var self = this;
    var doc = this.doc();
    if (!doc) return;
    var range = this.savedRange;
    var promise = this.upload(source, true);
    if (!promise) return;
    var wrap = this.element.querySelector("[data-cm-editor-wrap]");
    wm.loading(wrap, true, { label: "Adding the picture…" });   // (until it shows)
    promise.then(function (file) {
      if (!file) {
        wm.loading(wrap, false);
        return;
      }
      file.cid = newCid();
      var picture = doc.createElement("img");
      picture.src = "/compose/blob/" + encodeURIComponent(file.blobId) + "?type=" + encodeURIComponent(file.type);
      picture.alt = file.name;
      picture.setAttribute("data-cid", file.cid);
      picture.style.maxWidth = "100%";
      self.restoreRange(range);
      var selection = doc.getSelection();
      if (selection.rangeCount && doc.body.contains(selection.anchorNode)) {
        var place = selection.getRangeAt(0);
        place.deleteContents();
        place.insertNode(picture);
        place.setStartAfter(picture);
        place.collapse(true);
        selection.removeAllRanges();
        selection.addRange(place);
      } else {
        doc.body.appendChild(picture);
      }
      wm.loading(wrap, false);   // (in its place now, it shows the turning arrows itself till it's there)
      var shown = function () {
        self.fit();
      };
      picture.addEventListener("load", shown);
      picture.addEventListener("error", shown);
      self.checkEmpty();
      self.changedNow();
    });
  };

  // A picture in what it says, right-clicked: another put in its place, made smaller or larger,
  // or taken out (one taken out isn't sent: only the pictures it shows go with it: message())
  Composer.prototype.pictureMenu = function (picture, event) {
    var self = this;
    var doc = this.doc();
    if (!doc) return;
    var outer = this.frame.getBoundingClientRect();
    var widest = Math.max(80, doc.body.clientWidth - 32);
    var natural = picture.naturalWidth || widest;
    function size(share) {
      return function () {
        picture.setAttribute("width", String(Math.max(16, Math.round(Math.min(natural, widest) * share))));
        picture.removeAttribute("height");
        picture.style.width = "";
        picture.style.height = "";
        self.changedNow();
        self.fit();
      };
    }
    picture.classList.add("wm-picked");
    wm.menu({ x: outer.left + event.clientX, y: outer.top + event.clientY }, [
      { label: "Replace picture", icon: "image", act: function () {
        self.replacing = picture;
        self.element.querySelector("[data-cm-picture-input]").click();
      } },
      "-",
      { label: "Small", icon: "image", act: size(0.25) },
      { label: "Medium", icon: "image", act: size(0.5) },
      { label: "Large", icon: "image", act: size(0.75) },
      { label: "Original size", icon: "image", act: function () {
        picture.removeAttribute("width");
        picture.removeAttribute("height");
        picture.style.width = "";
        picture.style.height = "";
        self.changedNow();
        self.fit();
      } },
      "-",
      { label: "Remove picture", icon: "trash", danger: true, act: function () {
        picture.remove();
        self.checkEmpty();
        self.changedNow();
        self.fit();
      } },
    ], { onClose: function () {
      picture.classList.remove("wm-picked");
      if (!picture.classList.length) picture.removeAttribute("class");
    } });
  };

  // a picture put in the place of another: uploaded, then shown there (as wide as the one before)
  Composer.prototype.replacePicture = function (picture, source) {
    var self = this;
    var promise = this.upload(source, true);
    if (!promise) return;
    var wrap = this.element.querySelector("[data-cm-editor-wrap]");
    wm.loading(wrap, true, { label: "Replacing the picture…" });
    promise.then(function (file) {
      wm.loading(wrap, false);
      if (!file || !picture.isConnected) return;
      file.cid = newCid();
      picture.src = "/compose/blob/" + encodeURIComponent(file.blobId) + "?type=" + encodeURIComponent(file.type);
      picture.alt = file.name;
      picture.setAttribute("data-cid", file.cid);
      picture.removeAttribute("height");
      picture.addEventListener("load", function () { self.fit(); }, { once: true });
      self.changedNow();
    });
  };

  Composer.prototype.saveRange = function () {
    var doc = this.doc();
    if (!doc) return;
    var selection = doc.getSelection();
    this.savedRange = selection.rangeCount && doc.body.contains(selection.anchorNode) ? selection.getRangeAt(0).cloneRange() : null;
  };
  Composer.prototype.restoreRange = function (range) {
    var doc = this.doc();
    if (!doc) return;
    this.frame.contentWindow.focus();
    if (!range) return;
    var selection = doc.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  };

  // --- what's sent to the webmail ---
  Composer.prototype.message = function (quiet) {
    var doc = this.doc();
    var written = this.html();
    var inUse = {};
    var holderOfWords = doc ? doc.body : null;
    if (!holderOfWords) {   // (its frame gone already: what it said, kept)
      holderOfWords = document.createElement("div");
      holderOfWords.innerHTML = written;
    }
    holderOfWords.querySelectorAll("img[data-cid]").forEach(function (picture) { inUse[picture.getAttribute("data-cid")] = true; });
    holderOfWords.querySelectorAll('img[src*="/compose/blob/"]').forEach(function (picture) {
      var match = /\/compose\/blob\/([^?"]+)/.exec(picture.getAttribute("src"));
      if (match) inUse["blob:" + decodeURIComponent(match[1])] = true;
    });
    return {
      from: this.from, to: this.fields.to.people(), cc: this.fields.cc.people(), bcc: this.fields.bcc.people(),
      subject: this.subject.value, html: written, important: this.important, draft: this.draft, reply: this.reply,
      quiet: !!quiet,
      attachments: this.files.filter(function (file) {
        return file.blobId && (!file.inline || inUse[file.cid] || inUse["blob:" + file.blobId]);
      }).map(function (file) {
        return { blobId: file.blobId, name: file.name, type: file.type, size: file.size, cid: file.cid, inline: !!file.inline };
      }),
    };
  };

  Composer.prototype.isEmpty = function () {
    var doc = this.doc();
    var said = doc ? doc.body.textContent.trim() : "";
    return !this.touched && !this.draft ||
      (!said && !this.subject.value.trim() && !this.files.length &&
       !["to", "cc", "bcc"].some(function (field) { return this.fields[field].list.length; }, this) && !this.draft);
  };

  Composer.prototype.uploading = function () {
    return this.files.some(function (file) { return file.uploading; });
  };

  Composer.prototype.save = function (quiet) {
    var self = this;
    clearTimeout(this.saveTimer);
    if (!this.changed && quiet) return Promise.resolve(true);
    if (this.uploading()) {
      if (!quiet) wm.toast("Please wait, attachments are still uploading.", { warning: true });
      return Promise.resolve(false);
    }
    if (this.saving) return this.saving;
    this.setStatus("Saving…");
    var sent = this.message(quiet);
    this.changed = false;
    this.saving = wm.request(data().saveUrl, { method: "POST", body: sent, quiet: quiet, failTitle: "Your message has not been saved" })
      .then(function (answer) {
        self.saving = null;
        self.draft = answer.draft;
        self.setStatus("Saved");
        wm.counts(answer.counts, answer.unread);
        if (answer.message) wm.toast(answer.message);
        refreshIf("drafts");
        return true;
      }, function () {
        self.saving = null;
        self.changed = true;
        self.setStatus(quiet ? "Not saved" : "");
        return false;
      });
    return this.saving;
  };

  Composer.prototype.send = function () {
    var self = this;
    if (this.sending) return;
    ["to", "cc", "bcc"].forEach(function (field) { self.fields[field].commit(); });
    if (this.uploading()) {
      wm.toast("Please wait, attachments are still uploading.", { warning: true });
      return;
    }
    var wrong = ["to", "cc", "bcc"].reduce(function (found, field) { return found.concat(self.fields[field].wrong()); }, []);
    if (wrong.length) {
      wm.board("Invalid email address", wrong[0] + " isn't an email address. Change it, then send again.");
      return;
    }
    if (!this.fields.to.list.length && !this.fields.cc.list.length) {
      wm.board("Email wasn't sent", "Enter at least one email address in the 'To:' or 'Cc:' fields");
      this.fields.to.input.focus();
      return;
    }
    var count = this.fields.to.list.length + this.fields.cc.list.length + this.fields.bcc.list.length;
    if (count > this.limits.recipients) {
      wm.board("Email wasn't sent", "Recipient limit exceeded. The maximum number allowed per email is " + this.limits.recipients);
      return;
    }
    var go = this.subject.value.trim() ? Promise.resolve(true) : wm.confirm({
      title: "Mail has no subject. Want to send it anyway?", yes: "Send without subject", no: "Add subject",
    });
    go.then(function (yes) {
      if (!yes) {
        self.subject.focus();
        return;
      }
      clearTimeout(self.saveTimer);
      self.sending = true;
      self.element.classList.add("is-sending");
      var body = self.message(false);
      // off it goes: the rocket rises from Send while it goes, and blasts off once it's sent (webmail-rocket.js)
      var flight = wm.rocket ? wm.rocket(self.element.querySelector('[data-cm="send"]')) : null;
      wm.request(data().sendUrl, { method: "POST", body: body, quiet: true }).then(function (answer) {
        if (flight) flight.sent();
        self.sending = false;
        wm.counts(answer.counts, answer.unread);
        wm.toast(answer.message || "Message has been successfully sent");
        self.close(true);
        refreshIf("sent");
        refreshIf("drafts");
        if (self.reply && wm.list) wm.list.refresh({ quiet: true });
      }, function (error) {
        if (flight) flight.failed();
        self.sending = false;
        self.element.classList.remove("is-sending");
        if (error.name === "AbortError") return;
        failed(self, error);
      });
    });
  };

  // not sent: the board says why; saved to Drafts, it stays open to be put right
  function failed(composer, error) {
    var title = "Message has not been sent";
    var problem = error.problem || "The webmail didn't answer. Check your connection and try again.";
    if (error.answer) {
      title = error.answer.title || title;
      if (error.answer.draft) composer.draft = error.answer.draft;
      wm.counts(error.answer.counts, error.answer.unread);
      refreshIf("drafts");
    }
    wm.board(title, problem);
  }

  // --- closing ---
  Composer.prototype.close = function (sent) {
    var self = this;
    if (sent || this.isEmpty() || (!this.changed && this.draft)) {
      this.remove();
      return Promise.resolve(true);
    }
    return askToSave(this).then(function (choice) {
      if (choice === "save") {
        return self.save(false).then(function (saved) {
          if (saved) self.remove();
          return saved;
        });
      }
      if (choice === "discard") {
        self.discard();
        return true;
      }
      return false;
    });
  };

  Composer.prototype.discard = function () {
    var self = this;
    clearTimeout(this.saveTimer);
    this.files.forEach(function (file) { if (file.request) file.request.abort(); });
    if (this.draft) {
      var draft = this.draft;
      wm.request(data().discardUrl, { method: "POST", body: { draft: draft }, quiet: true }).then(function (answer) {
        wm.counts(answer.counts, answer.unread);
        refreshIf("drafts");
      }, function () {});
    }
    self.remove();
  };

  Composer.prototype.remove = function () {
    clearTimeout(this.saveTimer);
    composers = composers.filter(function (other) { return other !== this; }, this);
    var element = this.element;
    if (this.tables) this.tables.destroy();
    if (element.classList.contains("is-screen")) this.toggleScreen(false);
    if (element.classList.contains("is-full")) setOverlay(false);
    if (element.classList.contains("is-inline")) {
      var card = element.closest(".wm-read-card");
      if (card) card.classList.remove("has-reply");
    }
    element.classList.add("is-leaving");
    setTimeout(function () { element.remove(); layout(); }, wm.reduceMotion ? 0 : 180);
    layout();
    showLimit();
  };

  // "Save your message as a draft?": save, discard, or go back to it
  function askToSave(composer) {
    return new Promise(function (resolve) {
      var dialog = document.createElement("dialog");
      dialog.className = "wm-dialog";
      dialog.innerHTML = '<div class="wm-dialog-card"><h2 class="wm-dialog-title">Save your message as a draft?</h2>' +
        '<p class="wm-dialog-text">You can save this message and get back to it in the Drafts folder later</p>' +
        '<div class="wm-dialog-actions"><button type="button" class="wm-button is-ghost" data-choice="cancel">Cancel</button>' +
        '<button type="button" class="wm-button is-ghost is-danger-text" data-choice="discard">Discard message</button>' +
        '<button type="button" class="wm-button" data-choice="save">Save as draft</button></div></div>';
      function done(choice) {
        dialog.classList.add("is-leaving");
        setTimeout(function () {
          if (dialog.open) dialog.close();
          dialog.remove();
        }, wm.reduceMotion ? 0 : 160);
        resolve(choice);
      }
      dialog.addEventListener("click", function (event) {
        var button = event.target.closest("[data-choice]");
        if (button) done(button.dataset.choice);
        else if (event.target === dialog) done("cancel");
      });
      dialog.addEventListener("cancel", function (event) {
        event.preventDefault();
        done("cancel");
      });
      document.body.appendChild(dialog);
      dialog.showModal();
      dialog.querySelector('[data-choice="save"]').focus();
    });
  }

  function refreshIf(folder) {
    var nav = document.querySelector("[data-wm-folders]");
    if (nav && nav.dataset.current === folder && wm.list) wm.list.reload();
  }

  // --- the windows ---
  function windows() {
    return composers.filter(function (composer) { return !composer.element.classList.contains("is-inline"); });
  }

  // side by side from the right; those that don't fit are minimized (the oldest first)
  function layout() {
    var open = windows();
    var room = window.innerWidth - 24;
    var needed = 0;
    open.slice().reverse().forEach(function (composer) {
      var minimized = composer.element.classList.contains("is-minimized");
      needed += (minimized ? 280 : 600) + 16;
    });
    if (!narrow()) {
      for (var index = 0; index < open.length && needed > room; index++) {
        var composer = open[index];
        if (composer.element.classList.contains("is-minimized") || composer.element.classList.contains("is-full") ||
            composer.element.classList.contains("is-screen")) continue;
        if (index === open.length - 1) break;   // the newest stays open
        composer.element.classList.add("is-minimized");
        needed -= 320;
      }
    } else {   // a phone: one open at a time
      open.forEach(function (composer, index) {
        if (index < open.length - 1 && !composer.element.classList.contains("is-minimized")) composer.element.classList.add("is-minimized");
      });
    }
    holder.classList.toggle("has-windows", open.length > 0);
  }
  window.addEventListener("resize", layout);

  function setOverlay(on) {
    if (overlay) overlay.hidden = !on;
    document.body.classList.toggle("is-composing-full", on);
  }

  function showLimit() {
    var button = document.querySelector("[data-wm-compose]");
    if (!button) return;
    var full = windows().length >= MAX_WINDOWS;
    button.classList.toggle("is-limited", full);
    if (full) button.dataset.tip = "Compose limit exceeded. Close a window to continue.";
    else delete button.dataset.tip;
  }

  Composer.prototype.toggleMinimize = function (on) {
    var element = this.element;
    var minimized = on === undefined ? !element.classList.contains("is-minimized") : on;
    if (minimized && this.tables) this.tables.hide();
    if (minimized && element.classList.contains("is-screen")) this.toggleScreen(false);
    if (minimized && element.classList.contains("is-full")) this.toggleFull(false);
    element.classList.toggle("is-minimized", minimized);
    if (!minimized) {
      windows().forEach(function (other) {
        if (other !== this && narrow()) other.element.classList.add("is-minimized");
      }, this);
      if (holder.lastElementChild !== element) {   // (last: the newest place, at the right)
        var html = this.html();
        holder.appendChild(element);
        this.mountEditor(html);   // (moved, its frame is drawn anew)
      }
      layout();
    }
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: {} }));
  };

  Composer.prototype.toggleFull = function (on) {
    var element = this.element;
    var full = on === undefined ? !element.classList.contains("is-full") : on;
    windows().forEach(function (other) {
      if (other !== this && other.element.classList.contains("is-full")) other.element.classList.remove("is-full");
    }, this);
    element.classList.toggle("is-full", full);
    if (full) element.classList.remove("is-minimized");
    setOverlay(full);
    var button = element.querySelector('[data-cm="fullscreen"]');
    var tip = full ? button.dataset.tipOn : button.dataset.tipOff;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
    button.replaceChildren(wm.icon(full ? "restore" : "maximize"));
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
  };

  // Full screen: the whole screen, edge to edge, to see it all well (the browser's own full screen
  // too, when it allows it: the whole page, so the menus and dialogs still open over it). Exit full
  // screen, or Esc, brings it back as it was.
  Composer.prototype.toggleScreen = function (on) {
    var element = this.element;
    var screen = on === undefined ? !element.classList.contains("is-screen") : on;
    if (screen === element.classList.contains("is-screen")) return;
    composers.forEach(function (other) {   // (one at a time)
      if (other !== this && other.element.classList.contains("is-screen")) other.toggleScreen(false);
    }, this);
    element.classList.toggle("is-screen", screen);
    if (screen) element.classList.remove("is-minimized");
    setOverlay(screen || element.classList.contains("is-full"));
    var root = document.documentElement;
    if (screen && root.requestFullscreen && !document.fullscreenElement) {
      root.requestFullscreen().catch(function () {});   // (refused: it fills the window all the same)
    } else if (!screen && document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(function () {});
    }
    var button = element.querySelector('[data-cm="screen"]');
    var tip = screen ? button.dataset.tipOn : button.dataset.tipOff;
    button.dataset.tip = tip;
    button.setAttribute("aria-label", tip);
    button.replaceChildren(wm.icon(screen ? "screen-exit" : "screen-full"));
    document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
  };
  // the browser's full screen left (Esc): the composer too
  document.addEventListener("fullscreenchange", function () {
    if (document.fullscreenElement) return;
    composers.forEach(function (composer) {
      if (composer.element.classList.contains("is-screen")) composer.toggleScreen(false);
    });
  });

  // an inline reply taken to a window of its own
  Composer.prototype.popOut = function () {
    var html = this.html();
    var card = this.element.closest(".wm-read-card");
    if (card) card.classList.remove("has-reply");
    this.element.classList.remove("is-inline");
    holder.appendChild(this.element);
    this.mountEditor(html);
    layout();
    showLimit();
  };

  // --- what its buttons do ---
  Composer.prototype.wire = function () {
    var self = this;
    var element = this.element;
    element.addEventListener("click", function (event) {
      var button = event.target.closest("[data-cm]");
      if (!button || !element.contains(button)) {
        if (element.classList.contains("is-minimized") && event.target.closest("[data-cm-head]")) self.toggleMinimize(false);
        return;
      }
      var action = button.dataset.cm;
      if (action === "minimize") self.toggleMinimize();
      else if (action === "fullscreen") self.toggleFull();
      else if (action === "screen") self.toggleScreen();
      else if (action === "quote") self.foldQuote(!self.quoteFolded);
      else if (action === "close") self.close();
      else if (action === "popout") self.popOut();
      else if (action === "ccbcc") {
        self.showCcBcc(true);
        self.fields.cc.input.focus();
      } else if (action === "send") self.send();
      else if (action === "discard") self.discard();
      else if (action === "attach") element.querySelector("[data-cm-files-input]").click();
      else if (action === "picture") {
        self.saveRange();
        self.replacing = null;
        element.querySelector("[data-cm-picture-input]").click();
      } else if (action === "format") {   // the bar opens down into place; Aa stays lit while it's out
        var shown = button.getAttribute("aria-pressed") !== "true";
        button.setAttribute("aria-pressed", String(shown));
        button.classList.toggle("is-on", shown);
        wm.reveal(element.querySelector("[data-cm-toolbar]"), shown);
        self.fit();
      } else if (action === "link") self.linkDialog(button);
      else if (action === "signature") self.signatureMenu(button);
      else if (action === "important") {
        self.setImportant(!self.important);
        self.changedNow();
        document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: button } }));
      } else if (action === "from") self.fromMenu(button);
    });
    element.querySelector("[data-cm-head]").addEventListener("dblclick", function (event) {
      if (!event.target.closest("[data-cm]") && !element.classList.contains("is-inline")) self.toggleFull();
    });
    this.subject.addEventListener("input", function () {
      self.setTitle();
      self.changedNow();
    });
    this.subject.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        self.frame.contentWindow.focus();
      }
    });
    element.querySelector("[data-cm-files-input]").addEventListener("change", function (event) {
      Array.prototype.forEach.call(event.target.files, function (file) { self.upload(file, false); });
      event.target.value = "";
    });
    element.querySelector("[data-cm-picture-input]").addEventListener("change", function (event) {
      var replacing = self.replacing;   // (Replace picture, from a picture's menu)
      self.replacing = null;
      Array.prototype.forEach.call(event.target.files, function (file, index) {
        if (replacing && index === 0) self.replacePicture(replacing, file);
        else self.insertPicture(file);
      });
      event.target.value = "";
    });
    // files dropped on it
    var drop = element.querySelector("[data-cm-drop]");
    var depth = 0;
    element.addEventListener("dragenter", function (event) {
      if (!hasFiles(event)) return;
      depth++;
      drop.hidden = false;
    });
    element.addEventListener("dragleave", function (event) {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) drop.hidden = true;
    });
    element.addEventListener("dragover", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    element.addEventListener("drop", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      drop.hidden = true;
      Array.prototype.forEach.call(event.dataTransfer.files, function (file) { self.upload(file, false); });
    });
    // the formatting bar
    element.querySelector("[data-cm-toolbar]").addEventListener("mousedown", function (event) {
      if (event.target.closest("button")) event.preventDefault();   // the cursor stays in what it says
    });
    element.querySelector("[data-cm-toolbar]").addEventListener("click", function (event) {
      var format = event.target.closest("[data-format]");
      if (format) {
        self.format(format.dataset.format);
        return;
      }
      var pick = event.target.closest("[data-cm-pick]");
      if (pick) self.pick(pick.dataset.cmPick, pick);
    });
    element.addEventListener("keydown", function (event) {
      self.keys(event);
    });
  };

  function hasFiles(event) {
    return event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") >= 0;
  }

  Composer.prototype.keys = function (event) {
    var mod = event.ctrlKey || event.metaKey;
    if (mod && event.key === "Enter") {
      event.preventDefault();
      this.send();
    } else if (mod && (event.key === "s" || event.key === "S")) {
      event.preventDefault();
      this.save(false);
    } else if (event.key === "Escape" && this.element.classList.contains("is-screen")) {
      event.preventDefault();
      this.toggleScreen(false);
    } else if (event.key === "Escape" && this.element.classList.contains("is-full")) {
      event.preventDefault();
      this.toggleFull(false);
    }
  };

  // the page of what it says: typing, pasting pictures, the keys, the bar's state
  Composer.prototype.wireEditor = function (doc) {
    var self = this;
    if (doc.wmWired) return;
    doc.wmWired = true;
    doc.execCommand("styleWithCSS", false, true);
    doc.execCommand("defaultParagraphSeparator", false, "p");
    doc.addEventListener("input", function () {
      self.checkEmpty();
      self.changedNow();
      self.fit();
    });
    doc.addEventListener("keydown", function (event) {
      var mod = event.ctrlKey || event.metaKey;
      if (mod && event.shiftKey && (event.key === "8" || event.key === "*")) {
        event.preventDefault();
        self.format("insertUnorderedList");
      } else if (mod && event.shiftKey && (event.key === "7" || event.key === "&")) {
        event.preventDefault();
        self.format("insertOrderedList");
      } else if (mod && (event.key === "k" || event.key === "K")) {
        event.preventDefault();
        self.linkDialog(self.element.querySelector('[data-cm="link"]'));
      } else if (mod && event.key === "[") {
        event.preventDefault();
        self.format("outdent");
      } else if (mod && event.key === "]") {
        event.preventDefault();
        self.format("indent");
      } else if (mod && event.key === "\\") {
        event.preventDefault();
        self.format("removeFormat");
      } else {
        self.keys(event);
      }
    });
    doc.addEventListener("paste", function (event) {
      var items = Array.prototype.filter.call(event.clipboardData.files || [], function (file) {
        return /^image\/(png|jpeg|gif|webp)$/.test(file.type);
      });
      if (!items.length) return;
      event.preventDefault();
      self.saveRange();
      items.forEach(function (file) { self.insertPicture(file); });
    });
    doc.addEventListener("selectionchange", function () { self.showState(); });
    // tables made to fit (webmail-tables.js), and a picture's menu on a right-click
    if (self.tables) self.tables.destroy();
    if (wm.tableTools) {
      self.tables = wm.tableTools(self.frame, { changed: function () {
        self.checkEmpty();
        self.changedNow();
        self.fit();
      } });
    }
    doc.addEventListener("contextmenu", function (event) {
      var picture = event.target.nodeType === 1 && event.target.closest("img");
      if (!picture) return;
      event.preventDefault();
      self.pictureMenu(picture, event);
    });
    doc.addEventListener("focus", function () { self.element.classList.add("is-writing"); }, true);
    doc.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (link && (event.ctrlKey || event.metaKey)) window.open(link.href, "_blank", "noopener");
    });
  };

  // the bar shows what the cursor is in: bold, a list...
  Composer.prototype.showState = function () {
    var doc = this.doc();
    if (!doc) return;
    this.element.querySelectorAll("[data-format]").forEach(function (button) {
      var command = button.dataset.format;
      if (["bold", "italic", "underline", "strikeThrough", "insertUnorderedList", "insertOrderedList"].indexOf(command) < 0) return;
      var on = false;
      try {
        on = doc.queryCommandState(command);
      } catch (error) { /* (not in what it says) */ }
      button.setAttribute("aria-pressed", String(on));
      button.classList.toggle("is-on", on);
    });
  };

  Composer.prototype.format = function (command, value) {
    var doc = this.doc();
    if (!doc) return;
    this.frame.contentWindow.focus();
    if (command === "quote") {
      doc.execCommand("formatBlock", false, "blockquote");
    } else {
      doc.execCommand(command, false, value === undefined ? null : value);
    }
    this.checkEmpty();
    this.changedNow();
    this.showState();
    this.fit();
  };

  // fonts, sizes, colours, alignment and tables: small menus from the bar
  Composer.prototype.pick = function (kind, button) {
    var self = this;
    this.saveRange();
    var range = this.savedRange;
    function then(command, value) {
      return function () {
        self.restoreRange(range);
        self.format(command, value);
      };
    }
    if (kind === "font") {
      wm.menu(button, FONTS.map(function (font) {
        return { label: font[0], act: function () {
          then("fontName", font[1])();
          self.element.querySelector("[data-cm-font]").textContent = font[0];
        } };
      }));
    } else if (kind === "size") {
      wm.menu(button, SIZES.map(function (size) {
        return { label: size[0], act: function () {
          then("fontSize", size[1])();
          self.element.querySelector("[data-cm-size]").textContent = size[0];
        } };
      }));
    } else if (kind === "align") {
      wm.menu(button, [
        { label: "Align left", icon: "align-left", act: then("justifyLeft") },
        { label: "Align center", icon: "align-center", act: then("justifyCenter") },
        { label: "Align right", icon: "align-right", act: then("justifyRight") },
      ]);
    } else if (kind === "color" || kind === "back") {
      this.palette(button, function (colour) {
        self.restoreRange(range);
        self.format(kind === "color" ? "foreColor" : "hiliteColor", colour);
        button.style.setProperty("--wm-swatch", colour);
      }, kind === "back");
    } else if (kind === "table") {
      this.tablePicker(button, function (rows, cols) {
        self.restoreRange(range);
        var cells = "";
        for (var row = 0; row < rows; row++) {
          cells += "<tr>";
          for (var col = 0; col < cols; col++) cells += "<td><br></td>";
          cells += "</tr>";
        }
        self.format("insertHTML", '<table style="border-collapse:collapse"><tbody>' + cells + "</tbody></table><p><br></p>");
      });
    }
  };

  function popover(button, className) {
    var mask = document.createElement("div");
    mask.className = "wm-menu-mask";
    var box = document.createElement("div");
    box.className = "wm-menu-pop " + className;
    document.body.appendChild(mask);
    document.body.appendChild(box);
    function close() {
      mask.remove();
      box.remove();
      document.removeEventListener("keydown", keys, true);
    }
    function keys(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
    }
    mask.addEventListener("mousedown", function (event) {
      event.preventDefault();
      close();
    });
    document.addEventListener("keydown", keys, true);
    return { box: box, close: close, place: function () {
      var rect = button.getBoundingClientRect();
      var width = box.offsetWidth, height = box.offsetHeight;
      var top = rect.top - height - 6 >= 8 ? rect.top - height - 6 : Math.min(rect.bottom + 6, window.innerHeight - height - 8);
      box.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + "px";
      box.style.top = Math.max(8, top) + "px";
    } };
  }

  Composer.prototype.palette = function (button, chosen, highlight) {
    var pop = popover(button, "wm-cm-palette");
    var colours = highlight ? ["transparent"].concat(COLORS.slice(5)) : COLORS;
    colours.forEach(function (colour) {
      var swatch = document.createElement("button");
      swatch.type = "button";
      swatch.className = "wm-cm-swatch" + (colour === "transparent" ? " is-none" : "");
      swatch.style.background = colour;
      swatch.setAttribute("aria-label", colour === "transparent" ? "No highlight" : colour);
      swatch.title = colour === "transparent" ? "No highlight" : colour;
      swatch.addEventListener("mousedown", function (event) { event.preventDefault(); });
      swatch.addEventListener("click", function () {
        pop.close();
        chosen(colour);
      });
      pop.box.appendChild(swatch);
    });
    pop.place();
    pop.box.querySelector("button").focus();
  };

  Composer.prototype.tablePicker = function (button, chosen) {
    var pop = popover(button, "wm-cm-table");
    var grid = document.createElement("div");
    grid.className = "wm-cm-table-grid";
    var label = document.createElement("p");
    label.className = "wm-cm-table-size";
    label.textContent = "1 × 1";
    for (var row = 1; row <= 8; row++) {
      for (var col = 1; col <= 8; col++) {
        var cell = document.createElement("button");
        cell.type = "button";
        cell.dataset.row = row;
        cell.dataset.col = col;
        cell.setAttribute("aria-label", row + " by " + col);
        grid.appendChild(cell);
      }
    }
    grid.addEventListener("mouseover", function (event) {
      var cell = event.target.closest("button");
      if (!cell) return;
      grid.querySelectorAll("button").forEach(function (other) {
        other.classList.toggle("is-on", Number(other.dataset.row) <= Number(cell.dataset.row) && Number(other.dataset.col) <= Number(cell.dataset.col));
      });
      label.textContent = cell.dataset.row + " × " + cell.dataset.col;
    });
    grid.addEventListener("mousedown", function (event) { event.preventDefault(); });
    grid.addEventListener("click", function (event) {
      var cell = event.target.closest("button");
      if (!cell) return;
      pop.close();
      chosen(Number(cell.dataset.row), Number(cell.dataset.col));
    });
    pop.box.appendChild(grid);
    pop.box.appendChild(label);
    pop.place();
  };

  // Insert link: its address, and the words it shows (the words chosen, when some are)
  Composer.prototype.linkDialog = function (button) {
    var self = this;
    this.saveRange();
    var range = this.savedRange;
    var doc = this.doc();
    var chosenText = range ? range.toString() : "";
    var existing = range && range.commonAncestorContainer && (range.commonAncestorContainer.nodeType === 1 ?
      range.commonAncestorContainer : range.commonAncestorContainer.parentElement);
    existing = existing && existing.closest ? existing.closest("a[href]") : null;
    var pop = popover(button, "wm-cm-link");
    pop.box.innerHTML = '<form class="wm-cm-link-form"><label><span>Link</span><input type="text" name="url" placeholder="https://" autocomplete="off"></label>' +
      '<label><span>Text to display</span><input type="text" name="text" autocomplete="off"></label>' +
      '<div class="wm-cm-link-actions"><button type="button" class="wm-button is-ghost is-small" data-cancel>Cancel</button>' +
      '<button type="submit" class="wm-button is-small">Insert</button></div></form>';
    var form = pop.box.querySelector("form");
    form.url.value = existing ? existing.getAttribute("href") : "";
    form.text.value = existing ? existing.textContent : chosenText;
    pop.place();
    form.url.focus();
    form.querySelector("[data-cancel]").addEventListener("click", function () {
      pop.close();
      self.restoreRange(range);
    });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var url = form.url.value.trim();
      if (!url) {
        form.url.focus();
        return;
      }
      if (!/^(https?:|mailto:|tel:)/i.test(url)) url = /^[^\s@]+@[^\s@]+$/.test(url) ? "mailto:" + url : "https://" + url;
      var words = form.text.value.trim() || url;
      pop.close();
      self.restoreRange(range);
      if (existing) {
        existing.setAttribute("href", url);
        existing.textContent = words;
        self.changedNow();
      } else if (chosenText && words === chosenText) {
        self.format("createLink", url);
      } else {
        var link = doc.createElement("a");
        link.href = url;
        link.textContent = words;
        self.format("insertHTML", link.outerHTML + "&nbsp;");
      }
    });
  };

  // the signature: one of the mailbox's, none, or to its settings
  Composer.prototype.signatureMenu = function (button) {
    var self = this;
    var doc = this.doc();
    if (!doc) return;
    var current = doc.querySelector(".wm-signature");
    var currentId = current ? current.getAttribute("data-signature") : null;
    var items = this.signatures.map(function (signature) {
      return { label: signature.name, switchOn: String(signature.id) === currentId, act: function () { self.useSignature(signature); } };
    });
    if (items.length) items.push("-");
    items.push({ label: "No signature", act: function () { self.useSignature(null); } });
    items.push({ label: "Manage signatures", icon: "settings", act: function () { window.open(data().settingsUrl, "_blank", "noopener"); } });
    wm.menu(button, items);
  };

  Composer.prototype.useSignature = function (signature) {
    var doc = this.doc();
    if (!doc) return;
    var block = doc.querySelector(".wm-signature");
    if (!signature) {
      if (block) block.remove();
    } else {
      if (!block) {
        block = doc.createElement("div");
        block.className = "wm-signature";
        var quote = doc.querySelector("blockquote.wm-quote");
        var spacer = doc.createElement("p");
        spacer.innerHTML = "<br>";
        if (quote) {
          doc.body.insertBefore(spacer, quote);
          doc.body.insertBefore(block, quote);
        } else {
          doc.body.appendChild(spacer);
          doc.body.appendChild(block);
        }
      }
      block.setAttribute("data-signature", signature.id);
      block.innerHTML = signature.html;
    }
    this.checkEmpty();
    this.changedNow();
    this.fit();
  };

  Composer.prototype.fromMenu = function (button) {
    var self = this;
    wm.menu(button, this.froms.map(function (one) {
      return { label: (one.name ? one.name + " <" + one.email + ">" : one.email), switchOn: one.email === self.from, act: function () {
        self.setFrom(one.email);
        self.changedNow();
      } };
    }));
  };

  // --- To, Cc and Bcc: an address a chip ---
  var ADDRESS = /^[^@\s<>(),;:"[\]\\]+@[^@\s<>(),;:"[\]\\]+\.[^@\s<>(),;:"[\]\\]+$/;

  function Tags(composer, field) {
    var self = this;
    this.composer = composer;
    this.field = field;
    this.box = composer.element.querySelector('[data-cm-tags="' + field + '"]');
    this.input = composer.element.querySelector('[data-cm-input="' + field + '"]');
    this.list = [];   // {name, email, element}
    this.suggestions = null;
    this.asking = null;
    this.timer = null;
    this.box.addEventListener("click", function (event) {
      if (event.target === self.box) self.input.focus();
    });
    this.input.addEventListener("keydown", function (event) { self.keys(event); });
    this.input.addEventListener("input", function () {
      var value = self.input.value;
      if (/[,;]/.test(value)) {
        self.commit();
        return;
      }
      clearTimeout(self.timer);
      self.timer = setTimeout(function () { self.suggest(); }, 180);
      self.input.style.width = Math.max(40, Math.min(value.length * 8 + 30, self.box.clientWidth - 16)) + "px";
    });
    this.input.addEventListener("paste", function (event) {
      var text = (event.clipboardData || window.clipboardData).getData("text");
      if (!/[,;\n]/.test(text)) return;
      event.preventDefault();
      self.input.value = text;
      self.commit();
    });
    this.input.addEventListener("blur", function () {
      setTimeout(function () {
        if (document.activeElement !== self.input) {
          self.closeSuggestions();
          self.commit();
        }
      }, 150);
    });
  }

  Tags.prototype.people = function () {
    return this.list.map(function (person) { return { name: person.name || null, email: person.email }; });
  };
  Tags.prototype.wrong = function () {
    return this.list.filter(function (person) { return !ADDRESS.test(person.email); }).map(function (person) { return person.email; });
  };

  // what's typed, as chips: "Name <a@b.c>", a@b.c, several with commas
  Tags.prototype.commit = function () {
    var self = this;
    var text = this.input.value;
    this.input.value = "";
    this.input.style.width = "";
    text.split(/[,;\n]+/).forEach(function (piece) {
      piece = piece.trim();
      if (!piece) return;
      var match = /^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/.exec(piece);
      self.add(match ? { name: match[1].trim() || null, email: match[2].trim() } : { name: null, email: piece });
    });
  };

  Tags.prototype.add = function (person, quiet) {
    var self = this;
    var email = (person.email || "").trim();
    if (!email) return;
    var all = ["to", "cc", "bcc"].reduce(function (found, field) { return found.concat(self.composer.fields[field] ? self.composer.fields[field].list : []); }, []);
    if (all.some(function (other) { return other.email.toLowerCase() === email.toLowerCase(); })) {
      if (!quiet) wm.toast("You have already added that email address", { warning: true });
      return;
    }
    var chip = document.createElement("span");
    var wrong = !ADDRESS.test(email);
    chip.className = "wm-cm-tag" + (wrong ? " is-wrong" : "");
    chip.title = wrong ? "Invalid email address" : (person.name ? person.name + " <" + email + ">" : email);
    var words = document.createElement("span");
    words.className = "wm-cm-tag-text";
    words.textContent = person.name || email;
    chip.appendChild(words);
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "wm-cm-tag-x";
    remove.setAttribute("aria-label", "Remove " + email);
    remove.appendChild(wm.icon("close"));
    chip.appendChild(remove);
    var entry = { name: person.name || null, email: email, element: chip };
    remove.addEventListener("click", function (event) {
      event.stopPropagation();
      self.remove(entry);
      self.input.focus();
    });
    chip.addEventListener("dblclick", function () {   // put back to be changed
      self.remove(entry);
      self.input.value = entry.name ? entry.name + " <" + entry.email + ">" : entry.email;
      self.input.focus();
    });
    this.box.insertBefore(chip, this.input);
    this.list.push(entry);
    if (!quiet) this.composer.changedNow();
  };

  Tags.prototype.remove = function (entry) {
    this.list = this.list.filter(function (other) { return other !== entry; });
    entry.element.remove();
    this.composer.changedNow();
  };

  Tags.prototype.keys = function (event) {
    var open = this.suggestions && !this.suggestions.hidden;
    if (open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      var items = Array.prototype.slice.call(this.suggestions.querySelectorAll("button"));
      var at = items.indexOf(this.suggestions.querySelector(".is-active"));
      var next = (at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach(function (item, index) { item.classList.toggle("is-active", index === next); });
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      var active = open && this.suggestions.querySelector(".is-active");
      if (active) {
        event.preventDefault();
        active.click();
        return;
      }
      if (this.input.value.trim()) {
        event.preventDefault();
        this.commit();
        this.closeSuggestions();
      }
    } else if (event.key === "Backspace" && !this.input.value && this.list.length) {
      this.remove(this.list[this.list.length - 1]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      this.closeSuggestions();
    }
  };

  Tags.prototype.suggest = function () {
    var self = this;
    var typed = this.input.value.trim();
    if (this.asking) this.asking.abort();
    if (typed.length < 1) {
      this.closeSuggestions();
      return;
    }
    var ask = this.asking = new AbortController();
    wm.request(data().suggestUrl + "?q=" + encodeURIComponent(typed), { signal: ask.signal, quiet: true }).then(function (answer) {
      if (self.asking !== ask) return;
      self.asking = null;
      self.showSuggestions(answer.people || []);
    }, function () {});
  };

  Tags.prototype.showSuggestions = function (people) {
    var self = this;
    var have = {};
    ["to", "cc", "bcc"].forEach(function (field) {
      self.composer.fields[field].list.forEach(function (person) { have[person.email.toLowerCase()] = true; });
    });
    people = people.filter(function (person) { return !have[person.email.toLowerCase()]; });
    if (!people.length) {
      this.closeSuggestions();
      return;
    }
    if (!this.suggestions) {
      this.suggestions = document.createElement("div");
      this.suggestions.className = "wm-cm-suggest";
      this.suggestions.setAttribute("role", "listbox");
      this.box.parentElement.appendChild(this.suggestions);
    }
    this.suggestions.innerHTML = "";
    people.forEach(function (person, index) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "wm-cm-suggest-item" + (index === 0 ? " is-active" : "");
      item.setAttribute("role", "option");
      var badge = document.createElement("span");
      badge.className = "wm-cm-suggest-badge";
      badge.textContent = (person.name || person.email).slice(0, 1).toUpperCase();
      var words = document.createElement("span");
      words.className = "wm-cm-suggest-words";
      var name = document.createElement("span");
      name.className = "wm-cm-suggest-name";
      name.textContent = person.name || person.email;
      var address = document.createElement("span");
      address.className = "wm-cm-suggest-email";
      address.textContent = person.email;
      words.appendChild(name);
      if (person.name) words.appendChild(address);
      item.appendChild(badge);
      item.appendChild(words);
      item.addEventListener("mousedown", function (event) { event.preventDefault(); });
      item.addEventListener("click", function () {
        self.input.value = "";
        self.add(person);
        self.closeSuggestions();
        self.input.focus();
      });
      self.suggestions.appendChild(item);
    });
    this.suggestions.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
  };

  Tags.prototype.closeSuggestions = function () {
    if (this.suggestions) this.suggestions.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
  };

  // --- opening one ---
  function start(options) {
    var query = "?kind=" + encodeURIComponent(options.kind || "new") + (options.id ? "&id=" + encodeURIComponent(options.id) : "");
    return wm.request(data().startUrl + query, { failTitle: "Couldn't open the composer" });
  }

  function openWindow(options) {
    options = options || {};
    if (windows().length >= MAX_WINDOWS) {
      wm.board("Compose limit exceeded", "You cannot open more than " + MAX_WINDOWS + " drafts at the same time");
      return null;
    }
    if (options.kind === "draft" && options.id) {   // open already: that one comes forward
      var open = composers.filter(function (composer) { return composer.draft === options.id; })[0];
      if (open) {
        open.toggleMinimize(false);
        return open;
      }
    }
    var composer = new Composer(options);
    composers.push(composer);
    composer.element.classList.add("is-loading");
    holder.appendChild(composer.element);
    layout();
    showLimit();
    start(options).then(function (started) {
      composer.element.classList.remove("is-loading");
      composer.fill(started);
      (options.to || []).forEach(function (address) { composer.fields.to.add({ email: address }, true); });
      if (options.subject) composer.subject.value = options.subject;
      if (options.body) composer.pendingHtml = options.body;
      composer.setTitle();
      focusFirst(composer);
    }, function () {
      composer.remove();
    });
    return composer;
  }

  function focusFirst(composer) {
    setTimeout(function () {
      if (!composer.fields.to.list.length) composer.fields.to.input.focus();
      else if (!composer.subject.value) composer.subject.focus();
      else composer.frame.contentWindow && composer.frame.contentWindow.focus();
    }, 60);
  }

  // A reply or forward under the open message: in place of its reply buttons
  function openInline(kind, id) {
    var card = document.querySelector('[data-wm-read][data-id="' + CSS.escape(id) + '"] .wm-read-card');
    if (!card || narrow()) return openWindow({ kind: kind, id: id });
    var already = composers.filter(function (composer) { return composer.element.classList.contains("is-inline"); })[0];
    var go = already ? already.close() : Promise.resolve(true);
    go.then(function (closed) {
      if (!closed) return;
      var composer = new Composer({ kind: kind, id: id });
      composer.quoteFolded = kind !== "forward";   // (a forward shows what it passes on)
      composer.element.classList.add("is-inline", "is-loading");
      composers.push(composer);
      card.classList.add("has-reply");
      card.appendChild(composer.element);
      start({ kind: kind, id: id }).then(function (started) {
        composer.element.classList.remove("is-loading");
        composer.fill(started);
        composer.element.querySelector("[data-cm-inline-title]").textContent = started.reply ? started.reply.title : "";
        composer.element.scrollIntoView({ block: "nearest", behavior: wm.reduceMotion ? "auto" : "smooth" });
        if (kind === "forward") composer.fields.to.input.focus();
        else setTimeout(function () { composer.frame.contentWindow.focus(); }, 120);
      }, function () {
        composer.remove();
      });
    });
  }

  // leaving the message it answers (another opens, the pane closes, another folder): what it
  // says is kept at once, then it's saved quietly to Drafts, and goes
  function leaveInline() {
    composers.filter(function (composer) { return composer.element.classList.contains("is-inline"); }).forEach(function (composer) {
      composers = composers.filter(function (other) { return other !== composer; });
      if (composer.isEmpty()) return;
      composer.pendingHtml = composer.html();
      composer.frame.remove();   // (what it says is in pendingHtml now)
      composer.changed = true;
      composer.save(true).then(function (saved) {
        if (saved && composer.draft) wm.toast("Your message has been successfully saved to drafts");
      });
    });
  }
  document.addEventListener("wm:leaving", leaveInline);

  function fromMessage(kind, id) {
    if (kind === "edit-draft") return openWindow({ kind: "draft", id: id });
    var map = { reply: "reply", "reply-all": "all", forward: "forward" };
    return openInline(map[kind] || "reply", id);
  }

  // a mailto: link (in a message): a new message, filled in from it
  function mailto(href) {
    var rest = href.replace(/^mailto:/i, "");
    var parts = rest.split("?");
    var to = decodeURIComponent(parts[0] || "").split(",").filter(Boolean);
    var fields = {};
    (parts[1] || "").split("&").forEach(function (pair) {
      var bits = pair.split("=");
      if (bits[0]) fields[decodeURIComponent(bits[0]).toLowerCase()] = decodeURIComponent((bits[1] || "").replace(/\+/g, " "));
    });
    var composer = openWindow({ kind: "new", to: to, subject: fields.subject });
    if (composer && fields.body) {
      var body = fields.body.replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }).replace(/\n/g, "<br>");
      composer.pendingHtml = "<p>" + body + "</p>";
    }
  }

  var compose = document.querySelector("[data-wm-compose]");
  if (compose) compose.addEventListener("click", function () { openWindow({ kind: "new" }); });

  // before leaving the page: what's being written is kept
  window.addEventListener("beforeunload", function (event) {
    var unsaved = composers.some(function (composer) { return composer.changed && !composer.isEmpty(); });
    if (!unsaved) return;
    composers.forEach(function (composer) {
      if (composer.changed && !composer.isEmpty() && navigator.sendBeacon && !composer.uploading()) {
        // (a last quiet save: sendBeacon can't carry the page's token, so it's asked for with fetch keepalive)
        try {
          fetch(data().saveUrl, { method: "POST", keepalive: true, credentials: "same-origin",
                                  headers: { "Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.content : "" },
                                  body: JSON.stringify(composer.message(true)) });
        } catch (error) { /* (the page is going) */ }
      }
    });
    event.preventDefault();
    event.returnValue = "";
  });

  document.addEventListener("someless:theme", function () {
    composers.forEach(function (composer) {
      var doc = composer.doc();
      if (!doc) return;
      composer.mountEditor(composer.html());
    });
  });

  // opened from another app (Contacts' "Send email"): /mail/inbox?compose=mailto:…
  var asked = new URLSearchParams(location.search).get("compose");
  if (asked && /^mailto:/i.test(asked)) {
    var here = new URL(location.href);
    here.searchParams.delete("compose");
    history.replaceState(history.state, "", here.pathname + here.search + here.hash);
    setTimeout(function () { mailto(asked); }, 0);
  }

  window.wm.compose = { open: openWindow, fromMessage: fromMessage, mailto: mailto, composers: function () { return composers; } };
})();

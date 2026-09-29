// A small editor of formatted text for Settings (a signature, the auto-reply's message), with
// PrivateEmail's bar: undo and redo, the font and its size, bold, italics, underline and
// strikethrough, a picture and a link, the text's colour and highlight, lists, alignment and more.
// The words are in a page of their own (a frame where no script runs).
//   var editor = wm.editor(holder, {html, placeholder, onChange, pictures})
//   editor.html(), editor.set(html), editor.focus(), editor.text()
// holder: an element with [data-editor-bar] (webmail-editor-bar.html) and an iframe
// [data-editor-frame] (sandbox="allow-same-origin").
//
// A picture (the bar's button, pasted or dropped) goes in as it is when it's small (nothing
// lost); a bigger one is made 600 pixels wide, the most a signature needs. Clicked, it can be
// made smaller or larger, or taken out. It's kept inside the signature (data:), and sent with a
// message as a part of its own (compose.py).
(function () {
  if (!window.wm) return;
  var FONTS = [["Arial", "Arial, Helvetica, sans-serif"], ["Bookman", "'Bookman Old Style', serif"],
               ["Comic Sans", "'Comic Sans MS', 'Comic Sans', cursive"], ["Courier New", "'Courier New', Courier, monospace"],
               ["Georgia", "Georgia, serif"], ["Palatino", "'Palatino Linotype', 'Book Antiqua', Palatino, serif"],
               ["Tahoma", "Tahoma, Geneva, sans-serif"], ["Times New Roman", "'Times New Roman', Times, serif"],
               ["Trebuchet MS", "'Trebuchet MS', sans-serif"], ["Verdana", "Verdana, Geneva, sans-serif"]];
  var SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36];
  var COLORS = ["#000000", "#434343", "#666666", "#999999", "#cccccc", "#ffffff", "#e03131", "#f76707", "#f59f00", "#2f9e44",
                "#1971c2", "#6741d9", "#c2255c", "#ffc9c9", "#ffe8cc", "#fff3bf", "#d3f9d8", "#d0ebff", "#e5dbff", "#fcc2d7"];
  var PICTURE_TYPES = /^image\/(png|jpeg|gif|webp)$/;
  var WIDEST = 600;                 // px: a picture wider is made this wide
  var KEEP_AS_IS = 400 * 1024;      // bytes: a picture this small (and not too wide) goes in untouched
  var BIGGEST_FILE = 15 * 1024 * 1024;

  function page(placeholder) {
    var dark = document.documentElement.dataset.theme === "dark";
    return '<!doctype html><html><head><meta charset="utf-8"><style>' +
      "html{color-scheme:" + (dark ? "dark" : "light") + "}" +
      "body{margin:0;padding:12px 14px;min-height:calc(100vh - 24px);box-sizing:border-box;font:14px/1.55 Arial,Helvetica,sans-serif;" +
      "color:" + (dark ? "#e3e7f4" : "#1c1f24") + ";overflow-wrap:anywhere;outline:none}" +
      "body.is-empty::before{content:" + JSON.stringify(placeholder || "") + ";position:absolute;color:" + (dark ? "#7c87a9" : "#878d98") +
      ";pointer-events:none}p{margin:0}a{color:" + (dark ? "#8cb4ff" : "#3b63e6") + "}" +
      "img{max-width:100%;height:auto;cursor:pointer}img.is-picked{outline:2px solid #3b63e6;outline-offset:2px}" +
      "blockquote{margin:0 0 0 .8ex;padding-left:1ex;border-left:2px solid " + (dark ? "#3b4777" : "#ccc") + "}" +
      "</style></head><body contenteditable=\"true\" class=\"is-empty\"></body></html>";
  }

  // a picture file, ready to go in: {src, width}
  function prepare(file) {
    return new Promise(function (resolve, reject) {
      if (!PICTURE_TYPES.test(file.type || "")) {
        reject(new Error("Choose a PNG, JPG, GIF or WebP picture."));
        return;
      }
      if (file.size > BIGGEST_FILE) {
        reject(new Error("This picture is too large. Choose one under 15 MB."));
        return;
      }
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("This picture can't be read. Choose another one.")); };
      reader.onload = function () {
        var image = new Image();
        image.onerror = function () { reject(new Error("This picture can't be read. Choose another one.")); };
        image.onload = function () {
          var width = image.naturalWidth, height = image.naturalHeight;
          if (width <= WIDEST && file.size <= KEEP_AS_IS) {   // small already: in as it is, nothing lost
            resolve({ src: reader.result, width: width });
            return;
          }
          var scale = Math.min(1, WIDEST / width);
          var canvas = document.createElement("canvas");
          canvas.width = Math.round(width * scale);
          canvas.height = Math.round(height * scale);
          canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
          var photo = file.type === "image/jpeg";
          var made = canvas.toDataURL(photo ? "image/jpeg" : "image/png", 0.92);
          if (!photo && made.length > 700 * 1024) made = canvas.toDataURL("image/jpeg", 0.92);   // (a photo saved as PNG)
          resolve({ src: made, width: canvas.width });
        };
        image.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  wm.editor = function (holder, options) {
    options = options || {};
    var frame = holder.querySelector("[data-editor-frame]");
    var bar = holder.querySelector("[data-editor-bar]");
    var pictureInput = holder.querySelector("[data-editor-picture-input]");
    var pictures = !!pictureInput && options.pictures !== false;
    var pending = options.html || "";
    var savedRange = null;
    var api = {};

    function doc() {
      var inner = frame.contentDocument;
      return inner && inner.body && inner.body.isContentEditable ? inner : null;
    }
    function empty() {
      var inner = doc();
      if (inner) inner.body.classList.toggle("is-empty", !inner.body.textContent.trim() && !inner.body.querySelector("img, li, hr"));
    }
    function changed() {
      empty();
      showState();
      if (options.onChange) options.onChange();
    }
    function saveRange() {
      var inner = doc();
      var selection = inner && inner.getSelection();
      savedRange = selection && selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    }
    function restoreRange() {
      var inner = doc();
      if (!inner) return;
      frame.contentWindow.focus();
      if (savedRange) {
        var selection = inner.getSelection();
        selection.removeAllRanges();
        selection.addRange(savedRange);
      }
    }
    function format(command, value) {
      var inner = doc();
      if (!inner) return;
      frame.contentWindow.focus();
      inner.execCommand(command, false, value === undefined ? null : value);
      changed();
    }

    // the font's size, in pixels (the browser's own sizes are 1 to 7: the biggest, made the one chosen)
    function setSize(pixels) {
      var inner = doc();
      if (!inner) return;
      restoreRange();
      inner.execCommand("styleWithCSS", false, false);
      inner.execCommand("fontSize", false, "7");
      inner.execCommand("styleWithCSS", false, true);
      inner.querySelectorAll('font[size="7"]').forEach(function (font) {
        var span = inner.createElement("span");
        span.style.fontSize = pixels + "px";
        while (font.firstChild) span.appendChild(font.firstChild);
        font.replaceWith(span);
      });
      changed();
    }

    // what the bar shows: the font and size where the cursor is, the styles on
    function showState() {
      var inner = doc();
      if (!inner || !bar) return;
      ["bold", "italic", "underline", "strikeThrough", "insertUnorderedList", "insertOrderedList"].forEach(function (command) {
        var button = bar.querySelector('[data-format="' + command + '"]');
        if (!button) return;
        var on = false;
        try { on = inner.queryCommandState(command); } catch (error) { on = false; }
        button.setAttribute("aria-pressed", String(!!on));
      });
      var selection = inner.getSelection();
      var node = selection && selection.anchorNode;
      if (node && node.nodeType === 3) node = node.parentNode;
      if (!node || !inner.body.contains(node)) node = inner.body;
      var style = frame.contentWindow.getComputedStyle(node);
      var family = (style.fontFamily || "").split(",")[0].replace(/['"]/g, "").trim().toLowerCase();
      var font = FONTS.filter(function (one) { return one[1].toLowerCase().indexOf(family) >= 0; })[0];
      var fontLabel = bar.querySelector("[data-editor-font]");
      var sizeLabel = bar.querySelector("[data-editor-size]");
      if (fontLabel) fontLabel.textContent = font ? font[0] : "Arial";
      if (sizeLabel) sizeLabel.textContent = String(Math.round(parseFloat(style.fontSize) || 14));
    }

    function mount() {
      frame.addEventListener("load", function onLoad() {
        frame.removeEventListener("load", onLoad);
        var inner = frame.contentDocument;
        inner.body.innerHTML = pending;
        inner.execCommand("styleWithCSS", false, true);
        inner.addEventListener("input", changed);
        inner.addEventListener("keydown", function (event) {
          var mod = event.ctrlKey || event.metaKey;
          if (mod && (event.key === "k" || event.key === "K")) {
            event.preventDefault();
            link();
          }
        });
        inner.addEventListener("selectionchange", showState);
        inner.addEventListener("keyup", showState);
        inner.addEventListener("mouseup", showState);
        inner.addEventListener("click", function (event) {
          if (event.target.tagName === "IMG") pictureMenu(event.target);
        });
        inner.addEventListener("paste", function (event) {
          var files = Array.prototype.filter.call((event.clipboardData && event.clipboardData.files) || [], function (file) {
            return /^image\//.test(file.type);
          });
          if (!files.length) return;
          event.preventDefault();
          if (pictures) files.forEach(addPicture);
        });
        inner.addEventListener("dragover", function (event) {
          if (event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") >= 0) event.preventDefault();
        });
        inner.addEventListener("drop", function (event) {
          var files = Array.prototype.filter.call((event.dataTransfer && event.dataTransfer.files) || [], function (file) {
            return /^image\//.test(file.type);
          });
          if (!files.length) return;
          event.preventDefault();
          if (pictures) files.forEach(addPicture);
        });
        empty();
        showState();
      });
      frame.srcdoc = page(options.placeholder);
    }

    // --- pictures ---
    function addPicture(file) {
      var holderOfLoader = holder.querySelector(".wm-editor-frame") ? holder : null;
      if (holderOfLoader) wm.loading(holder, true);
      prepare(file).then(function (ready) {
        wm.loading(holder, false);
        restoreRange();
        var width = Math.min(ready.width, WIDEST);
        format("insertHTML", '<img src="' + ready.src + '" width="' + width + '" alt="">');
      }, function (error) {
        wm.loading(holder, false);
        wm.board("The picture wasn't added", error.message);
      });
    }
    function pictureMenu(picture) {
      var inner = doc();
      inner.querySelectorAll("img.is-picked").forEach(function (one) { one.classList.remove("is-picked"); });
      picture.classList.add("is-picked");
      var outer = frame.getBoundingClientRect();
      var box = picture.getBoundingClientRect();
      var natural = Math.min(picture.naturalWidth || WIDEST, WIDEST);
      function size(share) {
        return function () {
          picture.setAttribute("width", String(Math.max(16, Math.round(natural * share))));
          picture.removeAttribute("height");
          picture.style.width = "";
          picture.style.height = "";
          changed();
        };
      }
      wm.menu({ x: outer.left + box.left, y: outer.top + box.bottom + 6 }, [
        { label: "Small", icon: "image", act: size(0.25) },
        { label: "Medium", icon: "image", act: size(0.5) },
        { label: "Large", icon: "image", act: size(0.75) },
        { label: "Original size", icon: "image", act: size(1) },
        "-",
        { label: "Remove picture", icon: "trash", danger: true, act: function () { picture.remove(); changed(); } },
      ], { onClose: function () { picture.classList.remove("is-picked"); } });
    }
    if (pictureInput) {
      pictureInput.addEventListener("change", function () {
        Array.prototype.forEach.call(pictureInput.files || [], addPicture);
        pictureInput.value = "";
      });
    }

    // Insert link: a small form under the bar's link button, its address and (with nothing
    // chosen) the words it shows
    function link() {
      var inner = doc();
      if (!inner) return;
      var selection = inner.getSelection();
      var range = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
      var chosen = range && !range.collapsed;
      var button = bar && bar.querySelector("[data-editor-link]");
      var mask = document.createElement("div");
      mask.className = "wm-menu-mask";
      var box = document.createElement("form");
      box.className = "wm-menu-pop wm-cm-link wm-cm-link-form";
      box.innerHTML = '<label><span>Link</span><input type="text" name="url" placeholder="https://" autocomplete="off"></label>' +
        (chosen ? "" : '<label><span>Text to display</span><input type="text" name="text" autocomplete="off"></label>') +
        '<div class="wm-cm-link-actions"><button type="button" class="wm-button is-ghost is-small" data-cancel>Cancel</button>' +
        '<button type="submit" class="wm-button is-small">Insert</button></div>';
      document.body.appendChild(mask);
      document.body.appendChild(box);
      var place = (button || frame).getBoundingClientRect();
      box.style.left = Math.max(8, Math.min(place.left, window.innerWidth - box.offsetWidth - 8)) + "px";
      box.style.top = Math.min(place.bottom + 6, window.innerHeight - box.offsetHeight - 8) + "px";
      box.url.focus();
      function close() {
        mask.remove();
        box.remove();
      }
      mask.addEventListener("mousedown", function (event) {
        event.preventDefault();
        close();
      });
      box.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          event.preventDefault();
          close();
        }
      });
      box.querySelector("[data-cancel]").addEventListener("click", close);
      box.addEventListener("submit", function (event) {
        event.preventDefault();
        var address = box.url.value.trim();
        if (!address) return;
        if (!/^(https?:|mailto:|tel:)/i.test(address)) address = /^[^\s@]+@[^\s@]+$/.test(address) ? "mailto:" + address : "https://" + address;
        var words = chosen ? "" : (box.text.value.trim() || address);
        close();
        frame.contentWindow.focus();
        if (range) {
          selection.removeAllRanges();
          selection.addRange(range);
        }
        if (chosen) {
          format("createLink", address);
        } else {
          var made = inner.createElement("a");
          made.href = address;
          made.textContent = words;
          format("insertHTML", made.outerHTML + "&nbsp;");
        }
      });
    }

    // the colours: a palette of swatches under the button
    function palette(button, pick, back) {
      var mask = document.createElement("div");
      mask.className = "wm-menu-mask";
      var box = document.createElement("div");
      box.className = "wm-menu-pop wm-palette";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-label", back ? "Highlight color" : "Text color");
      COLORS.forEach(function (colour) {
        var swatch = document.createElement("button");
        swatch.type = "button";
        swatch.className = "wm-palette-swatch";
        swatch.style.setProperty("--swatch", colour);
        swatch.setAttribute("aria-label", colour);
        swatch.addEventListener("click", function () {
          close();
          pick(colour);
        });
        box.appendChild(swatch);
      });
      var none = document.createElement("button");
      none.type = "button";
      none.className = "wm-palette-none";
      none.textContent = back ? "No highlight" : "Automatic";
      none.addEventListener("click", function () {
        close();
        pick(back ? "transparent" : "inherit");
      });
      box.appendChild(none);
      document.body.appendChild(mask);
      document.body.appendChild(box);
      var place = button.getBoundingClientRect();
      box.style.left = Math.max(8, Math.min(place.left, window.innerWidth - box.offsetWidth - 8)) + "px";
      box.style.top = Math.min(place.bottom + 6, window.innerHeight - box.offsetHeight - 8) + "px";
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
    }

    function pick(kind, button) {
      saveRange();
      function then(command, value) {
        return function () {
          restoreRange();
          format(command, value);
        };
      }
      if (kind === "font") {
        wm.menu(button, FONTS.map(function (font) {
          return { label: font[0], act: then("fontName", font[1]) };
        }));
      } else if (kind === "size") {
        wm.menu(button, SIZES.map(function (pixels) {
          return { label: String(pixels), act: function () { setSize(pixels); } };
        }));
      } else if (kind === "color" || kind === "back") {
        palette(button, function (colour) {
          restoreRange();
          format(kind === "color" ? "foreColor" : "hiliteColor", colour);
          if (colour !== "inherit" && colour !== "transparent") button.style.setProperty("--wm-swatch", colour);
        }, kind === "back");
      } else if (kind === "align") {
        wm.menu(button, [
          { label: "Align left", icon: "align-left", act: then("justifyLeft") },
          { label: "Align center", icon: "align-center", act: then("justifyCenter") },
          { label: "Align right", icon: "align-right", act: then("justifyRight") },
          { label: "Justify", icon: "align-left", act: then("justifyFull") },
        ]);
      } else if (kind === "more") {
        wm.menu(button, [
          { label: "Indent less", icon: "indent-less", act: then("outdent") },
          { label: "Indent more", icon: "indent-more", act: then("indent") },
          { label: "Quote", icon: "quote", act: then("formatBlock", "blockquote") },
          { label: "Horizontal line", icon: "format", act: then("insertHorizontalRule") },
          "-",
          { label: "Remove formatting", icon: "clear-format", act: then("removeFormat") },
        ]);
      }
    }

    if (bar) {
      bar.addEventListener("mousedown", function (event) {
        if (event.target.closest("button")) event.preventDefault();   // (the words keep their selection)
      });
      bar.addEventListener("click", function (event) {
        var button = event.target.closest("button");
        if (!button) return;
        if (button.hasAttribute("data-editor-link")) {
          link();
        } else if (button.hasAttribute("data-editor-picture")) {
          saveRange();
          if (pictureInput) pictureInput.click();
        } else if (button.dataset.editorPick) {
          pick(button.dataset.editorPick, button);
        } else if (button.dataset.format) {
          format(button.dataset.format);
        }
      });
    }

    api.html = function () {
      var inner = doc();
      if (!inner) return pending;
      inner.querySelectorAll("img.is-picked").forEach(function (one) { one.classList.remove("is-picked"); });
      return inner.body.innerHTML.replace(/ class=""/g, "");
    };
    api.set = function (html) {
      pending = html || "";
      var inner = doc();
      if (inner) {
        inner.body.innerHTML = pending;
        empty();
        showState();
      }
    };
    api.focus = function () {
      if (frame.contentWindow) frame.contentWindow.focus();
    };
    api.text = function () {
      var inner = doc();
      return inner ? inner.body.textContent.trim() : "";
    };
    api.hasPictures = function () {
      var inner = doc();
      return !!(inner && inner.body.querySelector("img"));
    };
    mount();
    document.addEventListener("someless:theme", function () {
      pending = api.html();
      mount();
    });
    return api;
  };
})();

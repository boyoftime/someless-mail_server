// A small editor of formatted text for Settings (a signature, the auto-reply's message), like the
// composer's (webmail-compose.js): the words in a page of their own (a frame where no script
// runs), a bar above for bold, italics, underline, lists, alignment, links and colours.
//   var editor = wm.editor(holder, {html, placeholder, onChange})
//   editor.html(), editor.set(html), editor.focus()
// holder: an element with [data-editor-bar] (buttons with data-format, or data-editor-link) and
// an iframe [data-editor-frame] (sandbox="allow-same-origin").
(function () {
  if (!window.wm) return;
  var COLORS = ["#000000", "#666666", "#e03131", "#f76707", "#2f9e44", "#1971c2", "#6741d9", "#c2255c"];

  function page(placeholder) {
    var dark = document.documentElement.dataset.theme === "dark";
    return '<!doctype html><html><head><meta charset="utf-8"><style>' +
      "html{color-scheme:" + (dark ? "dark" : "light") + "}" +
      "body{margin:0;padding:12px 14px;min-height:calc(100vh - 24px);box-sizing:border-box;font:14px/1.55 Arial,Helvetica,sans-serif;" +
      "color:" + (dark ? "#e3e7f4" : "#1c1f24") + ";overflow-wrap:anywhere;outline:none}" +
      "body.is-empty::before{content:" + JSON.stringify(placeholder || "") + ";position:absolute;color:" + (dark ? "#7c87a9" : "#878d98") +
      ";pointer-events:none}p{margin:0}a{color:" + (dark ? "#8cb4ff" : "#3b63e6") + "}img{max-width:100%}" +
      "</style></head><body contenteditable=\"true\" class=\"is-empty\"></body></html>";
  }

  wm.editor = function (holder, options) {
    options = options || {};
    var frame = holder.querySelector("[data-editor-frame]");
    var bar = holder.querySelector("[data-editor-bar]");
    var pending = options.html || "";
    var api = {};

    function doc() {
      var inner = frame.contentDocument;
      return inner && inner.body && inner.body.isContentEditable ? inner : null;
    }
    function empty() {
      var inner = doc();
      if (inner) inner.body.classList.toggle("is-empty", !inner.body.textContent.trim() && !inner.body.querySelector("img, li"));
    }
    function changed() {
      empty();
      if (options.onChange) options.onChange();
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
        empty();
      });
      frame.srcdoc = page(options.placeholder);
    }

    function format(command, value) {
      var inner = doc();
      if (!inner) return;
      frame.contentWindow.focus();
      inner.execCommand(command, false, value === undefined ? null : value);
      changed();
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

    if (bar) {
      bar.addEventListener("mousedown", function (event) {
        if (event.target.closest("button")) event.preventDefault();
      });
      bar.addEventListener("click", function (event) {
        var button = event.target.closest("button");
        if (!button) return;
        if (button.hasAttribute("data-editor-link")) {
          link();
        } else if (button.hasAttribute("data-editor-color")) {
          wm.menu(button, COLORS.map(function (colour) {
            return { label: colour, act: function () { format("foreColor", colour); } };
          }));
        } else if (button.dataset.format) {
          format(button.dataset.format);
        }
      });
    }

    api.html = function () {
      var inner = doc();
      return inner ? inner.body.innerHTML : pending;
    };
    api.set = function (html) {
      pending = html || "";
      var inner = doc();
      if (inner) {
        inner.body.innerHTML = pending;
        empty();
      }
    };
    api.focus = function () {
      if (frame.contentWindow) frame.contentWindow.focus();
    };
    api.text = function () {
      var inner = doc();
      return inner ? inner.body.textContent.trim() : "";
    };
    mount();
    document.addEventListener("someless:theme", function () {
      pending = api.html();
      mount();
    });
    return api;
  };
})();

// Dropdowns: a <select data-dropdown> becomes a button showing the choice, which opens a list
// in the panel's own look (the browser's own is plain, and different on every system). The
// select stays underneath, hidden, holding the choice, so the form sends it as before, and
// without JavaScript it's simply there. The list opens downwards, or upwards when there's
// more room there (inside a dialog, the dialog's room).
// Keyboard: Enter, Space or the arrows open it; the arrows, Home and End move; Enter or Space
// choose; Escape closes it without closing the dialog around it; Tab moves on.
(function () {
  var count = 0;

  function enhance(root) {
    root.querySelectorAll("select[data-dropdown]:not([data-dropdown-ready])").forEach(build);
  }

  function build(select) {
    select.setAttribute("data-dropdown-ready", "");
    var id = select.id || "dropdown-" + (count += 1);
    var wrap = document.createElement("div");
    wrap.className = "dropdown";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "dropdown-button";
    button.id = id + "-button";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    var text = document.createElement("span");
    text.className = "dropdown-text";
    text.id = id + "-text";
    button.appendChild(text);
    button.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 9.5l5.5 5.5 5.5-5.5"/></svg>');
    var list = document.createElement("ul");
    list.className = "dropdown-list";
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    list.tabIndex = -1;
    list.hidden = true;
    button.setAttribute("aria-controls", list.id);

    // the select's label names the button (with the choice) and the list
    var label = select.id && document.querySelector("label[for='" + select.id + "']");
    if (label) {
      label.id = label.id || id + "-label";
      label.htmlFor = button.id;
      button.setAttribute("aria-labelledby", label.id + " " + text.id);
      list.setAttribute("aria-labelledby", label.id);
    }

    var items = Array.from(select.options).map(function (option, index) {
      var item = document.createElement("li");
      item.className = "dropdown-option";
      item.id = id + "-option-" + index;
      item.setAttribute("role", "option");
      item.textContent = option.textContent;
      item.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 12.5l4.5 4.5 8.5-9"/></svg>');
      list.appendChild(item);
      return item;
    });
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    wrap.appendChild(button);
    wrap.appendChild(list);
    select.tabIndex = -1;

    var active = select.selectedIndex;

    function showChoice() {
      text.textContent = select.options[select.selectedIndex].textContent;
      items.forEach(function (item, index) {
        item.setAttribute("aria-selected", index === select.selectedIndex ? "true" : "false");
      });
    }

    function light(index) {
      active = Math.max(0, Math.min(items.length - 1, index));
      items.forEach(function (item, i) { item.classList.toggle("is-active", i === active); });
      list.setAttribute("aria-activedescendant", items[active].id);
      var item = items[active];
      if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop;
      else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight) {
        list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight;
      }
    }

    function open() {
      if (!list.hidden) return;
      list.hidden = false;
      var box = button.getBoundingClientRect();
      var room = button.closest("dialog") ? button.closest("dialog").getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
      var below = room.bottom - box.bottom;
      var above = box.top - room.top;
      list.setAttribute("data-side", below >= list.offsetHeight + 12 || below >= above ? "below" : "above");
      wrap.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      light(select.selectedIndex);
      list.focus({ preventScroll: true });
    }

    function close(refocus) {
      if (list.hidden) return;
      list.hidden = true;
      wrap.classList.remove("is-open");
      button.setAttribute("aria-expanded", "false");
      if (refocus) button.focus();
    }

    function choose(index) {
      if (select.selectedIndex !== index) {
        select.selectedIndex = index;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      showChoice();
      close(true);
    }

    button.addEventListener("click", function () {
      if (list.hidden) open();
      else close(true);
    });
    button.addEventListener("keydown", function (event) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].indexOf(event.key) !== -1) {
        event.preventDefault();
        open();
      }
    });
    list.addEventListener("keydown", function (event) {
      var moves = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: items.length - 1 };
      if (event.key in moves) {
        event.preventDefault();
        light(moves[event.key]);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose(active);
      } else if (event.key === "Escape") {
        event.preventDefault(); // this closes the list, not the dialog it's in
        event.stopPropagation();
        close(true);
      } else if (event.key === "Tab") {
        close(false);
      }
    });
    list.addEventListener("pointermove", function (event) {
      var item = event.target.closest(".dropdown-option");
      if (item) light(items.indexOf(item));
    });
    list.addEventListener("click", function (event) {
      var item = event.target.closest(".dropdown-option");
      if (item) choose(items.indexOf(item));
    });
    list.addEventListener("focusout", function (event) {
      if (!wrap.contains(event.relatedTarget)) close(false);
    });
    document.addEventListener("pointerdown", function (event) {
      if (!wrap.contains(event.target)) close(false);
    });
    showChoice();
  }

  enhance(document);
  document.addEventListener("someless:swap", function (event) { enhance(event.detail.main); });
})();

// The dividers between the webmail's columns (webmail-mail.html), as PrivateEmail has them: one on
// the folders' edge, one on the mail's, on screens 1200px wide and wider. Dragging one sets that
// column's width, and webmail-app.css keeps it where PrivateEmail stops: the folders from 184 to
// 320px, the mail from 248px until the reading pane would be narrower than 430px. Letting go
// keeps both widths, in a cookie the page is drawn with next time (webmail.py). A divider with
// the keyboard moves with the arrow keys.
(function () {
  var shell = document.querySelector("[data-wm-shell]");
  if (!shell) return;
  var columns = { side: shell.querySelector(".wm-side"), list: shell.querySelector(".wm-list") };
  var widths = { side: "--wm-side-width", list: "--wm-list-width" };
  var STEP = 16;   // px, for each arrow key

  function width(name) {
    return Math.round(columns[name].getBoundingClientRect().width);
  }

  // what the columns are now, their limits applied: kept, for this page and the next
  function keep() {
    shell.style.setProperty(widths.side, width("side") + "px");
    shell.style.setProperty(widths.list, width("list") + "px");
    document.cookie = "wm_columns=" + width("side") + "," + width("list") + "; path=/; max-age=31536000; samesite=lax" +
      (location.protocol === "https:" ? "; secure" : "");
    shell.querySelectorAll("[data-wm-resize]").forEach(function (handle) {
      handle.setAttribute("aria-valuenow", width(handle.dataset.wmResize));
    });
  }

  shell.querySelectorAll("[data-wm-resize]").forEach(function (handle) {
    var name = handle.dataset.wmResize;
    var from = null;   // where the drag started: {x, width}

    handle.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      event.preventDefault();   // no text selected, no focus ring
      from = { x: event.clientX, width: width(name) };
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("is-resizing");
    });
    handle.addEventListener("pointermove", function (event) {
      if (!from) return;
      shell.style.setProperty(widths[name], from.width + event.clientX - from.x + "px");
    });
    function end() {
      if (!from) return;
      from = null;
      document.body.classList.remove("is-resizing");
      keep();
    }
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end);

    handle.addEventListener("keydown", function (event) {
      var step = { ArrowLeft: -STEP, ArrowRight: STEP }[event.key];
      if (!step) return;
      event.preventDefault();
      shell.style.setProperty(widths[name], width(name) + step + "px");
      keep();
    });
  });

  shell.querySelectorAll("[data-wm-resize]").forEach(function (handle) {
    handle.setAttribute("aria-valuenow", width(handle.dataset.wmResize));
  });
})();

// Tables in what's being written (webmail-compose.js), easy to shape. The pointer on the border
// between two columns turns into a two-way arrow, with a line in the theme's blue along it:
// dragged, that column is made wider or narrower, all the way down the table. On the border
// under a row, the same for that row: taller or lower. A right-click on a cell: rows and columns
// put in above, below or beside it, or taken out, and the table taken out. The line is on this
// page, over the frame, so nothing of it ever goes in the message.
//   var tools = wm.tableTools(frame, {changed}); tools.hide(); tools.destroy()
// changed(): called after each change to the table (to save it, and fit the frame).
(function () {
  if (!window.wm) return;
  var EDGE = 5;           // px either side of a border that take hold of it
  var NARROWEST = 32;     // px: a column pulled narrower stops here
  var LOWEST = 24;        // px: and a row

  wm.tableTools = function (frame, options) {
    var doc = frame.contentDocument;
    var win = frame.contentWindow;
    var root = doc.documentElement;
    var border = null;      // the border pointed at: {kind: "column", table, index, cell} or {kind: "row", table, row}
    var dragging = null;    // {at, x, y, size}
    var guide = document.createElement("div");   // the line along it
    guide.className = "wm-tt-guide";
    guide.hidden = true;
    document.body.appendChild(guide);

    // --- the border at a point of the frame ---
    function cellAt(x, y) {
      var found = doc.elementFromPoint(x, y);
      var cell = found && found.closest ? found.closest("td, th") : null;
      return cell && doc.body.contains(cell) ? cell : null;
    }
    function borderAt(x, y) {
      var near = [cellAt(x, y), cellAt(x - EDGE, y), cellAt(x + EDGE, y), cellAt(x, y - EDGE), cellAt(x, y + EDGE)];
      for (var i = 0; i < near.length; i++) {
        var cell = near[i];
        if (!cell) continue;
        var box = cell.getBoundingClientRect();
        var row = cell.parentElement;
        var table = cell.closest("table");
        var across = y >= box.top - EDGE && y <= box.bottom + EDGE;
        var along = x >= box.left - EDGE && x <= box.right + EDGE;
        if (across && Math.abs(x - box.right) <= EDGE) return { kind: "column", table: table, index: cell.cellIndex, cell: cell };
        if (across && Math.abs(x - box.left) <= EDGE && cell.cellIndex > 0) {   // (its left: the column before it)
          return { kind: "column", table: table, index: cell.cellIndex - 1, cell: row.cells[cell.cellIndex - 1] };
        }
        if (along && Math.abs(y - box.bottom) <= EDGE) return { kind: "row", table: table, row: row };
        if (along && Math.abs(y - box.top) <= EDGE && row.rowIndex > 0) return { kind: "row", table: table, row: table.rows[row.rowIndex - 1] };
      }
      return null;
    }

    // --- the line along it, over the frame ---
    function showGuide(at) {
      if (!at.table.isConnected || !frame.isConnected) {
        guide.hidden = true;
        return;
      }
      var outer = frame.getBoundingClientRect();
      var box = at.table.getBoundingClientRect();
      var left, top, width, height;
      if (at.kind === "column") {
        left = at.cell.getBoundingClientRect().right - 1;
        top = Math.max(0, box.top);
        width = 2;
        height = Math.min(box.bottom, outer.height) - top;
      } else {
        top = at.row.getBoundingClientRect().bottom - 1;
        left = Math.max(0, box.left);
        height = 2;
        width = Math.min(box.right, outer.width) - left;
      }
      guide.hidden = width <= 0 || height <= 0 || left < -1 || top < -1 || left > outer.width || top > outer.height;
      guide.style.left = Math.round(outer.left + left) + "px";
      guide.style.top = Math.round(outer.top + top) + "px";
      guide.style.width = Math.round(width) + "px";
      guide.style.height = Math.round(height) + "px";
    }
    function point(at) {
      border = at;
      root.classList.toggle("wm-tt-col", !!at && at.kind === "column");
      root.classList.toggle("wm-tt-row", !!at && at.kind === "row");
      if (at) showGuide(at);
      else guide.hidden = true;
    }
    function hide() {
      if (dragging) return;
      point(null);
    }

    doc.addEventListener("mousemove", function (event) {
      if (dragging) return;
      point(event.buttons ? null : borderAt(event.clientX, event.clientY));   // (words being picked: no borders)
    });
    frame.addEventListener("mouseleave", hide);
    doc.addEventListener("keydown", hide);
    win.addEventListener("scroll", hide);
    window.addEventListener("scroll", hide, true);   // (the page or a column scrolling, the frame with it)
    window.addEventListener("resize", hide);

    // --- a border dragged: its column wider or narrower, its row taller or lower ---
    doc.addEventListener("pointerdown", function (event) {
      if (event.button !== 0 || !border) return;
      var at = border;
      var size = at.kind === "column" ? at.cell.getBoundingClientRect().width : at.row.getBoundingClientRect().height;
      dragging = { at: at, x: event.clientX, y: event.clientY, size: size };
      try { root.setPointerCapture(event.pointerId); } catch (error) { /* (it follows inside the frame only) */ }
      root.classList.add("wm-tt-sizing");
      document.body.classList.add(at.kind === "column" ? "is-sizing-column" : "is-sizing-row");
    });
    doc.addEventListener("mousedown", function (event) {
      if (dragging) event.preventDefault();   // (no cursor put in the cell, no words picked)
    });
    doc.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var at = dragging.at;
      if (at.kind === "column") {
        var width = Math.max(NARROWEST, Math.round(dragging.size + event.clientX - dragging.x));
        Array.prototype.forEach.call(at.table.rows, function (row) {
          if (row.cells[at.index]) row.cells[at.index].style.width = width + "px";
        });
      } else {
        var height = Math.max(LOWEST, Math.round(dragging.size + event.clientY - dragging.y));
        Array.prototype.forEach.call(at.row.cells, function (one) { one.style.height = height + "px"; });
      }
      showGuide(at);
    });
    function letGo() {
      if (!dragging) return;
      dragging = null;
      root.classList.remove("wm-tt-sizing");
      document.body.classList.remove("is-sizing-column", "is-sizing-row");
      point(null);
      options.changed();
    }
    doc.addEventListener("pointerup", letGo);
    doc.addEventListener("pointercancel", letGo);

    // --- rows and columns, from a cell's right-click menu ---
    function blank(like) {
      var made = doc.createElement("td");
      made.innerHTML = "<br>";
      if (like && like.style.width) made.style.width = like.style.width;   // (as wide as its column)
      return made;
    }
    function insertRow(row, below) {
      var made = doc.createElement("tr");
      Array.prototype.forEach.call(row.cells, function (one) { made.appendChild(blank(one)); });
      if (below) row.after(made);
      else row.before(made);
    }
    function insertColumn(where, index, right) {
      Array.prototype.forEach.call(where.rows, function (row) {
        var at = row.cells[Math.min(index, row.cells.length - 1)];
        var made = blank();
        if (!at) row.appendChild(made);
        else if (right) at.after(made);
        else at.before(made);
      });
    }
    function deleteRow(where, row) {
      row.remove();
      if (!where.rows.length) deleteTable(where);
    }
    function deleteColumn(where, index) {
      Array.prototype.slice.call(where.rows).forEach(function (row) {
        if (row.cells[index]) row.cells[index].remove();
        if (!row.cells.length) row.remove();
      });
      if (!where.rows.length) deleteTable(where);
    }
    function deleteTable(where) {
      var next = where.nextElementSibling;
      where.remove();
      if (!doc.body.firstChild) doc.body.innerHTML = "<p><br></p>";
      if (next) {   // the cursor where it was
        var range = doc.createRange();
        range.setStart(next, 0);
        range.collapse(true);
        var selection = doc.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
    function done() {
      point(null);
      options.changed();
    }

    doc.addEventListener("contextmenu", function (event) {
      var target = event.target.nodeType === 1 ? event.target : event.target.parentElement;
      var cell = target && target.closest("td, th");
      if (!cell || target.closest("img")) return;   // (a picture has its own menu)
      event.preventDefault();
      point(null);
      var where = cell.closest("table");
      var row = cell.parentElement;
      var index = cell.cellIndex;
      var outer = frame.getBoundingClientRect();
      wm.menu({ x: outer.left + event.clientX, y: outer.top + event.clientY }, [
        { label: "Insert row above", icon: "plus", act: function () { insertRow(row, false); done(); } },
        { label: "Insert row below", icon: "plus", act: function () { insertRow(row, true); done(); } },
        { label: "Insert column left", icon: "plus", act: function () { insertColumn(where, index, false); done(); } },
        { label: "Insert column right", icon: "plus", act: function () { insertColumn(where, index, true); done(); } },
        "-",
        { label: "Delete row", icon: "trash", act: function () { deleteRow(where, row); done(); } },
        { label: "Delete column", icon: "trash", act: function () { deleteColumn(where, index); done(); } },
        "-",
        { label: "Delete table", icon: "trash", danger: true, act: function () { deleteTable(where); done(); } },
      ]);
    });

    return {
      hide: hide,
      destroy: function () {
        dragging = null;
        point(null);
        guide.remove();
        document.body.classList.remove("is-sizing-column", "is-sizing-row");
        window.removeEventListener("scroll", hide, true);
        window.removeEventListener("resize", hide);
      },
    };
  };
})();

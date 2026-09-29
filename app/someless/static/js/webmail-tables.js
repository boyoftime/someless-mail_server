// Tables in what's being written (webmail-compose.js), easy to shape. Pointing at a table shows a
// handle at its top left corner, to drag it elsewhere in the message, and a + at its right edge
// and one at its bottom edge, for one more column or row. Pointing at a cell shows its menu at its
// top right (a right-click on it opens the same): rows and columns put in above, below or beside
// it, or taken out, and the table taken out; and a corner at its bottom right, pulled to make its
// column wider and its row taller. The handles are on this page, over the frame, so nothing of
// them ever goes in the message.
//   var tools = wm.tableTools(frame, {changed}); tools.hide(); tools.destroy()
// changed(): called after each change to the table (to save it, and fit the frame).
(function () {
  if (!window.wm) return;
  var HIDE_AFTER = 350;   // ms after the pointer has left the table and its handles
  var NARROWEST = 32;     // px: a column pulled narrower stops here
  var LOWEST = 24;        // px: and a row

  wm.tableTools = function (frame, options) {
    var doc = frame.contentDocument;
    var win = frame.contentWindow;
    var table = null;       // the table pointed at
    var cell = null;        // and its cell
    var hideTimer = null;
    var dragging = null;    // {kind: "size" | "move", ...}

    function handle(className, iconName, label) {
      var made = document.createElement("button");
      made.type = "button";
      made.className = "wm-tt " + className;
      made.setAttribute("aria-label", label);
      made.dataset.tip = label;
      made.hidden = true;
      made.appendChild(wm.icon(iconName));
      made.addEventListener("mouseenter", stay);
      made.addEventListener("mouseleave", later);
      made.addEventListener("mousedown", function (event) { event.preventDefault(); });   // (the cursor stays in the message)
      document.body.appendChild(made);
      return made;
    }
    var move = handle("wm-tt-move", "grip", "Drag to move the table");
    var addColumn = handle("wm-tt-add", "plus", "Add a column");
    var addRow = handle("wm-tt-add", "plus", "Add a row");
    var cellMenu = handle("wm-tt-menu", "more", "Rows and columns");
    var pull = handle("wm-tt-size", "resize", "Drag to make it bigger");
    var handles = [move, addColumn, addRow, cellMenu, pull];
    var line = document.createElement("div");   // where a table being moved would go
    line.className = "wm-tt-drop";
    line.hidden = true;
    document.body.appendChild(line);

    // --- showing the handles where they belong, over the frame ---
    function place(element, x, y) {   // x, y: its middle, in the frame's page
      var outer = frame.getBoundingClientRect();
      var inside = x >= 0 && y >= 0 && x <= outer.width && y <= outer.height;
      element.hidden = !inside;
      if (!inside) return;
      element.style.left = Math.round(outer.left + x) + "px";
      element.style.top = Math.round(outer.top + y) + "px";
    }
    function show() {
      if (!table || !table.isConnected || !frame.isConnected) {
        hide();
        return;
      }
      var box = table.getBoundingClientRect();
      var width = win.innerWidth, height = win.innerHeight;
      place(move, Math.max(12, box.left), Math.max(12, box.top));
      place(addColumn, Math.min(box.right + 14, width - 12), box.top + box.height / 2);
      place(addRow, box.left + box.width / 2, Math.min(box.bottom + 14, height - 12));
      if (cell && table.contains(cell)) {
        var edge = cell.getBoundingClientRect();
        place(cellMenu, edge.right - 13, edge.top + 13);
        place(pull, edge.right, edge.bottom);
      } else {
        cellMenu.hidden = true;
        pull.hidden = true;
      }
    }
    function hide() {
      clearTimeout(hideTimer);
      if (dragging) return;
      handles.forEach(function (one) { one.hidden = true; });
      table = null;
      cell = null;
    }
    function later() {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(hide, HIDE_AFTER);
    }
    function stay() {
      clearTimeout(hideTimer);
    }
    function again() {
      if (table) show();
    }

    doc.addEventListener("mousemove", function (event) {
      if (dragging) return;
      var target = event.target.nodeType === 1 ? event.target : event.target.parentElement;
      var nextTable = target && target.closest("table");
      if (!nextTable || !doc.body.contains(nextTable)) {
        later();
        return;
      }
      stay();
      table = nextTable;
      cell = target.closest("td, th");
      show();
    });
    frame.addEventListener("mouseleave", later);
    win.addEventListener("scroll", again);
    doc.addEventListener("input", again);
    window.addEventListener("scroll", again, true);   // (the page or a column scrolling, the frame with it)
    window.addEventListener("resize", again);

    // --- rows and columns ---
    function blank(like) {
      var made = doc.createElement("td");
      made.innerHTML = "<br>";
      if (like && like.style.width) made.style.width = like.style.width;   // (as wide as its column)
      return made;
    }
    function insertRow(where, row, below) {
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
      options.changed();
      if (table && !table.isConnected) hide();
      else again();
    }

    function menuFor(at, target) {
      var where = target.closest("table");
      var row = target.parentElement;
      var index = target.cellIndex;
      stay();
      wm.menu(at, [
        { label: "Insert row above", icon: "plus", act: function () { insertRow(where, row, false); done(); } },
        { label: "Insert row below", icon: "plus", act: function () { insertRow(where, row, true); done(); } },
        { label: "Insert column left", icon: "plus", act: function () { insertColumn(where, index, false); done(); } },
        { label: "Insert column right", icon: "plus", act: function () { insertColumn(where, index, true); done(); } },
        "-",
        { label: "Delete row", icon: "trash", act: function () { deleteRow(where, row); done(); } },
        { label: "Delete column", icon: "trash", act: function () { deleteColumn(where, index); done(); } },
        "-",
        { label: "Delete table", icon: "trash", danger: true, act: function () { deleteTable(where); done(); } },
      ], { onClose: later });
    }
    cellMenu.addEventListener("click", function () {
      if (cell) menuFor(cellMenu, cell);
    });
    doc.addEventListener("contextmenu", function (event) {
      var target = event.target.nodeType === 1 ? event.target : event.target.parentElement;
      var inCell = target && target.closest("td, th");
      if (!inCell || target.closest("img")) return;   // (a picture has its own menu)
      event.preventDefault();
      var outer = frame.getBoundingClientRect();
      menuFor({ x: outer.left + event.clientX, y: outer.top + event.clientY }, inCell);
    });
    addColumn.addEventListener("click", function () {
      if (!table) return;
      var widest = Math.max.apply(null, Array.prototype.map.call(table.rows, function (row) { return row.cells.length; }));
      insertColumn(table, widest - 1, true);
      done();
    });
    addRow.addEventListener("click", function () {
      if (!table || !table.rows.length) return;
      insertRow(table, table.rows[table.rows.length - 1], true);
      done();
    });

    // --- a cell pulled bigger: its column wider, its row taller ---
    pull.addEventListener("pointerdown", function (event) {
      if (!cell) return;
      event.preventDefault();
      pull.setPointerCapture(event.pointerId);
      var style = win.getComputedStyle(cell);
      dragging = { kind: "size", x: event.clientX, y: event.clientY, table: table, row: cell.parentElement, index: cell.cellIndex,
                   width: parseFloat(style.width) || cell.clientWidth, height: parseFloat(style.height) || cell.clientHeight };
      document.body.classList.add("is-sizing-cell");
    });
    pull.addEventListener("pointermove", function (event) {
      if (!dragging || dragging.kind !== "size") return;
      var width = Math.max(NARROWEST, Math.round(dragging.width + event.clientX - dragging.x));
      var height = Math.max(LOWEST, Math.round(dragging.height + event.clientY - dragging.y));
      Array.prototype.forEach.call(dragging.table.rows, function (row) {
        if (row.cells[dragging.index]) row.cells[dragging.index].style.width = width + "px";
      });
      Array.prototype.forEach.call(dragging.row.cells, function (one) { one.style.height = height + "px"; });
      show();
    });

    // --- the table dragged elsewhere: before or after the part of the message it's let go on ---
    function partAt(x, y) {   // the part of the message (a child of its body) at a point of the frame
      var node = null;
      if (doc.caretRangeFromPoint) {
        var range = doc.caretRangeFromPoint(x, y);
        node = range && range.startContainer;
      } else if (doc.caretPositionFromPoint) {
        var position = doc.caretPositionFromPoint(x, y);
        node = position && position.offsetNode;
      }
      if (!node) node = doc.elementFromPoint(x, y);
      if (!node || node === doc.body || node === doc.documentElement) {
        return doc.body.lastChild;   // (below it all: the end)
      }
      while (node.parentNode && node.parentNode !== doc.body) node = node.parentNode;
      return node.parentNode === doc.body ? node : null;
    }
    function boxOf(node) {
      if (node.nodeType === 1) return node.getBoundingClientRect();
      var range = doc.createRange();
      range.selectNode(node);
      return range.getBoundingClientRect();
    }
    move.addEventListener("pointerdown", function (event) {
      if (!table) return;
      event.preventDefault();
      move.setPointerCapture(event.pointerId);
      dragging = { kind: "move", table: table, to: null };
      document.body.classList.add("is-moving-table");
    });
    move.addEventListener("pointermove", function (event) {
      if (!dragging || dragging.kind !== "move") return;
      var outer = frame.getBoundingClientRect();
      var x = Math.max(2, Math.min(event.clientX - outer.left, outer.width - 2));
      var y = event.clientY - outer.top;
      var scroller = doc.scrollingElement || doc.documentElement;
      if (y < 28) scroller.scrollTop -= 14;   // (near an edge: it scrolls on)
      else if (y > outer.height - 28) scroller.scrollTop += 14;
      y = Math.max(2, Math.min(y, outer.height - 2));
      var part = partAt(x, y);
      if (!part || part === dragging.table) {
        dragging.to = null;
        line.hidden = true;
        return;
      }
      var box = boxOf(part);
      var before = y < box.top + box.height / 2;
      dragging.to = { part: part, before: before };
      line.hidden = false;
      line.style.left = Math.round(outer.left + 12) + "px";
      line.style.width = Math.round(outer.width - 24) + "px";
      line.style.top = Math.round(outer.top + (before ? box.top : box.bottom) - 1) + "px";
    });

    function letGo() {
      if (!dragging) return;
      var was = dragging;
      dragging = null;
      line.hidden = true;
      document.body.classList.remove("is-sizing-cell", "is-moving-table");
      if (was.kind === "move") {
        if (!was.to) {
          again();
          return;
        }
        if (was.to.before) was.to.part.before(was.table);
        else was.to.part.after(was.table);
        var next = was.table.nextSibling;
        if (!next || (next.nodeType === 1 && next.tagName === "TABLE")) {   // (room to write after it)
          var paragraph = doc.createElement("p");
          paragraph.innerHTML = "<br>";
          was.table.after(paragraph);
        }
        table = was.table;
      }
      done();
    }
    [move, pull].forEach(function (one) {
      one.addEventListener("pointerup", letGo);
      one.addEventListener("pointercancel", letGo);
    });

    return {
      hide: hide,
      destroy: function () {
        dragging = null;
        hide();
        handles.forEach(function (one) { one.remove(); });
        line.remove();
        document.body.classList.remove("is-sizing-cell", "is-moving-table");
        window.removeEventListener("scroll", again, true);
        window.removeEventListener("resize", again);
      },
    };
  };
})();

// The Filters page (webmail-settings-filters.html, settings.py, sieve.py), as PrivateEmail's: the
// filters in their order, each with what it looks for and does and a switch for on or off;
// dragged by its handle to run earlier or later; ticked ones deleted together. "Create a new
// filter" (or Edit) opens the form: its name; its conditions, all, any or none needed, a group of
// conditions of their own inside; its actions; and whether it stops the ones after it. Cancel
// with changes asks first ("Discard filter rule?").
(function () {
  var holder = document.querySelector("[data-wm-rules]");
  if (!holder || !window.wm) return;
  var url = holder.dataset.url;
  var rules = JSON.parse(holder.dataset.rules || "[]");
  var folders = JSON.parse(holder.dataset.folders || "[]");
  var table = holder.querySelector("[data-wm-rules-table]");
  var body = holder.querySelector("[data-wm-rules-body]");
  var empty = holder.querySelector("[data-wm-rules-empty]");
  var deleteButton = document.querySelector("[data-wm-delete-rules]");
  var dialog = document.querySelector("[data-wm-rule-dialog]");
  var form = dialog.querySelector("[data-wm-rule-form]");
  var problem = form.querySelector("[data-wm-problem]");
  var editing = null;
  var changed = false;

  var PROPERTIES = [["from", "From"], ["to", "To"], ["cc", "CC"], ["any_recipient", "Any recipient"], ["subject", "Subject"],
                    ["body", "Body"], ["header", "Header"], ["size", "Size"], ["sent_date", "Sent date"]];
  var TEXT_OPS = [["contains", "Contains"], ["not_contains", "Does not contain"], ["is", "Is exactly"], ["is_not", "Is not exactly"],
                  ["starts", "Starts with"], ["not_starts", "Does not start with"], ["ends", "Ends with"], ["not_ends", "Does not end with"],
                  ["matches", "Matches"], ["not_matches", "Does not match"], ["regex", "Matches regex"], ["not_regex", "Does not match regex"],
                  ["exists", "Exists"], ["not_exists", "Does not exist"]];
  var SIZE_OPS = [["greater", "Greater than"], ["less", "Lower than"], ["greater_or_equal", "Greater or equal"], ["less_or_equal", "Lower or equal"]];
  var DATE_OPS = [["after", "After"], ["before", "Before"], ["on", "On"], ["not_on", "Not on"], ["on_or_after", "On or after"],
                  ["on_or_before", "On or before"]];
  var ACTIONS = [["move", "Move to"], ["copy", "Copy to"], ["forward", "Forward to"], ["mark", "Mark as"], ["keep", "Keep"],
                 ["discard", "Discard"], ["delete", "Delete"]];

  function label(pairs, key) {
    var found = pairs.filter(function (pair) { return pair[0] === key; })[0];
    return found ? found[1] : key;
  }
  function opsFor(prop) {
    return prop === "size" ? SIZE_OPS : prop === "sent_date" ? DATE_OPS : TEXT_OPS;
  }
  function folderName(id) {
    var found = folders.filter(function (folder) { return folder.id === id; })[0];
    return found ? found.label : "a folder that's gone";
  }

  // --- the list ---
  function describeCondition(condition) {
    if (condition.group) {
      return "(" + (condition.group === "all" ? "all of: " : "any of: ") + condition.conditions.map(describeCondition).join(", ") + ")";
    }
    var subject = condition.prop === "header" ? (condition.headers || []).join(" or ") : label(PROPERTIES, condition.prop);
    var verb = label(opsFor(condition.prop), condition.op).toLowerCase();
    if (condition.op === "exists" || condition.op === "not_exists") return subject + " " + verb;
    return subject + " " + verb + " “" + condition.value + "”";
  }
  function describeAction(action) {
    if (action.type === "move") return "Move to “" + folderName(action.folder) + "”";
    if (action.type === "copy") return "Copy to “" + folderName(action.folder) + "”";
    if (action.type === "forward") return "Forward to " + action.address + (action.keep ? " (keep a copy)" : "");
    if (action.type === "read") return "Mark as read";
    if (action.type === "favorite") return "Mark as favorite";
    return label(ACTIONS, action.type);
  }
  function describe(rule) {
    var when = rule.operator === "none" ? "All emails" :
      (rule.conditions.length > 1 ? (rule.operator === "all" ? "All of: " : "Any of: ") : "") + rule.conditions.map(describeCondition).join(", ");
    return when + " → " + rule.actions.map(describeAction).join(", ") + (rule.stop ? ", then stop" : "");
  }

  function draw() {
    body.innerHTML = "";
    rules.forEach(function (rule) {
      var row = document.createElement("tr");
      row.dataset.id = rule.id;
      row.innerHTML = '<td class="is-narrow"><span class="wm-drag-handle" title="Drag to reorder filter"></span></td>' +
        '<td class="is-narrow"><label class="wm-check"><input type="checkbox" data-wm-rule-tick></label></td>' +
        '<td class="wm-rule-name"></td><td class="wm-rule-summary"></td>' +
        '<td class="is-narrow"><button type="button" class="wm-switch-button" role="switch" data-wm-rule-toggle><span class="wm-switch"><span></span></span></button></td>' +
        '<td class="is-narrow"><button type="button" class="wm-icon wm-mini" data-wm-rule-menu aria-label="More options"></button></td>';
      row.querySelector(".wm-drag-handle").appendChild(wm.icon("grip"));
      row.querySelector(".wm-rule-name").textContent = rule.name;
      row.querySelector(".wm-rule-summary").textContent = describe(rule);
      var toggle = row.querySelector("[data-wm-rule-toggle]");
      toggle.setAttribute("aria-checked", String(rule.enabled));
      toggle.setAttribute("aria-label", (rule.enabled ? "Turn off " : "Turn on ") + rule.name);
      row.querySelector("[data-wm-rule-menu]").appendChild(wm.icon("more") || wm.icon("chevron"));
      body.appendChild(row);
    });
    table.hidden = !rules.length;
    empty.hidden = !!rules.length;
    showDelete();
  }

  function showDelete() {
    var ticked = body.querySelectorAll("[data-wm-rule-tick]:checked").length;
    deleteButton.hidden = !ticked;
  }

  function send(target, payload, title) {
    return wm.request(target, { method: "POST", body: payload, failTitle: title }).then(function (answer) {
      rules = answer.rules;
      draw();
      if (answer.message) wm.toast(answer.message);
      return answer;
    });
  }

  body.addEventListener("click", function (event) {
    var row = event.target.closest("tr");
    if (!row) return;
    var rule = rules.filter(function (one) { return String(one.id) === row.dataset.id; })[0];
    if (event.target.closest("[data-wm-rule-toggle]")) {
      send(url + "/" + rule.id + "/toggle", { enabled: !rule.enabled }, "An error has occured while updaing the rule.");
      return;
    }
    var menu = event.target.closest("[data-wm-rule-menu]");
    if (menu) {
      wm.menu(menu, [
        { label: "Edit rule", icon: "edit", act: function () { openForm(rule); } },
        { label: "Remove rule", icon: "trash", danger: true, act: function () { remove([rule.id], rule.name); } },
      ]);
      return;
    }
    if (event.target.closest("[data-wm-rule-tick]")) {
      showDelete();
      return;
    }
    if (event.target.closest(".wm-rule-name, .wm-rule-summary")) openForm(rule);
  });

  holder.querySelector("[data-wm-rules-all]").addEventListener("change", function (event) {
    body.querySelectorAll("[data-wm-rule-tick]").forEach(function (tick) { tick.checked = event.target.checked; });
    showDelete();
  });

  function remove(ids, name) {
    wm.confirm(ids.length === 1 ? { title: "Delete filter?", text: "Are you sure you want to delete " + (name || "this") + " filter?",
                                    yes: "Delete", no: "Cancel", danger: true }
                                : { title: "Delete filters?", text: "Are you sure you want to delete all the selected filters?",
                                    yes: "Delete", no: "Cancel", danger: true }).then(function (yes) {
      if (yes) send(url + "/delete", { ids: ids }, "An error has occured while deleting the rule(-s).");
    });
  }
  deleteButton.addEventListener("click", function () {
    var ids = Array.prototype.map.call(body.querySelectorAll("[data-wm-rule-tick]:checked"), function (tick) {
      return Number(tick.closest("tr").dataset.id);
    });
    remove(ids);
  });

  // their order: dragged by the handle (the row can be dragged while it's held there)
  var dragged = null;
  body.addEventListener("pointerdown", function (event) {
    var handle = event.target.closest(".wm-drag-handle");
    if (handle) handle.closest("tr").draggable = true;
  });
  document.addEventListener("pointerup", function () {
    if (dragged) return;
    body.querySelectorAll("tr[draggable]").forEach(function (row) { row.removeAttribute("draggable"); });
  });
  body.addEventListener("dragstart", function (event) {
    dragged = event.target.closest("tr");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragged.dataset.id);
    dragged.classList.add("is-dragged");
  });
  body.addEventListener("dragover", function (event) {
    var over = event.target.closest("tr");
    if (!dragged || !over || over === dragged) return;
    event.preventDefault();
    var box = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragged, event.clientY < box.top + box.height / 2 ? over : over.nextSibling);
  });
  body.addEventListener("dragend", function () {
    if (!dragged) return;
    dragged.classList.remove("is-dragged");
    dragged.removeAttribute("draggable");
    dragged = null;
    var ids = Array.prototype.map.call(body.querySelectorAll("tr"), function (row) { return Number(row.dataset.id); });
    send(url + "/order", { ids: ids }, "An error has occured while updaing the rule.");
  });

  // --- the form ---
  function select(pairs, value, className) {
    var box = document.createElement("select");
    box.className = "wm-input wm-select " + (className || "");
    pairs.forEach(function (pair) {
      var option = document.createElement("option");
      option.value = pair[0];
      option.textContent = pair[1];
      box.appendChild(option);
    });
    if (value !== undefined) box.value = value;
    return box;
  }
  function removeButton(text) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "wm-icon wm-mini";
    button.setAttribute("aria-label", text);
    button.setAttribute("data-tip", text);
    button.appendChild(wm.icon("close"));
    return button;
  }

  function conditionRow(condition) {
    condition = condition || { prop: "subject", op: "contains", value: "" };
    var row = document.createElement("div");
    row.className = "wm-rule-row";
    row.dataset.kind = "condition";
    var prop = select(PROPERTIES, condition.prop, "is-prop");
    var op = select(opsFor(condition.prop), condition.op, "is-op");
    var headers = document.createElement("input");
    headers.className = "wm-input is-headers";
    headers.placeholder = "Header names";
    headers.value = (condition.headers || []).join(", ");
    var value = document.createElement("input");
    value.className = "wm-input is-value";
    value.placeholder = "Enter condition here";
    value.value = condition.value === undefined ? "" : condition.value;
    function shape() {
      var chosen = prop.value;
      var ops = opsFor(chosen);
      if (!ops.some(function (pair) { return pair[0] === op.value; })) {
        var fresh = select(ops, ops[0][0], "is-op");
        op.replaceWith(fresh);
        op = fresh;
        op.addEventListener("change", shape);
      }
      headers.hidden = chosen !== "header";
      value.hidden = op.value === "exists" || op.value === "not_exists";
      value.type = chosen === "sent_date" ? "date" : chosen === "size" ? "number" : "text";
      value.placeholder = chosen === "size" ? "Size in bytes" : chosen === "sent_date" ? "Date" : "Enter condition here";
      if (chosen === "header") value.placeholder = "Header value";
    }
    prop.addEventListener("change", shape);
    op.addEventListener("change", shape);
    var remove = removeButton("Remove condition");
    remove.addEventListener("click", function () {
      row.remove();
      changed = true;
    });
    row.appendChild(prop);
    row.appendChild(headers);
    row.appendChild(op);
    row.appendChild(value);
    row.appendChild(remove);
    row.read = function () {
      var made = { prop: prop.value, op: op.value };
      if (prop.value === "header") made.headers = headers.value.split(/[,\s]+/).filter(Boolean);
      if (!value.hidden) made.value = value.value;
      return made;
    };
    shape();
    return row;
  }

  function groupBox(group) {
    group = group || { group: "all", conditions: [{ prop: "from", op: "contains", value: "" }] };
    var box = document.createElement("div");
    box.className = "wm-rule-group";
    box.dataset.kind = "group";
    var head = document.createElement("div");
    head.className = "wm-rule-group-head";
    var title = document.createElement("span");
    title.className = "wm-rule-group-title";
    title.textContent = "Nested Conditions Group";
    var operator = select([["all", "All of"], ["any", "Any of"]], group.group, "is-group-op");
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "wm-button is-ghost is-small is-danger-text";
    remove.textContent = "Remove group";
    remove.addEventListener("click", function () {
      box.remove();
      changed = true;
    });
    head.appendChild(title);
    head.appendChild(operator);
    head.appendChild(remove);
    var inner = document.createElement("div");
    inner.className = "wm-rule-group-rows";
    group.conditions.forEach(function (condition) { inner.appendChild(conditionRow(condition)); });
    var add = document.createElement("button");
    add.type = "button";
    add.className = "wm-button is-ghost is-small";
    add.appendChild(wm.icon("plus"));
    add.appendChild(document.createTextNode("Add condition"));
    add.addEventListener("click", function () {
      inner.appendChild(conditionRow());
      changed = true;
    });
    box.appendChild(head);
    box.appendChild(inner);
    box.appendChild(add);
    box.read = function () {
      return { group: operator.value, conditions: Array.prototype.map.call(inner.children, function (row) { return row.read(); }) };
    };
    return box;
  }

  function actionRow(action) {
    action = action || { type: "move" };
    var row = document.createElement("div");
    row.className = "wm-rule-row";
    var kind = select(ACTIONS, action.type === "read" || action.type === "favorite" ? "mark" : action.type, "is-action");
    var folder = select(folders.map(function (one) { return [one.id, one.label]; }), action.folder, "is-folder");
    var address = document.createElement("input");
    address.className = "wm-input is-value";
    address.type = "email";
    address.placeholder = "Enter email address";
    address.value = action.address || "";
    var keep = document.createElement("label");
    keep.className = "wm-check-line is-inline";
    keep.innerHTML = '<input type="checkbox"><span>Keep an email copy</span>';
    keep.title = "You should turn this on in every forwarding rule in order to keep a copy of forwarded emails in your mailbox.";
    keep.querySelector("input").checked = action.keep !== false;
    var mark = select([["read", "Read"], ["favorite", "Favorite"]], action.type === "favorite" ? "favorite" : "read", "is-mark");
    function shape() {
      folder.hidden = ["move", "copy"].indexOf(kind.value) < 0;
      address.hidden = keep.hidden = kind.value !== "forward";
      mark.hidden = kind.value !== "mark";
    }
    kind.addEventListener("change", shape);
    var remove = removeButton("Remove action");
    remove.addEventListener("click", function () {
      row.remove();
      changed = true;
    });
    row.appendChild(kind);
    row.appendChild(folder);
    row.appendChild(address);
    row.appendChild(keep);
    row.appendChild(mark);
    row.appendChild(remove);
    row.read = function () {
      if (kind.value === "mark") return { type: mark.value };
      var made = { type: kind.value };
      if (kind.value === "move" || kind.value === "copy") made.folder = folder.value;
      if (kind.value === "forward") {
        made.address = address.value.trim();
        made.keep = keep.querySelector("input").checked;
      }
      return made;
    };
    shape();
    return row;
  }

  var conditions = form.querySelector("[data-wm-conditions]");
  var actions = form.querySelector("[data-wm-actions]");
  var operatorGroup = form.querySelector("[data-wm-operator]");
  var nameInput = form.querySelector('[name="name"]');
  var stopInput = form.querySelector('[name="stop"]');

  function operator() {
    var on = operatorGroup.querySelector('[aria-checked="true"]');
    return on ? on.dataset.value : "all";
  }
  function setOperator(value) {
    operatorGroup.querySelectorAll("[data-value]").forEach(function (option) {
      option.setAttribute("aria-checked", String(option.dataset.value === value));
    });
    var none = value === "none";
    conditions.hidden = none;
    form.querySelector("[data-wm-condition-adds]").hidden = none;
  }
  operatorGroup.addEventListener("click", function (event) {
    var option = event.target.closest("[data-value]");
    if (!option) return;
    setOperator(option.dataset.value);
    changed = true;
  });

  function openForm(rule) {
    editing = rule || null;
    dialog.querySelector("[data-wm-rule-title]").textContent = rule ? "Edit the filter" : "Create a new filter";
    nameInput.value = rule ? rule.name : "";
    stopInput.checked = rule ? rule.stop : false;
    setOperator(rule ? rule.operator : "all");
    conditions.innerHTML = "";
    actions.innerHTML = "";
    (rule && rule.conditions.length ? rule.conditions : [null]).forEach(function (condition) {
      conditions.appendChild(condition && condition.group ? groupBox(condition) : conditionRow(condition));
    });
    (rule && rule.actions.length ? rule.actions : [null]).forEach(function (action) { actions.appendChild(actionRow(action)); });
    problem.hidden = true;
    changed = false;
    dialog.showModal();
    nameInput.focus();
  }
  document.querySelectorAll("[data-wm-new-rule]").forEach(function (button) {
    button.addEventListener("click", function () { openForm(null); });
  });
  form.querySelector("[data-wm-add-condition]").addEventListener("click", function () {
    conditions.appendChild(conditionRow());
    changed = true;
  });
  form.querySelector("[data-wm-add-group]").addEventListener("click", function () {
    conditions.appendChild(groupBox());
    changed = true;
  });
  form.querySelector("[data-wm-add-action]").addEventListener("click", function () {
    actions.appendChild(actionRow());
    changed = true;
  });
  form.addEventListener("input", function () { changed = true; });
  form.addEventListener("change", function () { changed = true; });

  function cancel() {
    if (!changed) {
      dialog.close();
      return;
    }
    wm.confirm({ title: "Discard filter rule?", text: "This filter rule will not be saved.", yes: "Yes, discard", no: "No, do not discard",
                 danger: true }).then(function (yes) {
      if (yes) dialog.close();
    });
  }
  form.querySelectorAll("[data-wm-rule-cancel]").forEach(function (button) { button.addEventListener("click", cancel); });
  dialog.addEventListener("cancel", function (event) {
    event.preventDefault();
    cancel();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    problem.hidden = true;
    var rule = {
      name: nameInput.value, operator: operator(), stop: stopInput.checked, enabled: editing ? editing.enabled : true,
      conditions: operator() === "none" ? [] : Array.prototype.map.call(conditions.children, function (row) { return row.read(); }),
      actions: Array.prototype.map.call(actions.children, function (row) { return row.read(); }),
    };
    wm.request(editing ? url + "/" + editing.id : url, { method: "POST", body: rule, quiet: true }).then(function (answer) {
      rules = answer.rules;
      draw();
      changed = false;
      dialog.close();
      wm.toast(answer.message);
    }, function (error) {
      problem.textContent = error.problem || "An error has occured. Try repeat action later.";
      problem.hidden = false;
    });
  });

  draw();
})();

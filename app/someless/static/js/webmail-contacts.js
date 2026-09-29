// Contacts (webmail-contacts.html, contacts.py), as PrivateEmail's: the list a page at a time,
// found as the top bar's search is typed in, the contact books down the side; ticked contacts
// deleted together (all of them across the pages too); a contact opens in Contact details (its
// addresses and numbers to copy, an email to write), and is added or changed in its form, a
// photo made 256 pixels square first. Each change goes to the webmail; the toast says it's done.
(function () {
  var page = document.querySelector("[data-wm-contacts]");
  if (!page || !window.wm) return;
  var mailUrl = document.currentScript.dataset.mailUrl;
  var state = {
    book: page.dataset.book, q: page.dataset.q, page: Number(page.dataset.page) || 1, pages: Number(page.dataset.pages) || 1,
    size: Number(page.dataset.size) || 25, total: Number(page.dataset.total) || 0,
  };
  var url = page.dataset.url;
  var body = page.querySelector("[data-wm-contacts-body]");
  var card = page.querySelector("[data-wm-contacts-card]");
  var none = page.querySelector("[data-wm-contacts-none]");
  var empty = page.querySelector("[data-wm-contacts-empty]");
  var pages = page.querySelector("[data-wm-pages]");
  var bulk = page.querySelector("[data-wm-bulk]");
  var allTick = page.querySelector("[data-wm-contacts-all]");
  var everyButton = page.querySelector("[data-wm-select-every]");
  var acrossPages = false;
  var loading = null;
  var TYPES = { other: "Other", home: "Home", work: "Work", mobile: "Mobile", fax: "Fax", pager: "Pager" };
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  // --- the list ---
  function address() {
    var params = new URLSearchParams();
    if (state.book) params.set("book", state.book);
    if (state.q) params.set("q", state.q);
    if (state.page > 1) params.set("page", String(state.page));
    return url + (params.toString() ? "?" + params.toString() : "");
  }

  function load(keepTicks) {
    if (loading) loading.abort();
    loading = new AbortController();
    card.classList.add("is-loading");
    wm.loading(card.hidden ? page : card, true);
    return wm.request(address() + (address().indexOf("?") < 0 ? "?" : "&") + "size=" + state.size, { signal: loading.signal })
      .then(function (answer) {
        loading = null;
        var wasTicked = keepTicks ? ticked() : [];
        body.innerHTML = answer.html;
        state.total = answer.total;
        state.page = answer.page;
        state.pages = answer.pages;
        state.size = answer.size;
        history.replaceState(history.state, "", address());
        wm.loading(card, false);
        wm.loading(page, false);
        if (keepTicks) {   // (the same contacts stay ticked)
          body.querySelectorAll("tr").forEach(function (row) {
            if (wasTicked.indexOf(row.dataset.id) >= 0) row.querySelector("[data-wm-contact-tick]").checked = true;
          });
        } else {
          clearTicks();
        }
        draw();
      }, function (error) {
        if (error && error.name === "AbortError") return;
        loading = null;
        card.classList.remove("is-loading");
        wm.loading(card, false);
        wm.loading(page, false);
      });
  }

  function draw() {
    card.classList.remove("is-loading");
    var rows = body.querySelectorAll("tr").length;
    var nothing = !state.total && !state.q;
    card.hidden = nothing;
    empty.hidden = !nothing;
    none.hidden = !!rows || nothing;
    card.querySelector("table").hidden = !rows;
    pages.hidden = !state.total;
    drawPages();
    showBulk();
  }

  function drawPages() {
    var list = pages.querySelector("[data-wm-page-list]");
    list.innerHTML = "";
    function button(label, target, options) {
      options = options || {};
      var made = document.createElement("button");
      made.type = "button";
      made.className = "wm-page" + (options.current ? " is-current" : "");
      if (options.icon) {
        made.appendChild(wm.icon(options.icon));
        made.setAttribute("aria-label", label);
      } else {
        made.textContent = label;
      }
      if (options.current) made.setAttribute("aria-current", "page");
      made.disabled = !!options.disabled;
      made.addEventListener("click", function () {
        state.page = target;
        load();
        page.scrollTo({ top: 0, behavior: wm.reduceMotion ? "auto" : "smooth" });
      });
      list.appendChild(made);
    }
    button("Previous page", state.page - 1, { icon: "chevron-left", disabled: state.page <= 1 });
    var shown = [];
    for (var number = 1; number <= state.pages; number += 1) {
      if (number === 1 || number === state.pages || Math.abs(number - state.page) <= 1) shown.push(number);
    }
    shown.forEach(function (number, index) {
      if (index && number - shown[index - 1] > 1) {
        var gap = document.createElement("span");
        gap.className = "wm-page-gap";
        gap.textContent = "…";
        list.appendChild(gap);
      }
      button(String(number), number, { current: number === state.page });
    });
    button("Next page", state.page + 1, { icon: "chevron-right", disabled: state.page >= state.pages });
    var first = state.total ? (state.page - 1) * state.size + 1 : 0;
    var last = Math.min(state.total, state.page * state.size);
    pages.querySelector("[data-wm-page-where]").textContent = "Show " + first + "–" + last + " of " + state.total;
    pages.querySelector("[data-wm-page-size]").value = String(state.size);
  }

  pages.querySelector("[data-wm-page-size]").addEventListener("change", function (event) {
    state.size = Number(event.target.value);
    document.cookie = "wm_contacts_size=" + state.size + "; path=/; max-age=31536000; samesite=lax";
    state.page = 1;
    load();
  });

  // the top bar's search: found as it's typed
  var search = document.querySelector("[data-wm-contacts-search]");
  if (search) {
    var field = search.querySelector("input[name=q]");
    var timer = null;
    field.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = field.value.trim();
        state.page = 1;
        load();
      }, 250);
    });
    search.addEventListener("submit", function (event) {
      event.preventDefault();
      clearTimeout(timer);
      state.q = field.value.trim();
      state.page = 1;
      load();
    });
  }

  // the contact books
  document.querySelectorAll(".wm-book[data-book]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      state.book = link.dataset.book;
      state.page = 1;
      document.querySelectorAll(".wm-book[data-book]").forEach(function (other) {
        other.classList.toggle("is-current", other === link);
        if (other === link) other.setAttribute("aria-current", "page");
        else other.removeAttribute("aria-current");
      });
      document.dispatchEvent(new CustomEvent("wm:side-close"));
      load();
    });
  });

  // --- ticks ---
  function ticked() {
    return Array.prototype.map.call(body.querySelectorAll("[data-wm-contact-tick]:checked"), function (tick) {
      return tick.closest("tr").dataset.id;
    });
  }
  function clearTicks() {
    acrossPages = false;
    body.querySelectorAll("[data-wm-contact-tick]").forEach(function (tick) { tick.checked = false; });
    allTick.checked = false;
    showBulk();
  }
  function showBulk() {
    var ids = ticked();
    var onPage = body.querySelectorAll("[data-wm-contact-tick]").length;
    bulk.hidden = !ids.length;
    body.querySelectorAll("tr").forEach(function (row) {
      row.classList.toggle("is-ticked", row.querySelector("[data-wm-contact-tick]").checked);
    });
    allTick.checked = !!onPage && ids.length === onPage;
    allTick.indeterminate = !!ids.length && ids.length < onPage;
    if (!ids.length) return;
    var label = bulk.querySelector("[data-wm-bulk-label]");
    if (acrossPages) {
      label.textContent = "All " + state.total + " selected";
      everyButton.hidden = true;
    } else {
      label.textContent = ids.length + (ids.length === 1 ? " item" : " items") + " selected";
      everyButton.hidden = !(ids.length === onPage && state.total > onPage);
      everyButton.textContent = "Select all " + state.total + " items";
    }
  }
  body.addEventListener("change", function (event) {
    if (!event.target.matches("[data-wm-contact-tick]")) return;
    acrossPages = false;
    showBulk();
  });
  allTick.addEventListener("change", function () {
    acrossPages = false;
    body.querySelectorAll("[data-wm-contact-tick]").forEach(function (tick) { tick.checked = allTick.checked; });
    showBulk();
  });
  everyButton.addEventListener("click", function () {
    acrossPages = true;
    showBulk();
  });
  bulk.querySelector("[data-wm-clear-ticks]").addEventListener("click", clearTicks);
  bulk.querySelector("[data-wm-delete-ticked]").addEventListener("click", function () {
    var count = acrossPages ? state.total : ticked().length;
    remove(acrossPages ? { all: true, q: state.q, book: state.book } : { ids: ticked() }, count);
  });

  function remove(what, count) {
    return wm.confirm(count === 1 ? {
      title: "Delete contact?", text: "This contact will be permanently deleted. This action cannot be undone.",
      yes: "Yes, delete", no: "No, don’t delete", danger: true,
    } : {
      title: "Delete " + count + " contacts?", text: "These contacts will be permanently deleted. This action cannot be undone.",
      yes: "Yes, delete", no: "No, don’t delete", danger: true,
    }).then(function (yes) {
      if (!yes) return false;
      return wm.request(page.dataset.deleteUrl, {
        method: "POST", body: what, failTitle: count === 1 ? "Contact could not be deleted" : "Some contacts could not be deleted",
      }).then(function (answer) {
        wm.toast(answer.message);
        if (state.page > 1 && count >= body.querySelectorAll("tr").length) state.page -= 1;
        load();
        return true;
      }, function () {
        load();
        return false;
      });
    });
  }

  // --- a row: opened, or its options ---
  body.addEventListener("click", function (event) {
    var row = event.target.closest("tr");
    if (!row) return;
    var menu = event.target.closest("[data-wm-contact-menu]");
    if (menu) {
      wm.menu(menu, [
        { label: "View details", icon: "eye", act: function () { view(row.dataset.id); } },
        { label: "Edit contact", icon: "edit", act: function () { fetchContact(row.dataset.id).then(openForm); } },
        { label: "Delete contact", icon: "trash", danger: true, act: function () { remove({ ids: [row.dataset.id] }, 1); } },
      ]);
      return;
    }
    if (event.target.closest("[data-wm-contact-open], .wm-contact-cell")) view(row.dataset.id);
  });

  function fetchContact(id) {
    return wm.request(url + "/" + encodeURIComponent(id), { failTitle: "Couldn't open the contact" }).then(function (answer) {
      return answer.contact;
    });
  }

  function avatar(contact, big) {
    var made = document.createElement("span");
    made.className = "wm-contact-avatar" + (big ? " is-big" : "");
    made.setAttribute("aria-hidden", "true");
    if (contact.photo) {
      var image = document.createElement("img");
      image.src = contact.photo;
      image.alt = "";
      made.appendChild(image);
    } else {
      made.textContent = contact.initials || "?";
    }
    return made;
  }

  function birthdayText(value) {
    var parts = value.replace(/^--/, "").split("-");
    if (value.indexOf("--") === 0) return MONTHS[Number(parts[0]) - 1] + " " + Number(parts[1]);
    return MONTHS[Number(parts[1]) - 1] + " " + Number(parts[2]) + ", " + parts[0];
  }

  // --- Contact details ---
  var viewDialog = document.querySelector("[data-wm-contact-view]");
  var viewBody = viewDialog.querySelector("[data-wm-view-body]");
  var viewing = null;

  function closeOnBackdrop(dialog, close) {
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) close();
    });
  }
  closeOnBackdrop(viewDialog, function () { viewDialog.close(); });
  viewDialog.querySelector("[data-wm-close]").addEventListener("click", function () { viewDialog.close(); });

  function group(title, iconName, rows) {
    rows = rows.filter(Boolean);
    if (!rows.length) return null;
    var section = document.createElement("section");
    section.className = "wm-contact-group";
    var head = document.createElement("h3");
    head.className = "wm-contact-group-title";
    head.appendChild(wm.icon(iconName));
    head.appendChild(document.createTextNode(title));
    section.appendChild(head);
    rows.forEach(function (row) { section.appendChild(row); });
    return section;
  }
  function line(label, value, options) {
    if (!value) return null;
    options = options || {};
    var row = document.createElement("div");
    row.className = "wm-contact-line";
    var name = document.createElement("span");
    name.className = "wm-contact-label";
    name.textContent = label;
    var text = document.createElement(options.href ? "a" : "span");
    text.className = "wm-contact-value";
    text.textContent = value;
    if (options.href) text.href = options.href;
    var holder = document.createElement("span");
    holder.className = "wm-contact-value-wrap";
    holder.appendChild(text);
    if (options.copy) {
      var copy = document.createElement("button");
      copy.type = "button";
      copy.className = "wm-icon wm-mini";
      copy.setAttribute("data-wm-copy", value);
      copy.setAttribute("data-copied", options.copy + " copied!");
      copy.setAttribute("aria-label", "Copy " + options.copy.toLowerCase());
      copy.setAttribute("data-tip", "Copy");
      copy.appendChild(wm.icon("copy"));
      holder.appendChild(copy);
    }
    row.appendChild(name);
    row.appendChild(holder);
    return row;
  }

  function view(id) {
    fetchContact(id).then(function (contact) {
      viewing = contact;
      viewBody.innerHTML = "";
      var identity = document.createElement("div");
      identity.className = "wm-contact-identity";
      identity.appendChild(avatar(contact, true));
      var who = document.createElement("div");
      who.className = "wm-contact-who-text";
      var name = document.createElement("p");
      name.className = "wm-contact-big-name";
      name.textContent = contact.display_name;
      who.appendChild(name);
      var job = [contact.job_title, contact.company].filter(Boolean).join(" · ");
      if (job) {
        var jobLine = document.createElement("p");
        jobLine.className = "wm-contact-job";
        jobLine.textContent = job;
        who.appendChild(jobLine);
      }
      identity.appendChild(who);
      viewBody.appendChild(identity);
      var fullName = [contact.first_name, contact.last_name].filter(Boolean).join(" ");
      [
        group("Name", "user", [line("Display name", contact.display_name), fullName !== contact.display_name ? line("Name", fullName) : null]),
        group("Email", "mail", contact.emails.map(function (one) {
          return line(TYPES[one.type], one.value, { href: mailUrl + "?compose=" + encodeURIComponent("mailto:" + one.value), copy: "Email" });
        })),
        group("Phone", "phone", contact.phones.map(function (one) {
          return line(TYPES[one.type], one.value, { href: "tel:" + one.value.replace(/[^0-9+]/g, ""), copy: "Phone" });
        })),
        group("Job", "briefcase", [line("Job title", contact.job_title),
                                   line("Organization", [contact.company, contact.department].filter(Boolean).join(", "))]),
        group("Address", "pin", contact.addresses.map(function (one) {
          var text = [one.street, [one.postcode, one.city].filter(Boolean).join(" "), one.state, one.country].filter(Boolean).join("\n");
          return line(TYPES[one.type], text, { copy: "Address" });
        })),
        group("Birthday", "cake", [contact.birthday ? line("Birthday", birthdayText(contact.birthday)) : null]),
        group("Notes", "note", [line("Notes", contact.notes)]),
      ].forEach(function (section) {
        if (section) viewBody.appendChild(section);
      });
      if (!viewDialog.open) viewDialog.showModal();
    });
  }
  viewDialog.querySelector("[data-wm-view-edit]").addEventListener("click", function () {
    viewDialog.close();
    if (viewing) openForm(viewing);
  });
  viewDialog.querySelector("[data-wm-view-delete]").addEventListener("click", function () {
    if (!viewing) return;
    remove({ ids: [viewing.id] }, 1).then(function (done) {
      if (done) viewDialog.close();
    });
  });

  // --- the form ---
  var formDialog = document.querySelector("[data-wm-contact-form-dialog]");
  var form = formDialog.querySelector("[data-wm-contact-form]");
  var problem = form.querySelector("[data-wm-problem]");
  var formAvatar = form.querySelector("[data-wm-form-avatar]");
  var photoInput = form.querySelector("[data-wm-photo-input]");
  var photoRemove = form.querySelector("[data-wm-photo-remove]");
  var displayName = form.querySelector('[name="display_name"]');
  var editing = null;
  var photo = "";
  var changed = false;
  var namedByHand = false;

  function input(name) {
    return form.querySelector('[name="' + name + '"]');
  }

  function addRow(kind, value) {
    var section = form.querySelector('[data-wm-list-of="' + kind + '"]');
    var rows = section.querySelector("[data-wm-rows]");
    var made = document.querySelector('[data-wm-row="' + kind + '"]').content.firstElementChild.cloneNode(true);
    if (value) {
      made.querySelectorAll("[data-field]").forEach(function (field) {
        if (value[field.dataset.field] !== undefined) field.value = value[field.dataset.field];
      });
    }
    rows.appendChild(made);
    section.querySelector("[data-wm-add]").hidden = rows.children.length >= 10;
    return made;
  }
  form.querySelectorAll("[data-wm-list-of]").forEach(function (section) {
    section.querySelector("[data-wm-add]").addEventListener("click", function () {
      var made = addRow(section.dataset.wmListOf);
      var first = made.querySelector("input");
      if (first) first.focus();
      changed = true;
    });
    section.addEventListener("click", function (event) {
      var removeButton = event.target.closest("[data-wm-remove]");
      if (!removeButton) return;
      removeButton.closest(".wm-contact-row").remove();
      section.querySelector("[data-wm-add]").hidden = false;
      changed = true;
    });
  });

  function readRows(kind) {
    return Array.prototype.map.call(form.querySelectorAll('[data-wm-list-of="' + kind + '"] .wm-contact-row'), function (row) {
      var made = {};
      row.querySelectorAll("[data-field]").forEach(function (field) { made[field.dataset.field] = field.value.trim(); });
      return made;
    });
  }

  function showPhoto() {
    formAvatar.innerHTML = "";
    if (photo) {
      var image = document.createElement("img");
      image.src = photo;
      image.alt = "";
      formAvatar.appendChild(image);
    } else {
      formAvatar.appendChild(wm.icon("user"));
    }
    form.querySelector("[data-wm-photo-label]").textContent = photo ? "Change photo" : "Add photo";
    photoRemove.hidden = !photo;
  }

  function openForm(contact) {
    editing = contact || null;
    form.querySelector("[data-wm-form-title]").textContent = contact ? "Edit contact" : "Add new contact";
    ["display_name", "first_name", "last_name", "job_title", "company", "department", "birthday", "notes"].forEach(function (name) {
      input(name).value = contact ? (contact[name] || "") : "";
    });
    if (contact && contact.birthday && contact.birthday.indexOf("--") === 0) input("birthday").value = "";   // (no year: kept as it is)
    form.querySelectorAll("[data-wm-rows]").forEach(function (rows) { rows.innerHTML = ""; });
    ["emails", "phones", "addresses"].forEach(function (kind) {
      var items = contact ? contact[kind] : [];
      if (!items.length && kind !== "addresses") addRow(kind);
      items.forEach(function (item) { addRow(kind, item); });
      form.querySelector('[data-wm-list-of="' + kind + '"] [data-wm-add]').hidden = items.length >= 10;
    });
    photo = contact ? contact.photo || "" : "";
    showPhoto();
    problem.hidden = true;
    changed = false;
    namedByHand = !!(contact && contact.display_name);
    formDialog.showModal();
    displayName.focus();
  }
  document.querySelectorAll("[data-wm-new-contact]").forEach(function (button) {
    button.addEventListener("click", function () { openForm(null); });
  });

  // the display name follows the first and last name, until it's typed itself
  displayName.addEventListener("input", function () { namedByHand = !!displayName.value.trim(); });
  ["first_name", "last_name"].forEach(function (name) {
    input(name).addEventListener("input", function () {
      if (namedByHand) return;
      displayName.value = [input("first_name").value.trim(), input("last_name").value.trim()].filter(Boolean).join(" ");
    });
  });
  form.addEventListener("input", function () { changed = true; });
  form.addEventListener("change", function () { changed = true; });

  // a photo: made 256 pixels square (the middle of it), as a JPEG
  photoInput.addEventListener("change", function () {
    var file = photoInput.files && photoInput.files[0];
    photoInput.value = "";
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var image = new Image();
      image.onload = function () {
        var side = Math.min(image.naturalWidth, image.naturalHeight);
        var canvas = document.createElement("canvas");
        canvas.width = canvas.height = 256;
        canvas.getContext("2d").drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, 0, 0, 256, 256);
        var made = canvas.toDataURL("image/jpeg", 0.86);
        if (made.length > 300000) {
          wm.board("Photo is too large", "This photo is too large to use, even after resizing. Please choose another one.");
          return;
        }
        photo = made;
        changed = true;
        showPhoto();
      };
      image.onerror = function () { wm.board("Upload failed", "Make sure your photo is under 5 MB and in PNG, JPG, or JPEG format."); };
      image.src = reader.result;
    };
    if (file.size > 5 * 1024 * 1024) {
      wm.board("Upload failed", "Make sure your photo is under 5 MB and in PNG, JPG, or JPEG format.");
      return;
    }
    reader.readAsDataURL(file);
  });
  photoRemove.addEventListener("click", function () {
    photo = "";
    changed = true;
    showPhoto();
  });

  function cancel() {
    if (!changed) {
      formDialog.close();
      return;
    }
    wm.confirm({ title: "Discard contact?", text: "This contact will not be saved.", yes: "Yes, discard", no: "No, do not discard",
                 danger: true }).then(function (yes) {
      if (yes) formDialog.close();
    });
  }
  form.querySelectorAll("[data-wm-form-cancel]").forEach(function (button) { button.addEventListener("click", cancel); });
  formDialog.addEventListener("cancel", function (event) {
    event.preventDefault();
    cancel();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    problem.hidden = true;
    var contact = {
      display_name: displayName.value, first_name: input("first_name").value, last_name: input("last_name").value,
      job_title: input("job_title").value, company: input("company").value, department: input("department").value,
      birthday: input("birthday").value || (editing && editing.birthday && editing.birthday.indexOf("--") === 0 ? editing.birthday : ""),
      notes: input("notes").value, photo: photo, book: state.book,
      emails: readRows("emails").map(function (one) { return { type: one.type, value: one.value }; }),
      phones: readRows("phones").map(function (one) { return { type: one.type, value: one.value }; }),
      addresses: readRows("addresses"),
    };
    if (!contact.display_name.trim() && !contact.first_name.trim() && !contact.last_name.trim()) {
      problem.textContent = "Display name is required";
      problem.hidden = false;
      displayName.focus();
      return;
    }
    var button = form.querySelector('[type="submit"]');
    button.disabled = true;
    wm.request(editing ? url + "/" + encodeURIComponent(editing.id) : url, { method: "POST", body: contact, quiet: true })
      .then(function (answer) {
        button.disabled = false;
        changed = false;
        formDialog.close();
        wm.toast(answer.message);
        load(true);
      }, function (error) {
        button.disabled = false;
        problem.textContent = error.problem || "Something went wrong. Please try again.";
        problem.hidden = false;
      });
  });

  draw();
})();

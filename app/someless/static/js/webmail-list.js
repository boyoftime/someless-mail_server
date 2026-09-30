// The webmail's list of mail (webmail-mail.html). It opens with the newest 50 messages, and when
// it's scrolled to within a screen or so of its end, the next 50 come in below (mail.py /list),
// until there are no more; "Loading more mail…" shows at the end meanwhile. "Sort and filter"
// (the folder's own, kept for next time: mail.py /view) draws the list again as chosen. Refresh
// brings in what's new at the top and the folders' counts, without a new page. For the other
// scripts, as wm.list: rows(), rowFor(id), remove(ids), refresh(), total().
(function () {
  var section = document.querySelector("[data-wm-list]");
  var scroll = document.querySelector("[data-wm-scroll]");
  var list = document.querySelector("[data-wm-messages]");
  if (!section || !scroll || !list || !window.wm) return;
  var empty = section.querySelector("[data-wm-list-empty]");
  var more = section.querySelector("[data-wm-more]");
  var NEAR = 700;        // px from the end: the next mail is asked for before it's reached
  var WAIT_AFTER = 5000; // ms before trying again after a failure
  var loading = false;
  var turning = null;    // the arrows in "Loading more mail…", only while it's asked for
  var triedAt = 0;       // the last failure
  var queued = false;
  var total = Number(section.dataset.total || 0);

  function rows() {
    return Array.prototype.slice.call(list.querySelectorAll(".wm-message"));
  }
  function rowFor(id) {
    return id ? list.querySelector('.wm-message[data-id="' + CSS.escape(id) + '"]') : null;
  }
  function changed() {
    list.dispatchEvent(new CustomEvent("someless:rows"));   // (the open message and the ticks: webmail-read.js, webmail-actions.js)
  }
  function showTotal(value) {
    total = value;
    section.dataset.total = String(value);
    var results = section.querySelector("[data-wm-results]");
    results.textContent = value + (value === 1 ? " result" : " results");
    var chooseTotal = document.querySelector("[data-wm-choose-total]");
    if (chooseTotal) chooseTotal.textContent = value;
    if (empty) empty.hidden = rows().length > 0;
  }

  // --- more, as the list is scrolled down ---
  function setMore(url) {
    if (url) {
      if (!more) {
        more = document.createElement("p");
        more.className = "wm-more";
        more.setAttribute("data-wm-more", "");
        more.setAttribute("role", "status");
        more.innerHTML = '<span class="wm-more-art" aria-hidden="true"></span><span>Loading more mail…</span>';
        scroll.appendChild(more);
      }
      more.dataset.url = url;
      more.hidden = false;
    } else if (more) {
      turn(false);
      more.remove();
      more = null;
    }
  }

  // (the line is only in sight while the next mail is on its way, so the arrows turn only then)
  function turn(on) {
    if (on && !turning && more) {
      turning = wm.spinner();
      more.querySelector(".wm-more-art").appendChild(turning);
    } else if (!on && turning) {
      wm.spinner.stop(turning);
      turning = null;
    }
  }

  function near() {
    return scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - NEAR;
  }

  function load() {
    if (loading || !more || Date.now() - triedAt < WAIT_AFTER) return;
    loading = true;
    more.hidden = false;
    turn(true);
    var asked = more.dataset.url;
    wm.request(asked, { quiet: true })
      .then(function (answer) {
        loading = false;
        turn(false);
        if (!more || more.dataset.url !== asked) return;   // drawn again meanwhile
        var have = {};
        rows().forEach(function (row) { have[row.dataset.id] = true; });
        var holder = document.createElement("template");
        holder.innerHTML = answer.html;
        Array.prototype.forEach.call(holder.content.querySelectorAll(".wm-message"), function (row) {
          if (!have[row.dataset.id]) list.appendChild(row);   // (one that moved up meanwhile: shown once)
        });
        changed();
        setMore(answer.next);
        if (answer.next) check();   // a tall screen can still be near the end
      })
      .catch(function () {
        loading = false;
        turn(false);
        triedAt = Date.now();
        if (more) more.hidden = true;   // back when it's tried again
        wm.board("Couldn't load more mail", "The webmail didn't answer. Check your connection, then scroll down again.");
      });
  }

  function check() {
    queued = false;
    if (near()) load();
  }

  scroll.addEventListener("scroll", function () {
    if (queued) return;
    queued = true;
    requestAnimationFrame(check);
  }, { passive: true });

  // --- drawn again: sorted or filtered anew, or refreshed ---
  function draw(answer) {
    var open = document.querySelector("[data-wm-view]");
    var openId = open && open.dataset.open;
    var ticked = {};
    rows().forEach(function (row) {
      var box = row.querySelector("input[type=checkbox]");
      if (box.checked && !box.hasAttribute("data-auto")) ticked[row.dataset.id] = true;
    });
    list.innerHTML = answer.html;
    rows().forEach(function (row, index) {
      row.classList.remove("is-more");
      row.style.setProperty("--i", index);
      if (ticked[row.dataset.id]) row.querySelector("input[type=checkbox]").checked = true;
    });
    list.classList.remove("is-redrawn");
    void list.offsetWidth;
    list.classList.add("is-redrawn");
    scroll.scrollTop = 0;
    setMore(answer.next);
    showTotal(answer.total);
    if (openId) list.dispatchEvent(new CustomEvent("someless:rows"));
    changed();
    if (answer.next) check();
  }

  // What's new at the top, the rest as it is: rows not in the list yet come in where they belong,
  // and the ones there already take on their state (read, a favorite)
  function merge(answer) {
    var holder = document.createElement("template");
    holder.innerHTML = answer.html;
    var fresh = Array.prototype.slice.call(holder.content.querySelectorAll(".wm-message"));
    var came = [];
    // Gone meanwhile (deleted or moved on another device, or in a mail app): out of the list, as
    // far as the fresh piece reaches (the whole list, when it's all of the folder); rows further
    // down, loaded as the list was scrolled, are left as they are
    var freshIds = {};
    fresh.forEach(function (row) { freshIds[row.dataset.id] = true; });
    var here = rows();
    var reach = -1;
    here.forEach(function (row, index) { if (freshIds[row.dataset.id]) reach = index; });
    var gone = here.filter(function (row, index) { return !freshIds[row.dataset.id] && (!answer.next || index < reach); })
                   .map(function (row) { return row.dataset.id; });
    if (gone.length) {
      remove(gone);
      document.dispatchEvent(new CustomEvent("wm:gone-elsewhere", { detail: { ids: gone } }));
    }
    fresh.forEach(function (row, index) {
      var there = rowFor(row.dataset.id);
      if (there) {
        ["is-unread", "is-flagged"].forEach(function (name) { there.classList.toggle(name, row.classList.contains(name)); });
        there.dataset.unread = row.dataset.unread;
        there.dataset.flagged = row.dataset.flagged;
        var marks = row.querySelector(".wm-preview-line");
        if (marks) there.querySelector(".wm-preview-line").replaceWith(marks);
        return;
      }
      var after = null;   // the row it comes before: the next one of the fresh that's here already
      for (var next = index + 1; next < fresh.length && !after; next++) after = rowFor(fresh[next].dataset.id);
      row.classList.remove("is-more");
      row.classList.add("is-new");
      if (after) list.insertBefore(row, after);
      else if (!more) list.appendChild(row);   // the end of the list, when all of it is here
      else return;
      came.push(row);
    });
    if (!rows().length || !fresh.length) setMore(answer.next);
    showTotal(answer.total);
    changed();
    return came;
  }

  function firstPiece() {
    var query = [];
    if (section.dataset.q) query.push("q=" + encodeURIComponent(section.dataset.q));
    if (section.dataset.in) query.push("in=" + encodeURIComponent(section.dataset.in));
    return section.dataset.listUrl + (query.length ? "?" + query.join("&") : "");
  }

  // the list drawn again from its start (its folder changed as a whole: all moved, all read)
  function reload() {
    return wm.request(firstPiece(), { quiet: true }).then(function (answer) {
      wm.counts(answer.counts, answer.unread);
      draw(answer);
    }, function () {});
  }

  function refresh(options) {
    options = options || {};
    return wm.request(firstPiece(), { quiet: !!options.quiet })
      .then(function (answer) {
        wm.counts(answer.counts, answer.unread);
        // the folders as they are now (made, renamed or deleted on another device): the rows stay
        // as they are when they're the same (webmail-folders.js)
        if (answer.folders && wm.folderActions) wm.folderActions.put(answer.folders);
        var came = merge(answer);
        document.dispatchEvent(new CustomEvent("wm:refreshed", { detail: { came: came } }));
        return came;
      });
  }

  function remove(ids) {
    var gone = 0;
    ids.forEach(function (id) {
      var row = rowFor(id);
      if (!row) return;
      gone += 1;
      if (wm.reduceMotion) {
        row.remove();
        return;
      }
      row.style.height = row.offsetHeight + "px";
      row.classList.add("is-leaving");
      requestAnimationFrame(function () { row.style.height = "0px"; });
      setTimeout(function () { row.remove(); if (empty) empty.hidden = rows().length > 0; }, 260);
    });
    showTotal(Math.max(0, total - gone));
    if (empty) setTimeout(function () { empty.hidden = rows().length > 0; }, 280);
    setTimeout(check, 300);   // fewer rows: the end may be near now
    changed();
  }

  // --- Sort and filter: the folder's own ---
  var toggle = section.querySelector("[data-wm-sort-toggle]");
  var box = section.querySelector("[data-wm-sort]");
  var badge = section.querySelector("[data-wm-sort-badge]");
  var reset = section.querySelector("[data-wm-sort-reset]");

  function chosen() {
    var sort = box.querySelector('[data-wm-sort-by][aria-checked="true"]');
    return {
      sort: sort ? sort.dataset.wmSortBy : "newest",
      filters: Array.prototype.map.call(box.querySelectorAll('[data-wm-filter][aria-checked="true"]'), function (option) {
        return option.dataset.wmFilter;
      }),
    };
  }

  function showChosen(sort, filters) {
    box.querySelectorAll("[data-wm-sort-by]").forEach(function (option) {
      option.setAttribute("aria-checked", String(option.dataset.wmSortBy === sort));
    });
    box.querySelectorAll("[data-wm-filter]").forEach(function (option) {
      option.setAttribute("aria-checked", String(filters.indexOf(option.dataset.wmFilter) >= 0));
    });
    badge.textContent = filters.length;
    badge.hidden = !filters.length;
    reset.disabled = sort === "newest" && !filters.length;
  }

  var asking = null;
  function apply() {
    var wanted = chosen();
    showChosen(wanted.sort, wanted.filters);
    if (asking) asking.abort();
    var ask = asking = new AbortController();
    section.classList.add("is-loading");
    wm.loading(section, true);
    wm.request(section.dataset.viewUrl, {
      method: "POST", signal: ask.signal, failTitle: "Couldn't sort the mail",
      body: { sort: wanted.sort, filters: wanted.filters, q: section.dataset.q, in: section.dataset.in },
    }).then(function (answer) {
      if (asking !== ask) return;
      asking = null;
      section.classList.remove("is-loading");
      wm.loading(section, false);
      draw(answer);
    }, function (error) {
      if (error.name === "AbortError") return;
      asking = null;
      section.classList.remove("is-loading");
      wm.loading(section, false);
    });
  }

  function setOpen(open) {
    box.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.classList.toggle("is-active", open);
    if (open) {
      document.dispatchEvent(new CustomEvent("someless:tips-away", { detail: { element: toggle } }));
      var first = box.querySelector(".wm-sort-option");
      if (first) first.focus({ preventScroll: true });
    }
  }

  if (toggle && box) {
    toggle.addEventListener("click", function () { setOpen(box.hidden); });
    box.addEventListener("click", function (event) {
      var option = event.target.closest(".wm-sort-option, [data-wm-sort-reset]");
      if (!option || option.disabled) return;
      if (option.hasAttribute("data-wm-sort-reset")) {
        showChosen("newest", []);
        setOpen(false);
      } else if (option.hasAttribute("data-wm-filter")) {
        option.setAttribute("aria-checked", String(option.getAttribute("aria-checked") !== "true"));
      } else {
        box.querySelectorAll("[data-wm-sort-by]").forEach(function (other) { other.setAttribute("aria-checked", "false"); });
        option.setAttribute("aria-checked", "true");
      }
      apply();
    });
    document.addEventListener("click", function (event) {
      if (!box.hidden && !box.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || box.hidden) return;
      setOpen(false);
      toggle.focus();
    });
    box.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      var options = Array.prototype.slice.call(box.querySelectorAll(".wm-sort-option, .wm-sort-reset:not(:disabled)"));
      var at = options.indexOf(document.activeElement);
      var next = options[(at + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length];
      if (next) next.focus();
    });
  }

  // the Refresh button at the top
  var again = document.querySelector("[data-wm-refresh]");
  if (again) {
    again.addEventListener("click", function () {
      again.classList.add("is-turning");
      refresh().then(function () {}, function () {}).then(function () {
        setTimeout(function () { again.classList.remove("is-turning"); }, 400);
      });
    });
  }

  // another folder's page (webmail-nav.js): its list, sort and filters in place of these
  function adopt(page) {
    var next = page.querySelector("[data-wm-list]");
    ["folder", "q", "in", "total", "viewUrl", "listUrl", "actions"].forEach(function (key) {
      section.dataset[key] = next.dataset[key] || "";
    });
    var head = section.querySelector(".wm-list-head");
    var nextHead = next.querySelector(".wm-list-head");
    head.classList.toggle("has-results", nextHead.classList.contains("has-results"));
    var results = section.querySelector("[data-wm-results]");
    var nextResults = next.querySelector("[data-wm-results]");
    results.hidden = nextResults.hidden;
    results.textContent = nextResults.textContent;
    section.querySelector("#wm-list-title").textContent = next.querySelector("#wm-list-title").textContent;
    if (box) {
      var sort = next.querySelector('[data-wm-sort-by][aria-checked="true"]');
      var filters = Array.prototype.map.call(next.querySelectorAll('[data-wm-filter][aria-checked="true"]'), function (option) {
        return option.dataset.wmFilter;
      });
      showChosen(sort ? sort.dataset.wmSortBy : "newest", filters);
      setOpen(false);
    }
    if (asking) asking.abort();
    asking = null;
    list.innerHTML = next.querySelector("[data-wm-messages]").innerHTML;
    rows().forEach(function (row, index) {
      row.classList.remove("is-more");
      row.style.setProperty("--i", index);
    });
    list.classList.remove("is-redrawn");
    void list.offsetWidth;
    list.classList.add("is-redrawn");
    var nextEmpty = next.querySelector("[data-wm-list-empty]");
    if (empty && nextEmpty) empty.innerHTML = nextEmpty.innerHTML;
    var nextMore = next.querySelector("[data-wm-more]");
    loading = false;
    triedAt = 0;
    setMore(nextMore ? nextMore.dataset.url : null);
    scroll.scrollTop = 0;
    showTotal(Number(section.dataset.total || 0));
    changed();
    check();
  }

  // --- the circles beside the mail: a contact's photo where there's one (contacts.py /photos),
  // asked for once for each address, for all the ones in sight at once ---
  var photos = {};   // address: its photo, or "" (asked: none)
  var MOST_AT_ONCE = 100;
  function showPhotos() {
    var wanted = [];
    Array.prototype.forEach.call(list.querySelectorAll(".wm-face[data-email]:not(.has-photo)"), function (face) {
      var email = face.dataset.email;
      if (photos[email]) {
        var picture = document.createElement("img");
        picture.alt = "";
        picture.src = photos[email];
        face.appendChild(picture);
        face.classList.add("has-photo");
      } else if (email && photos[email] === undefined && wanted.indexOf(email) < 0 && wanted.length < MOST_AT_ONCE) {
        wanted.push(email);
      }
    });
    if (!wanted.length || !section.dataset.photosUrl) return;
    wanted.forEach(function (email) { photos[email] = ""; });
    var query = wanted.map(function (email) { return "e=" + encodeURIComponent(email); }).join("&");
    wm.request(section.dataset.photosUrl + "?" + query, { quiet: true }).then(function (answer) {
      var found = answer.photos || {};
      Object.keys(found).forEach(function (email) { photos[email] = found[email]; });
      showPhotos();
    }, function () {
      wanted.forEach(function (email) { delete photos[email]; });   // (asked again next time)
    });
  }
  list.addEventListener("someless:rows", showPhotos);
  showPhotos();

  window.wm.list = {
    adopt: adopt,
    rows: rows, rowFor: rowFor, remove: remove, refresh: refresh, reload: reload, total: function () { return total; },
    section: section, element: list, scroll: scroll, changed: changed,
  };
  check();   // a screen taller than the first 50
})();

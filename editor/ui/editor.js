/* Website editor for Specialty Home Inspections LLC.
   Plain JavaScript, no libraries. Talks only to the editor server it was loaded from. */
(function () {
  "use strict";

  /* ================================================================ helpers */

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else if (k === "dataset") Object.keys(v).forEach(function (d) { el.dataset[d] = v[d]; });
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  function $(sel) { return document.querySelector(sel); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function get(obj, path) { return path.reduce(function (o, k) { return o == null ? undefined : o[k]; }, obj); }
  function set(obj, path, val) {
    var o = obj;
    for (var i = 0; i < path.length - 1; i++) o = o[path[i]];
    o[path[path.length - 1]] = val;
  }
  function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40); }
  function pathKey(p) { return p.join("."); }
  async function sha256(text) {
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.prototype.map.call(new Uint8Array(buf), function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }

  function api(path, body, opts) {
    opts = opts || {};
    var init = { method: body === undefined ? "GET" : "POST", credentials: "same-origin", headers: { "X-SHI": "1" } };
    if (body !== undefined) {
      if (body instanceof Blob) { init.body = body; init.headers["Content-Type"] = body.type || "application/octet-stream"; }
      else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
    }
    Object.assign(init.headers, opts.headers || {});
    return fetch(path, init).then(function (r) {
      if (r.status === 401) { window.location.href = "/login"; throw new Error("signed out"); }
      return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; d._ok = r.ok; return d; });
    });
  }

  var toastTimer;
  function toast(msg, kind) {
    var t = $("#toast");
    t.textContent = msg;
    t.className = "toast show " + (kind || "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = "toast"; }, 3200);
  }
  function busy(on, text) {
    $("#busy").hidden = !on;
    if (text) $("#busyText").textContent = text;
  }

  /* Simple modal dialog. buttons: [{label, kind, value}] -> resolves with value (null if closed) */
  function dialog(title, body, buttons, which) {
    var d = $(which || "#dlg");
    d.textContent = "";
    return new Promise(function (resolve) {
      var result = null;
      var close = function (v) { result = v; d.close(); };
      d.addEventListener("close", function () { resolve(result); }, { once: true });
      var foot = h("div", { class: "dlg-foot" });
      (buttons || [{ label: "OK", kind: "primary", value: true }]).forEach(function (b) {
        foot.appendChild(h("button", { class: "btn " + (b.kind || ""), type: "button", onclick: function () { close(b.value); } }, b.label));
      });
      d.appendChild(h("div", { class: "dlg-head" }, h("h2", { text: title }),
        h("button", { class: "icon-x", type: "button", "aria-label": "Close", onclick: function () { close(null); } }, "×")));
      d.appendChild(h("div", { class: "dlg-body" }, body));
      d.appendChild(foot);
      if (!d.open) d.showModal();
    });
  }
  function confirmBox(title, text, yesLabel, danger) {
    return dialog(title, h("p", { text: text }), [
      { label: "Cancel", value: false },
      { label: yesLabel || "Yes", kind: danger ? "danger" : "primary", value: true }
    ], "#dlg2").then(function (v) { return !!v; });
  }

  /* ================================================================ state */

  var S = {
    saved: null,        // last saved content
    content: null,      // what's being edited
    savedHash: "",
    published: {},
    media: [],
    targets: [],
    cfReady: false,
    siteUrl: "",
    undo: [],
    redo: [],
    lastPath: null,
    lastTime: 0,
    openKeys: {},       // which accordion cards are open
    issues: { errors: [], warnings: [] }
  };

  function isDirty() { return JSON.stringify(S.content) !== JSON.stringify(S.saved); }

  function commit(path, value, opts) {
    opts = opts || {};
    var key = path ? pathKey(path) : null;
    var now = Date.now();
    var coalesce = key && key === S.lastPath && now - S.lastTime < 1200 && !opts.structural;
    if (!coalesce) {
      S.undo.push(JSON.stringify(S.content));
      if (S.undo.length > 150) S.undo.shift();
      S.redo = [];
    }
    S.lastPath = key; S.lastTime = now;
    if (path) set(S.content, path, value);
    changed(opts.rerender, opts.anchor);
  }

  function changed(rerender, anchor) {
    if (rerender) renderForms(anchor);
    updateStatus();
    scheduleSync();
  }

  /* ---- keep your place: after the panel is redrawn, the thing you were working on
          is put back at exactly the same spot on the screen. */
  var lastTouched = null;
  document.addEventListener("pointerdown", function (e) {
    var el = e.target.closest && e.target.closest("#panel [data-path]");
    if (el) lastTouched = el.getAttribute("data-path");
  }, true);
  document.addEventListener("focusin", function (e) {
    var el = e.target.closest && e.target.closest("#panel [data-path]");
    if (el) lastTouched = el.getAttribute("data-path");
  });

  function scroller() {
    var panel = $("#panel");
    return getComputedStyle(panel).overflowY === "auto" || getComputedStyle(panel).overflowY === "scroll"
      ? panel : (document.scrollingElement || document.documentElement);
  }
  function findPath(path) {
    var parts = String(path || "").split(".");
    while (parts.length) {
      var el = document.querySelector('#panel [data-path="' + parts.join(".") + '"]');
      if (el && el.offsetParent !== null) return el;
      parts.pop();
    }
    return null;
  }
  function holdPlace(anchorPath, redraw) {
    var sc = scroller();
    var before = findPath(anchorPath);
    var oldTop = before ? before.getBoundingClientRect().top : null;
    var oldScroll = sc.scrollTop;
    var forms = $("#forms");
    forms.style.minHeight = forms.offsetHeight + "px";   // stop the page from collapsing while it's rebuilt
    redraw();
    sc.scrollTop = oldScroll;
    var fix = function () {
      var after = findPath(anchorPath);
      if (after && oldTop !== null) sc.scrollTop += after.getBoundingClientRect().top - oldTop;
    };
    fix();
    requestAnimationFrame(function () { requestAnimationFrame(function () { fix(); forms.style.minHeight = ""; fix(); }); });
  }

  function undo() {
    if (!S.undo.length) return;
    S.redo.push(JSON.stringify(S.content));
    S.content = JSON.parse(S.undo.pop());
    S.lastPath = null;
    changed(true);
  }
  function redo() {
    if (!S.redo.length) return;
    S.undo.push(JSON.stringify(S.content));
    S.content = JSON.parse(S.redo.pop());
    S.lastPath = null;
    changed(true);
  }

  /* ================================================================ status + sync */

  function updateStatus() {
    var pill = $("#status");
    var dirty = isDirty();
    if (dirty) { pill.textContent = "Unsaved changes"; pill.className = "pill warn"; }
    else if (S.published && S.published.hash && S.published.hash === S.savedHash) {
      pill.textContent = "Saved · Live on the website ✓"; pill.className = "pill ok";
    } else { pill.textContent = "Saved · Not on the website yet"; pill.className = "pill info"; }
    $("#undoBtn").disabled = !S.undo.length;
    $("#redoBtn").disabled = !S.redo.length;
    $("#saveBtn").disabled = !dirty;
    $("#saveBtn").textContent = dirty ? "Save" : "Saved";
    document.querySelectorAll(".card-save-btn, #panelSaveBtn").forEach(function (b) {
      b.disabled = !dirty;
      b.textContent = dirty ? "💾 Save" : "✓ Saved";
    });
    document.querySelectorAll(".card-save-note").forEach(function (n) { n.textContent = dirty ? "You have unsaved changes" : "All changes saved"; });
    var bar = $("#panelSave");
    if (bar) bar.classList.toggle("show", dirty);
  }

  var syncTimer = null, syncing = false, syncAgain = false;
  function scheduleSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(sync, 450);
  }
  function sync() {
    if (syncing) { syncAgain = true; return; }
    syncing = true;
    api("/api/draft", { content: S.content }).then(function (d) {
      if (d.issues) showIssues(d.issues);
      refreshPreview();
    }).catch(function () {}).finally(function () {
      syncing = false;
      if (syncAgain) { syncAgain = false; sync(); }
    });
  }

  function showIssues(issues) {
    S.issues = issues;
    var box = $("#issues");
    box.textContent = "";
    var list = [];
    (issues.errors || []).forEach(function (e) { list.push(h("li", { class: "err" }, e)); });
    (issues.warnings || []).forEach(function (w) { list.push(h("li", { class: "warnline" }, w)); });
    if (!list.length) { box.hidden = true; return; }
    box.appendChild(h("strong", { text: (issues.errors || []).length ? "Please fix before saving:" : "Heads up:" }));
    box.appendChild(h("ul", null, list));
    box.hidden = false;
  }

  /* ================================================================ preview (double-buffered so it never flashes) */

  /* The new preview loads invisibly behind the current one, jumps (no animation) to the same
     spot, and only then swaps in, so the page never flashes or scrolls while you edit. */
  var front = $("#frameA"), back = $("#frameB");
  front.classList.remove("hidden"); back.classList.remove("hidden");
  front.classList.add("live"); back.classList.add("buffer");
  var loadSeq = 0;
  function refreshPreview() {
    var y = 0, seq = ++loadSeq;
    try { y = front.contentWindow.scrollY; } catch (e) { /* not loaded */ }
    back.onload = function () {
      if (seq !== loadSeq) return;   // a newer edit is already loading
      var w = back.contentWindow;
      var settle = function (tries) {
        try { w.scrollTo({ top: y, left: 0, behavior: "instant" }); } catch (e) { /* ignore */ }
        var there = Math.abs(w.scrollY - y) < 2 || tries > 20;
        if (!there) return setTimeout(function () { settle(tries + 1); }, 25);
        w.requestAnimationFrame(function () {
          back.classList.remove("buffer"); back.classList.add("live"); back.removeAttribute("aria-hidden");
          front.classList.remove("live"); front.classList.add("buffer"); front.setAttribute("aria-hidden", "true");
          var t = front; front = back; back = t;
        });
      };
      settle(0);
    };
    back.src = "/preview?edit=1&t=" + Date.now();
  }

  /* Tablet and phone previews: the real device width, scaled down only if the screen is too small. */
  var DEVICES = { tablet: 820, phone: 390 };
  function fitFrames() {
    var holder = $("#frameHolder"), W = DEVICES[holder.dataset.device];
    [front, back].forEach(function (f) {
      if (!W) { f.style.cssText = ""; return; }
      var pad = 16, availW = holder.clientWidth - pad * 2, availH = holder.clientHeight - pad * 2;
      var scale = Math.min(1, availW / W);
      f.style.width = W + "px";
      f.style.height = Math.round(availH / scale) + "px";
      f.style.transform = "scale(" + scale + ")";
      f.style.left = Math.round((holder.clientWidth - W * scale) / 2) + "px";
      f.style.top = pad + "px";
    });
  }
  if (window.ResizeObserver) new ResizeObserver(fitFrames).observe($("#frameHolder"));
  window.addEventListener("resize", fitFrames);

  document.querySelectorAll("[data-device]").forEach(function (b) {
    b.addEventListener("click", function () {
      document.querySelectorAll("[data-device]").forEach(function (x) { x.classList.toggle("active", x === b); });
      $("#frameHolder").dataset.device = b.dataset.device;
      fitFrames();
    });
  });

  window.addEventListener("message", function (e) {
    if (e.origin !== window.location.origin || !e.data || e.data.type !== "shi-focus") return;
    jumpTo(String(e.data.path || ""));
  });

  function jumpTo(path) {
    var parts = path.split(".");
    while (parts.length) {
      var el = document.querySelector('[data-path="' + parts.join(".") + '"]');
      if (el) {
        var card = el.closest("details");
        while (card) { card.open = true; S.openKeys[card.dataset.key] = true; card = card.parentElement.closest("details"); }
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
        var input = el.matches("input, textarea") ? el : el.querySelector("input:not([type=checkbox]), textarea");
        if (input) setTimeout(function () { input.focus({ preventScroll: true }); }, 350);
        return;
      }
      parts.pop();
    }
  }

  /* ================================================================ field builders */

  function field(label, path, opts) {
    opts = opts || {};
    var id = "f-" + pathKey(path).replace(/[^a-z0-9]/gi, "-");
    var val = get(S.content, path);
    var input;
    if (opts.multiline) {
      input = h("textarea", { id: id, rows: opts.rows || 4, placeholder: opts.placeholder || "" });
      input.value = val == null ? "" : val;
      autoGrow(input);
    } else {
      input = h("input", { id: id, type: opts.type || "text", placeholder: opts.placeholder || "", maxlength: opts.max || null });
      input.value = val == null ? "" : val;
    }
    if (opts.readonly) input.readOnly = true;
    input.dataset.path = pathKey(path);
    input.addEventListener("input", function () {
      commit(path, input.value);
      if (opts.counter) counter.textContent = counterText();
      if (opts.multiline) autoGrow(input);
    });
    var counterText = function () { return input.value.length + " / about " + opts.counter + " letters"; };
    var counter = opts.counter ? h("span", { class: "counter", text: counterText() }) : null;
    var tools = opts.format ? formatBar(input, path) : null;
    return h("div", { class: "field" },
      h("label", { for: id }, label, counter),
      opts.help ? h("p", { class: "help", text: opts.help }) : null,
      tools, input);
  }

  function autoGrow(t) {
    requestAnimationFrame(function () { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 4, 520) + "px"; });
  }

  function formatBar(textarea, path) {
    function wrap(before, after, placeholder) {
      var s = textarea.selectionStart, e = textarea.selectionEnd, v = textarea.value;
      var sel = v.slice(s, e) || placeholder;
      textarea.value = v.slice(0, s) + before + sel + after + v.slice(e);
      textarea.focus();
      textarea.setSelectionRange(s + before.length, s + before.length + sel.length);
      commit(path, textarea.value);
    }
    return h("div", { class: "fmt" },
      h("button", { type: "button", class: "fmt-btn", title: "Make the selected words bold", onclick: function () { wrap("**", "**", "bold words"); } }, h("b", null, "B"), " Bold"),
      h("button", { type: "button", class: "fmt-btn", title: "Turn the selected words into a link", onclick: function () {
        dialog("Add a link", (function () {
          var inp = h("input", { type: "url", id: "linkUrl", placeholder: "https://www.example.com" });
          setTimeout(function () { inp.focus(); }, 50);
          return h("div", { class: "field" }, h("label", { for: "linkUrl" }, "Web address (or tel:850… for a phone number)"), inp);
        })(), [{ label: "Cancel", value: null }, { label: "Add link", kind: "primary", value: "ok" }]).then(function (v) {
          var url = (document.getElementById("linkUrl") || {}).value || "";
          if (v === "ok" && url.trim()) wrap("[", "](" + url.trim() + ")", "link text");
        });
      } }, "🔗 Link"),
      h("span", { class: "fmt-hint" }, "Blank line = new paragraph"));
  }

  /* A link field that can also take an uploaded PDF (stored in the media library). */
  function linkField(label, path) {
    var wrap = field(label, path, { placeholder: "https://…  or upload a PDF" });
    var cur = get(S.content, path) || "";
    wrap.appendChild(h("div", { class: "row-btns" },
      h("button", { type: "button", class: "btn small", onclick: function () {
        pickFiles(false, "pdf").then(function (ps) { if (ps[0]) commit(path, ps[0], { structural: true, rerender: true }); });
      } }, "📄 Upload a PDF here"),
      /^media\//.test(cur) ? h("a", { class: "btn small ghost", href: thumbUrl(cur), target: "_blank", rel: "noopener" }, "Open it") : null));
    return wrap;
  }

  function toggle(label, path, opts) {
    opts = opts || {};
    var id = "t-" + pathKey(path).replace(/[^a-z0-9]/gi, "-");
    var cur = get(S.content, path);
    var input = h("input", { id: id, type: "checkbox" });
    var def = opts.def === undefined ? true : opts.def;
    input.checked = cur === undefined ? def : !!cur;
    input.dataset.path = pathKey(path);
    input.addEventListener("change", function () {
      commit(path, opts.invert ? !input.checked : input.checked, { structural: true, rerender: !!opts.rerender });
    });
    return h("label", { class: "switch", for: id }, input, h("span", { class: "slider", "aria-hidden": "true" }), h("span", { text: label }));
  }

  function select(label, path, choices) {
    var id = "s-" + pathKey(path).replace(/[^a-z0-9]/gi, "-");
    var sel = h("select", { id: id });
    choices.forEach(function (c) { var o = h("option", { value: c[0] }, c[1]); sel.appendChild(o); });
    sel.value = get(S.content, path) || choices[0][0];
    sel.addEventListener("change", function () { commit(path, sel.value, { structural: true }); });
    return h("div", { class: "field" }, h("label", { for: id }, label), sel);
  }

  function color(label, path, fallback) {
    var id = "c-" + pathKey(path).replace(/[^a-z0-9]/gi, "-");
    var inp = h("input", { id: id, type: "color" });
    inp.value = get(S.content, path) || fallback;
    inp.addEventListener("input", function () { commit(path, inp.value); });
    return h("div", { class: "field color-field" }, h("label", { for: id }, label), inp);
  }

  /* --------- pictures */

  function thumbUrl(p) { return p ? "/files/" + p.replace(/^media\//, "media/") : ""; }

  function imagePicker(label, path, opts) {
    opts = opts || {};
    var cur = get(S.content, path);
    var img = cur ? h("img", { src: thumbUrl(cur), alt: "" }) : h("span", { class: "noimg", text: "No picture" });
    var wrap = h("div", { class: "field picker", dataset: { path: pathKey(path) } },
      h("span", { class: "label", text: label }),
      h("div", { class: "picker-row" },
        h("div", { class: "thumb" }, img),
        h("div", { class: "picker-btns" },
          h("button", { type: "button", class: "btn small", onclick: function () {
            openLibrary(true).then(function (chosen) { if (chosen) commit(path, chosen, { structural: true, rerender: true }); });
          } }, "Choose picture"),
          h("button", { type: "button", class: "btn small", onclick: function () {
            pickFiles(false).then(function (paths) { if (paths[0]) commit(path, paths[0], { structural: true, rerender: true }); });
          } }, "Upload new"),
          opts.removable && cur ? h("button", { type: "button", class: "btn small ghost", onclick: function () {
            commit(path, "", { structural: true, rerender: true });
          } }, "Remove") : null,
          opts.extra || null)));
    return wrap;
  }

  /* Shrink giant phone photos before upload so the website stays fast. Never touches existing files. */
  function prepareImage(file) {
    var big = file.size > 3 * 1024 * 1024;
    var heic = /heic|heif/i.test(file.type) || /\.hei[cf]$/i.test(file.name);
    if (!/^image\//.test(file.type) && !heic) return Promise.reject(new Error(file.name + " isn't a picture."));
    if (file.type === "image/gif") return Promise.resolve(file);
    return createImageBitmap(file).then(function (bmp) {
      var max = 2400;
      var scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
      if (scale === 1 && !big && !heic) { bmp.close && bmp.close(); return file; }
      var c = document.createElement("canvas");
      c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      bmp.close && bmp.close();
      var type = file.type === "image/png" ? "image/png" : "image/jpeg";
      return new Promise(function (res) { c.toBlob(function (b) { res(b); }, type, 0.86); });
    }).catch(function () {
      if (heic) throw new Error(file.name + " is an iPhone HEIC photo this browser can't open. Try Safari, or set the iPhone camera to “Most Compatible”.");
      return file;
    });
  }

  function upload(file, kind) {
    var prep = kind === "pdf" ? Promise.resolve(file) : prepareImage(file);
    return prep.then(function (blob) {
      return api("/api/upload", blob, { headers: { "X-Filename": encodeURIComponent(file.name).slice(0, 120), "X-Kind": kind || "image" } });
    }).then(function (d) {
      if (!d._ok) throw new Error(d.error || "Upload failed.");
      if (kind !== "pdf") S.media.push({ path: d.path, w: d.w, h: d.h, uploaded: true });
      return d.path;
    });
  }

  function pickFiles(multiple, kind) {
    var input = $("#fileInput");
    input.multiple = !!multiple;
    input.accept = kind === "pdf" ? "application/pdf,.pdf" : "image/*";
    input.value = "";
    return new Promise(function (resolve) {
      input.onchange = function () {
        var files = Array.prototype.slice.call(input.files || []);
        if (!files.length) return resolve([]);
        busy(true, kind === "pdf" ? "Adding the PDF…" : "Adding " + files.length + (files.length > 1 ? " pictures…" : " picture…"));
        var out = [], chain = Promise.resolve();
        files.forEach(function (f) {
          chain = chain.then(function () { return upload(f, kind).then(function (p) { out.push(p); }); })
            .catch(function (e) { toast(e.message, "bad"); });
        });
        chain.then(function () { busy(false); if (out.length) toast(kind === "pdf" ? "PDF added" : out.length + " picture" + (out.length > 1 ? "s" : "") + " added", "good"); resolve(out); });
      };
      input.click();
    });
  }

  function openLibrary(pickMode) {
    return new Promise(function (resolve) {
      var chosen = null;
      var grid = h("div", { class: "lib-grid" });
      function draw() {
        grid.textContent = "";
        if (!S.media.length) grid.appendChild(h("p", { class: "help", text: "No pictures yet. Use “Upload pictures” to add some." }));
        var items = S.media.slice().sort(function (a, b) { return (b.uploaded ? 1 : 0) - (a.uploaded ? 1 : 0) || a.path.localeCompare(b.path); });
        items.forEach(function (m) {
          var isLogo = m.path === "media/logo.jpg";
          var card = h("div", { class: "lib-item" + (isLogo ? " locked" : "") },
            h("button", { type: "button", class: "lib-pick", title: m.path, disabled: isLogo && pickMode, onclick: function () {
              if (!pickMode) return;
              chosen = m.path; resolve(chosen); $("#dlg").close();
            } }, h("img", { src: thumbUrl(m.path), alt: "", loading: "lazy" })),
            h("div", { class: "lib-meta" },
              h("span", { text: isLogo ? "🔒 Logo" : (m.w ? m.w + "×" + m.h : "") }),
              m.uploaded ? h("button", { type: "button", class: "link-btn", onclick: function () {
                confirmBox("Delete this picture?", "It will be removed from the picture library. (It's moved to a recovery folder, not destroyed.)", "Delete", true).then(function (ok) {
                  if (!ok) return;
                  api("/api/media/delete", { path: m.path }).then(function (d) {
                    if (!d._ok) toast(d.error, "bad");
                    else { S.media = S.media.filter(function (x) { return x.path !== m.path; }); toast("Picture deleted", "good"); }
                    draw();
                  });
                });
              } }, "Delete") : null));
          grid.appendChild(card);
        });
      }
      draw();
      var body = h("div", null,
        h("div", { class: "lib-top" },
          h("p", { class: "help", text: pickMode ? "Click a picture to use it. Your own uploads are first." : "All pictures the website can use." }),
          h("button", { type: "button", class: "btn primary small", onclick: function () {
            pickFiles(true).then(function () { draw(); });
          } }, "+ Upload pictures")),
        grid);
      dialog(pickMode ? "Choose a picture" : "Picture library", body, [{ label: "Close", value: null }]).then(function () {
        if (chosen === null) resolve(null);
      });
      $("#dlg").classList.add("wide");
      $("#dlg").addEventListener("close", function rm() { $("#dlg").classList.remove("wide"); $("#dlg").removeEventListener("close", rm); });
    });
  }

  /* Find the photo inside white borders and crop to it on the website (file itself unchanged). */
  function autoTrim(path) {
    return new Promise(function (resolve, reject) {
      var im = new Image();
      im.onload = function () {
        var c = document.createElement("canvas");
        c.width = im.naturalWidth; c.height = im.naturalHeight;
        var x = c.getContext("2d");
        x.drawImage(im, 0, 0);
        var d = x.getImageData(0, 0, c.width, c.height).data;
        var minX = c.width, minY = c.height, maxX = -1, maxY = -1;
        for (var yy = 0; yy < c.height; yy++) for (var xx = 0; xx < c.width; xx++) {
          var k = (yy * c.width + xx) * 4;
          if (d[k] < 235 || d[k + 1] < 235 || d[k + 2] < 235) {
            if (xx < minX) minX = xx; if (xx > maxX) maxX = xx; if (yy < minY) minY = yy; if (yy > maxY) maxY = yy;
          }
        }
        if (maxX < 0) return reject(new Error("The picture looks blank."));
        resolve({ x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 });
      };
      im.onerror = function () { reject(new Error("Couldn't open the picture.")); };
      im.src = thumbUrl(path);
    });
  }

  /* --------- lists */

  function listEditor(path, opts) {
    var items = get(S.content, path) || [];
    var box = h("div", { class: "list", dataset: { path: pathKey(path) } });
    var shownNo = 0;
    items.forEach(function (item, i) {
      var p = path.concat(i);
      var isHidden = isHiddenItem(item);
      if (!isHidden) shownNo++;
      var eye = opts.noHide ? null : h("button", { type: "button", class: "mini eye" + (isHidden ? " off" : ""),
        title: isHidden ? "Hidden. Click to show it on the website again" : "Shown. Click to hide it from the website (it isn't deleted)",
        "aria-label": isHidden ? "Show on website" : "Hide from website", "aria-pressed": isHidden ? "true" : "false",
        onclick: function () { toggleHidden(path, i); } }, isHidden ? "🙈" : "👁");
      var badge = isHidden ? h("span", { class: "hidden-tag", text: "Hidden on website" })
        : opts.numbered && (typeof opts.numbered !== "function" || opts.numbered()) ? h("span", { class: "num-tag", title: "Its number on the website", text: "#" + shownNo }) : null;
      var handle = h("button", { type: "button", class: "drag-handle", title: "Drag to move (or use the arrow keys)", "aria-label": "Drag to move item " + (i + 1) }, "⠿");
      handle.addEventListener("pointerdown", function (e) { startDrag(e, box, path); });
      handle.addEventListener("keydown", function (e) {
        if (e.key === "ArrowUp") { e.preventDefault(); move(path, i, -1); }
        if (e.key === "ArrowDown") { e.preventDefault(); move(path, i, 1); }
      });
      var controls = h("div", { class: "row-ctrls" },
        eye,
        h("button", { type: "button", class: "mini", title: "Move up", disabled: i === 0, onclick: function () { move(path, i, -1); } }, "↑"),
        h("button", { type: "button", class: "mini", title: "Move down", disabled: i === items.length - 1, onclick: function () { move(path, i, 1); } }, "↓"),
        opts.noRemove && opts.noRemove(item) ? null : h("button", { type: "button", class: "mini danger", title: "Remove", onclick: function () {
          var go = opts.confirmRemove ? confirmBox("Remove this?", opts.confirmRemove, "Remove", true) : Promise.resolve(true);
          go.then(function (ok) {
            if (!ok) return;
            var arr = clone(get(S.content, path)); arr.splice(i, 1);
            commit(path, arr, { structural: true, rerender: true });
          });
        } }, "✕"));
      box.appendChild(h("div", { class: "list-item" + (opts.compact ? " compact" : "") + (isHidden ? " is-hidden" : ""), dataset: { path: pathKey(p), index: String(i) } },
        items.length > 1 ? handle : null,
        h("div", { class: "list-body" }, badge, opts.render(item, p, i)), controls));
    });
    if (!opts.noAdd) {
      box.appendChild(h("div", { class: "list-add" },
        h("button", { type: "button", class: "btn small", onclick: function () {
          Promise.resolve(opts.make()).then(function (newItems) {
            if (!newItems) return;
            var arr = clone(get(S.content, path) || []);
            (Array.isArray(newItems) ? newItems : [newItems]).forEach(function (n) { arr.push(n); });
            commit(path, arr, { structural: true, rerender: true });
          });
        } }, "+ " + (opts.addLabel || "Add"))));
    }
    return box;
  }

  function isHiddenItem(item) { return !!(item && typeof item === "object" && item.hidden); }
  function toggleHidden(path, i) {
    var arr = clone(get(S.content, path)), it = arr[i];
    if (typeof it === "string") arr[i] = { text: it, hidden: true };
    else if (it.hidden) {
      delete it.hidden;
      if (Object.keys(it).length === 1 && "text" in it) arr[i] = it.text;   // back to plain text
    } else it.hidden = true;
    commit(path, arr, { structural: true, rerender: true, anchor: pathKey(path.concat(i)) });
    toast(isHiddenItem(arr[i]) ? "Hidden from the website (not deleted)" : "Shown on the website again", "good");
  }

  function move(path, i, dir) {
    var arr = clone(get(S.content, path));
    var j = i + dir;
    if (j < 0 || j >= arr.length) return;
    var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    moveTo(path, arr, j, dir < 0 ? "up" : "down");
  }
  function moveTo(path, arr, newIndex, focusWhich) {
    var anchor = pathKey(path.concat(newIndex));
    if (path.length === 1 && path[0] === "sections") anchor = "sections." + newIndex;
    commit(path, arr, { structural: true, rerender: true, anchor: anchor });
    var item = findPath(anchor);
    var again = item && item.querySelector(focusWhich === "up" ? '[title^="Move"][title*="up"]' : focusWhich === "down" ? '[title^="Move"][title*="down"]' : ".drag-handle");
    if (again && !again.disabled) again.focus({ preventScroll: true });
  }

  /* ---- drag to reorder (mouse, finger or pen) using the ⠿ handle */
  function startDrag(e, box, path) {
    if (e.button !== undefined && e.button !== 0) return;
    var item = e.currentTarget.closest(".list-item");
    if (!item) return;
    e.preventDefault();
    var handle = e.currentTarget, pid = e.pointerId;
    var sc = scroller();
    var startY = e.clientY, grabOffset = e.clientY - item.getBoundingClientRect().top;
    item.classList.add("dragging");
    document.body.classList.add("is-dragging");
    var autoTimer = null, lastY = e.clientY;
    function siblings() { return Array.prototype.filter.call(box.children, function (c) { return c.classList.contains("list-item"); }); }
    function place(y) {
      lastY = y;
      var list = siblings();
      for (var k = 0; k < list.length; k++) {
        var other = list[k];
        if (other === item) continue;
        var r = other.getBoundingClientRect();
        var mid = r.top + r.height / 2;
        var itemIdx = list.indexOf(item);
        if (k < itemIdx && y < mid) { box.insertBefore(item, other); return; }
        if (k > itemIdx && y > mid) { box.insertBefore(item, other.nextSibling); return; }
      }
    }
    function autoScroll() {
      var top = sc === document.scrollingElement ? 0 : sc.getBoundingClientRect().top;
      var bottom = sc === document.scrollingElement ? window.innerHeight : sc.getBoundingClientRect().bottom;
      var step = lastY < top + 60 ? -12 : lastY > bottom - 60 ? 12 : 0;
      if (step) { sc.scrollTop += step; place(lastY); }
    }
    // Listen on the whole window: moving the row inside the page would otherwise drop the drag.
    function onMove(ev) { if (ev.pointerId === pid) { ev.preventDefault(); place(ev.clientY); } }
    function onUp(ev) {
      if (ev && ev.pointerId !== undefined && ev.pointerId !== pid) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      clearInterval(autoTimer);
      item.classList.remove("dragging");
      document.body.classList.remove("is-dragging");
      var order = siblings().map(function (c) { return +c.dataset.index; });
      var moved = order.some(function (v, k) { return v !== k; });
      if (!moved) return;
      var old = get(S.content, path);
      var arr = order.map(function (k) { return clone(old[k]); });
      moveTo(path, arr, order.indexOf(+item.dataset.index), "drag");
      toast("Moved", "good");
    }
    autoTimer = setInterval(autoScroll, 30);
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    void startY; void grabOffset;
  }

  function stringItem(item, p) {
    if (item && typeof item === "object") p = p.concat("text");
    var inp = h("input", { type: "text" });
    inp.value = item && typeof item === "object" ? (item.text || "") : item;
    inp.dataset.path = pathKey(p);
    inp.addEventListener("input", function () { commit(p, inp.value); });
    return inp;
  }

  /* --------- accordion card */

  function decorateCards() {
    document.querySelectorAll("#forms details.card > .card-body").forEach(function (b) {
      if (b.querySelector(":scope > .card-save")) return;
      b.appendChild(h("div", { class: "card-save" },
        h("span", { class: "card-save-note" }),
        h("button", { type: "button", class: "btn small primary card-save-btn", onclick: function () { save(); } }, "💾 Save")));
    });
    updateStatus();
  }

  function card(key, title, sub, body, opts) {
    opts = opts || {};
    var d = h("details", { class: "card" + (opts.muted ? " muted-card" : ""), dataset: { key: key, path: opts.path || "" } });
    if (S.openKeys[key]) d.open = true;
    d.addEventListener("toggle", function () { S.openKeys[key] = d.open; });
    d.appendChild(h("summary", null,
      h("span", { class: "card-title" }, h("span", { text: title }), sub ? h("small", { text: sub }) : null),
      opts.badge ? h("span", { class: "badge " + (opts.badgeKind || ""), text: opts.badge }) : null,
      h("span", { class: "chev", "aria-hidden": "true" })));
    d.appendChild(h("div", { class: "card-body" }, body));
    return d;
  }

  /* ================================================================ section forms */

  var TYPE_NAMES = {
    hero: "Top of page", trust: "Trust badges", about: "About", text: "Text block", services: "Services",
    pricing: "Prices", feature: "Picture and text", reviews: "Reviews", list: "List", faq: "Questions and answers",
    badges: "Certifications", gallery: "Photo gallery", links: "Links", contact: "Contact"
  };

  function sectionBody(sec, i) {
    var P = ["sections", i];
    var f = [];
    var t = sec.type;
    if (t === "hero") {
      f.push(field("Small line above the headline", P.concat("eyebrow")));
      f.push(field("Headline", P.concat("title")));
      f.push(field("Opening paragraph", P.concat("lead"), { multiline: true, format: true }));
      f.push(field("Main button text", P.concat("primaryButton"), { help: "This button takes visitors to the contact section." }));
      f.push(toggle("Show a “Call” button next to it", P.concat("showCallButton")));
    }
    if (t === "trust") {
      f.push(h("p", { class: "help", text: "These show right under the top of the page." }));
      f.push(listEditor(P.concat("items"), {
        addLabel: "Add a badge",
        make: function () { return { image: "", label: "New badge", note: "", link: "" }; },
        render: function (it, p) {
          return [imagePicker("Picture", p.concat("image")), field("Title", p.concat("label")),
            field("Small note (optional)", p.concat("note")),
            field("Link when clicked (optional)", p.concat("link"), { help: "A web address, or “bbb” to use the BBB link from Business info." })];
        }
      }));
    }
    if (t === "about") {
      f.push(field("Heading", P.concat("title")));
      var crop = sec.photoCrop;
      f.push(imagePicker("Photo", P.concat("photo"), { extra: [
        h("button", { type: "button", class: "btn small", title: "Cut off white borders around the photo (the file itself isn't changed)", onclick: function () {
          autoTrim(sec.photo).then(function (box) {
            commit(P.concat("photoCrop"), box, { structural: true, rerender: true });
            toast("White edges trimmed", "good");
          }).catch(function (e) { toast(e.message, "bad"); });
        } }, "Trim white edges"),
        crop ? h("button", { type: "button", class: "btn small ghost", onclick: function () {
          var s = clone(get(S.content, P)); delete s.photoCrop;
          commit(P, s, { structural: true, rerender: true });
        } }, "Undo trim") : null] }));
      f.push(field("Photo description (for blind visitors and Google)", P.concat("photoAlt")));
      f.push(field("Text", P.concat("body"), { multiline: true, rows: 10, format: true }));
    }
    if (t === "text") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Text", P.concat("body"), { multiline: true, rows: 10, format: true }));
    }
    if (t === "services") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Introduction", P.concat("intro"), { multiline: true, format: true }));
      f.push(h("h4", { text: "Services offered" }));
      f.push(listEditor(P.concat("items"), { compact: true, addLabel: "Add a service", make: function () { return "New service"; }, render: stringItem }));
      f.push(field("Highlights box heading", P.concat("highlightsTitle")));
      f.push(h("h4", { text: "Highlights" }));
      f.push(listEditor(P.concat("highlights"), { compact: true, addLabel: "Add a highlight", make: function () { return "New highlight"; }, render: stringItem }));
    }
    if (t === "pricing") {
      f.push(field("Heading", P.concat("title")));
      f.push(listEditor(P.concat("rows"), {
        addLabel: "Add a price",
        make: function () { return { name: "New inspection", price: "$" }; },
        render: function (it, p) { return [field("What it is", p.concat("name")), field("Price", p.concat("price"))]; }
      }));
      f.push(field("Note under the prices", P.concat("note"), { multiline: true, rows: 2 }));
    }
    if (t === "feature") {
      f.push(field("Small tag above the heading (optional, e.g. NEW)", P.concat("kicker")));
      f.push(field("Heading", P.concat("title")));
      f.push(imagePicker("Picture (optional)", P.concat("image"), { removable: true }));
      f.push(field("Picture description", P.concat("imageAlt")));
      f.push(field("Text", P.concat("body"), { multiline: true, rows: 8, format: true }));
      f.push(linkField("When someone clicks the picture, open (optional)", P.concat("imageLink")));
      f.push(field("Button text (optional)", P.concat("buttonText")));
      f.push(linkField("Button link", P.concat("buttonUrl")));
      f.push(field("Second button text (optional)", P.concat("button2Text")));
      f.push(linkField("Second button link", P.concat("button2Url")));
    }
    if (t === "reviews") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Google reviews button text", P.concat("linkText")));
      f.push(listEditor(P.concat("items"), {
        addLabel: "Add a review",
        make: function () { return { quote: "", name: "", locked: false }; },
        noRemove: function () { return false; },
        confirmRemove: "This review will disappear from the website. You can always undo or bring it back from History.",
        render: reviewItem
      }));
    }
    if (t === "list") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Introduction", P.concat("intro"), { multiline: true, format: true }));
      f.push(toggle("Show numbers (1, 2, 3…)", P.concat("numbered"), { def: false, rerender: true }));
      f.push(listEditor(P.concat("items"), { compact: true, numbered: function () { return !!get(S.content, P.concat("numbered")); }, addLabel: "Add an item", make: function () { return "New item"; }, render: stringItem }));
    }
    if (t === "faq") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Introduction", P.concat("intro"), { multiline: true, format: true }));
      f.push(h("p", { class: "help", text: "Tap 👁 to hide a question without deleting it. The numbers on the website (1, 2, 3…) fix themselves." }));
      f.push(listEditor(P.concat("items"), {
        numbered: true,
        addLabel: "Add a question",
        make: function () { return { q: "New question?", a: "Answer." }; },
        render: function (it, p) {
          return [field("Question", p.concat("q")), field("Answer", p.concat("a"), { multiline: true, format: true }),
            it.allowAmount !== undefined ? toggle("Approved: this answer may mention a discount amount", p.concat("allowAmount"), { def: false }) : null];
        }
      }));
    }
    if (t === "badges") {
      f.push(field("Heading", P.concat("title")));
      f.push(h("h4", { text: "Featured (shown large)" }));
      f.push(listEditor(P.concat("featured"), {
        addLabel: "Add a featured badge",
        make: function () { return { image: "", alt: "", link: "" }; },
        render: function (it, p) { return [imagePicker("Picture", p.concat("image")), field("Name", p.concat("alt")), field("Link (optional)", p.concat("link"))]; }
      }));
      f.push(h("h4", { text: "All certifications" }));
      f.push(h("p", { class: "help", text: "Tap 👁 to hide one from the website without deleting it. Drag ⠿ to change the order; the first 12 shown are the ones visitors see before “Show all”." }));
      f.push(listEditor(P.concat("items"), {
        compact: true, addLabel: "Upload new certification badges",
        make: function () { return pickFiles(true).then(function (ps) { return ps.map(function (p) { return { image: p, alt: "" }; }); }); },
        render: function (it, p) {
          return h("div", { class: "badge-row" }, h("img", { src: thumbUrl(it.image), alt: "", loading: "lazy" }), stringItemObj(it, p.concat("alt"), "Name of this certification"));
        }
      }));
    }
    if (t === "gallery") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Introduction (optional)", P.concat("intro"), { multiline: true, format: true }));
      f.push(h("p", { class: "help", text: "This section only appears on the website once it has at least one photo." }));
      f.push(listEditor(P.concat("items"), {
        addLabel: "Upload photos",
        make: function () { return pickFiles(true).then(function (ps) { return ps.map(function (p) { return { image: p, caption: "" }; }); }); },
        render: function (it, p) {
          return h("div", { class: "badge-row" }, h("img", { src: thumbUrl(it.image), alt: "", loading: "lazy" }), stringItemObj(it, p.concat("caption"), "Caption (optional)"));
        }
      }));
    }
    if (t === "links") {
      f.push(field("Heading", P.concat("title")));
      f.push(listEditor(P.concat("groups"), {
        addLabel: "Add a group of links",
        make: function () { return { title: "New group", links: [] }; },
        render: function (g, p) {
          return [field("Group name", p.concat("title")), listEditor(p.concat("links"), {
            addLabel: "Add a link",
            make: function () { return { text: "Link name", url: "https://", note: "" }; },
            render: function (l, lp) { return [field("Link text", lp.concat("text")), field("Web address", lp.concat("url")), field("Note (optional)", lp.concat("note"))]; }
          })];
        }
      }));
    }
    if (t === "contact") {
      f.push(field("Heading", P.concat("title")));
      f.push(field("Text", P.concat("body"), { multiline: true, format: true }));
      f.push(h("p", { class: "help", text: "The phone number and email come from Business info." }));
    }
    return f;
  }

  function stringItemObj(item, p, placeholder) {
    var inp = h("input", { type: "text", placeholder: placeholder || "" });
    inp.value = get(S.content, p) || "";
    inp.dataset.path = pathKey(p);
    inp.addEventListener("input", function () { commit(p, inp.value); });
    return inp;
  }

  function reviewItem(r, p) {
    if (r.locked) {
      return h("div", { class: "review-locked" },
        h("p", { class: "lock-note" }, "🔒 Locked: copied word for word from the original website, so it can't be changed by accident."),
        h("blockquote", { text: "\"" + r.quote + "\"" }),
        h("p", { class: "review-who", text: r.name }),
        h("div", { class: "row-btns" },
          h("button", { type: "button", class: "btn small ghost", onclick: function () {
            confirmBox("Unlock this review?",
              "Reviews are a customer's own words. Only unlock it if the customer asked for a correction.",
              "Unlock", true).then(function (ok) {
              if (!ok) return;
              var o = clone(get(S.content, p));
              o.locked = false; delete o.quoteSha256; delete o.nameSha256;
              commit(p, o, { structural: true, rerender: true });
            });
          } }, "Unlock to edit")));
    }
    return h("div", null,
      field("What the customer said (their exact words)", p.concat("quote"), { multiline: true }),
      field("Name shown under it", p.concat("name"), { help: "Example: Jane Doe - Client" }),
      h("div", { class: "row-btns" },
        h("button", { type: "button", class: "btn small", title: "Protect these exact words from accidental changes", onclick: function () {
          var o = clone(get(S.content, p));
          if (!o.quote.trim() || !o.name.trim()) return toast("Fill in the review and the name first.", "bad");
          Promise.all([sha256(o.quote), sha256(o.name)]).then(function (hs) {
            o.locked = true; o.quoteSha256 = hs[0]; o.nameSha256 = hs[1];
            commit(p, o, { structural: true, rerender: true });
            toast("Review locked", "good");
          });
        } }, "🔒 Lock it")));
  }

  /* ================================================================ whole panel */

  function renderForms(anchorPath) {
    if (!$("#forms").childElementCount) return buildForms();
    holdPlace(anchorPath || lastTouched, buildForms);
  }

  function buildForms() {
    var c = S.content;
    var forms = $("#forms");
    forms.textContent = "";

    // Business info
    var B = ["business"];
    forms.appendChild(h("h3", { class: "group-title", text: "Business" }));
    forms.appendChild(card("business", "Business info", "Name, phone, email, links", [
      h("div", { class: "logo-lock" },
        h("img", { src: thumbUrl(c.business.logo.src), alt: "Logo" }),
        h("p", { class: "help" }, "🔒 The logo is protected and can't be changed or edited here.")),
      field("Business name", B.concat("name")),
      field("Owner", B.concat("owner")),
      field("Business started on", B.concat("founded"), { type: "date",
        help: "Write {years} in any text and the website shows how many years it's been since this date (it goes up by itself every year). {since} shows the year it started." }),
      field("License line", B.concat("credential")),
      field("Service area", B.concat("serviceArea")),
      field("Phone", B.concat("phone"), { type: "tel" }),
      field("Email", B.concat("email"), { type: "email" }),
      field("City", B.concat("city")),
      field("State", B.concat("region")),
      field("Website address", B.concat("siteUrl"), { help: "Used by Google. Change only if the domain changes." }),
      h("h4", { text: "Links" }),
      h("p", { class: "help", text: "Social pages: switch one on to show it in the Contact section." }),
      listEditor(["social"], { noHide: true,
        addLabel: "Add a social page",
        make: function () { return { name: "Instagram", url: "https://", show: false }; },
        render: function (it, p) {
          return [field("Name", p.concat("name")), field("Web address", p.concat("url")),
            toggle("Show on website", p.concat("show"), { def: false })];
        }
      }),
      field("Google reviews page", ["links", "googleReviews"]),
      field("BBB profile", ["links", "bbb"])
    ], { path: "business" }));

    forms.appendChild(card("hours", "Hours of operation", hoursSubtitle(), hoursBody(), { path: "hours" }));

    // Sections
    forms.appendChild(h("h3", { class: "group-title" }, "Page sections ", h("small", { text: "top to bottom, same order as the website" })));
    c.sections.forEach(function (sec, i) {
      var P = ["sections", i];
      var head = h("div", { class: "sec-head" },
        toggle("Show on website", P.concat("enabled"), { rerender: true }),
        h("div", { class: "sec-move" },
          h("button", { type: "button", class: "mini", title: "Move this section up", disabled: i === 0, onclick: function () { move(["sections"], i, -1); } }, "↑ Up"),
          h("button", { type: "button", class: "mini", title: "Move this section down", disabled: i === c.sections.length - 1, onclick: function () { move(["sections"], i, 1); } }, "↓ Down"),
          sec.type !== "hero" ? h("button", { type: "button", class: "mini danger", title: "Delete this section", onclick: function () {
            confirmBox("Delete the “" + (sec.title || TYPE_NAMES[sec.type]) + "” section?", "You can undo this, or bring it back later from History.", "Delete section", true).then(function (ok) {
              if (!ok) return;
              var arr = clone(c.sections); arr.splice(i, 1);
              commit(["sections"], arr, { structural: true, rerender: true });
            });
          } }, "Delete") : null));
      var navField = sec.type === "hero" ? null :
        field("Menu button (leave empty to keep it out of the menu)", P.concat("nav"), { placeholder: "e.g. FAQ" });
      var title = (sec.title || sec.eyebrow || "").replace(/\*\*/g, "");
      var badge = sec.enabled === false ? "Hidden" : (sec.type === "gallery" && !(sec.items || []).length ? "No photos yet" : null);
      forms.appendChild(card("sec-" + sec.id, TYPE_NAMES[sec.type] || sec.type, title, [head, navField].concat(sectionBody(sec, i)),
        { path: "sections." + i, badge: badge, badgeKind: "grey", muted: sec.enabled === false }));
    });
    forms.appendChild(h("div", { class: "add-section" },
      h("button", { type: "button", class: "btn", onclick: addSection }, "+ Add a new section")));

    // Look
    forms.appendChild(h("h3", { class: "group-title", text: "Look and feel" }));
    forms.appendChild(card("layout", "Page layout (A/B)", S.content.theme.layout === "mobile" ? "B: Phone layout on every screen" : "A: Computer layout on big screens", layoutBody()));
    forms.appendChild(card("theme", "Colors and style", "", [
      h("div", { class: "color-row" }, color("Main color (blue)", ["theme", "navy"], "#1b3a8c"), color("Accent color (red)", ["theme", "red"], "#d3333a")),
      h("button", { type: "button", class: "btn small", onclick: function () {
        var t = clone(c.theme); t.navy = "#1b3a8c"; t.red = "#d3333a";
        commit(["theme"], t, { structural: true, rerender: true });
      } }, "Use the logo colors"),
      select("Dark mode", ["theme", "mode"], [["auto", "Follow each visitor's phone/computer setting"], ["light", "Always light"], ["dark", "Always dark"]]),
      toggle("Gentle animations while scrolling", ["theme", "animations"])
    ]));
    forms.appendChild(card("seo", "Google and search engines", "Title and description", [
      field("Page title (shows in Google and on the browser tab)", ["seo", "title"], { counter: 60 }),
      field("Description (the grey text under the title in Google)", ["seo", "description"], { multiline: true, counter: 160 }),
      field("Keywords", ["seo", "keywords"], { multiline: true, rows: 2 })
    ]));
    forms.appendChild(card("statsSettings", "Visitor stats", (c.stats || {}).enabled ? "Counting visits (private, no cookies)" : "Off", [
      toggle("Count visits (anonymous: no cookies, no IP addresses stored)", ["stats", "enabled"], { def: true, rerender: true }),
      toggle("Skip visitors whose browser asks not to be tracked", ["stats", "respectPrivacySignals"], { def: true }),
      field("Where the counter lives", ["stats", "endpoint"], { help: "Leave as /api/hit while the website runs on the Pi. After moving the site to Cloudflare, use the address of the Pi's counter, e.g. https://stats.specialtyhomeinspections.biz/api/hit (see README)." }),
      h("button", { type: "button", class: "btn small", onclick: function () { window.SHI_openStats && window.SHI_openStats(); } }, "📈 Open the Visitors dashboard")
    ]));
    forms.appendChild(h("div", { class: "add-section" },
      h("button", { type: "button", class: "btn", onclick: function () { openLibrary(false); } }, "🖼 Picture library")));

    decorateCards();
  }

  /* ---------------- hours of operation ---------------- */
  var ZONES = [["America/Chicago", "Central Time"], ["America/New_York", "Eastern Time"],
    ["America/Denver", "Mountain Time"], ["America/Phoenix", "Arizona Time"], ["America/Los_Angeles", "Pacific Time"]];

  function ampm(t) {
    var p = String(t || "").split(":"); if (p.length < 2) return "?";
    var hh = +p[0]; return ((hh % 12) || 12) + ":" + p[1] + (hh < 12 ? " AM" : " PM");
  }
  function hoursSubtitle() {
    var hrs = S.content.hours || {};
    if (!hrs.show) return "Hidden on the website";
    var open = (hrs.schedule || []).filter(function (d) { return d.open; });
    if (!open.length) return "Closed every day";
    var same = open.length === 7 && open.every(function (d) { return d.from === open[0].from && d.to === open[0].to; });
    if (same) return open[0].from === open[0].to ? "Open 24 hours, every day" : "Every day, " + ampm(open[0].from) + " to " + ampm(open[0].to);
    return open.length + " days a week, hours vary";
  }

  function hoursBody() {
    var H = ["hours"];
    var hrs = S.content.hours;
    var rows = hrs.schedule.map(function (d, i) {
      var P = H.concat("schedule", i);
      var mk = function (k) {
        var inp = h("input", { type: "time", step: 300, "aria-label": d.day + (k === "from" ? " opens" : " closes") });
        inp.value = d[k] || "";
        inp.disabled = !d.open;
        inp.dataset.path = pathKey(P.concat(k));
        inp.addEventListener("change", function () { commit(P.concat(k), inp.value, { structural: true }); refreshHoursTitle(); });
        return inp;
      };
      var sw = h("input", { type: "checkbox", id: "day-" + i, "aria-label": d.day + " open" });
      sw.checked = !!d.open;
      sw.addEventListener("change", function () {
        var o = clone(get(S.content, P)); o.open = sw.checked;
        if (o.open && !o.from) { o.from = "05:00"; o.to = "23:30"; }
        commit(P, o, { structural: true, rerender: true });
      });
      return h("div", { class: "day-row" + (d.open ? "" : " closed"), dataset: { path: pathKey(P) } },
        h("label", { class: "switch day-switch", for: "day-" + i }, sw, h("span", { class: "slider", "aria-hidden": "true" }), h("span", { class: "day-name", text: d.day })),
        d.open ? h("div", { class: "day-times" }, h("span", { class: "muted small", text: "Opens" }), mk("from"), h("span", { class: "muted small", text: "Closes" }), mk("to"))
               : h("span", { class: "muted day-closed", text: "Closed all day" }));
    });

    var tz = h("select", { id: "hours-tz" });
    ZONES.forEach(function (z) { tz.appendChild(h("option", { value: z[0] }, z[1])); });
    tz.value = hrs.timezone || "America/Chicago";
    tz.addEventListener("change", function () {
      var o = clone(hrs); o.timezone = tz.value;
      o.zoneName = (ZONES.filter(function (z) { return z[0] === tz.value; })[0] || [0, "Central Time"])[1];
      commit(H, o, { structural: true, rerender: true });
    });

    function setAll(fn) {
      var o = clone(get(S.content, H)); o.schedule = o.schedule.map(fn);
      commit(H, o, { structural: true, rerender: true });
    }
    return [
      toggle("Show the hours and the two clocks on the website", H.concat("show"), { def: true, rerender: true }),
      h("p", { class: "help", text: "Visitors see their own time and yours, and a green “Open now” or “Opens in …” based on these hours." }),
      h("div", { class: "week" }, rows),
      h("div", { class: "row-btns" },
        h("button", { type: "button", class: "btn small", onclick: function () {
          var m = get(S.content, H.concat("schedule", 1));
          setAll(function (d) { return Object.assign({}, d, { open: m.open, from: m.from, to: m.to }); });
          toast("Monday's hours copied to every day", "good");
        } }, "Copy Monday to every day"),
        h("button", { type: "button", class: "btn small", onclick: function () {
          setAll(function (d) { return Object.assign({}, d, { open: true, from: "00:00", to: "00:00" }); });
        } }, "Open 24 hours, every day"),
        h("button", { type: "button", class: "btn small ghost", onclick: function () {
          setAll(function (d) { return Object.assign({}, d, { open: true, from: "05:00", to: "23:30" }); });
        } }, "Reset to 5:00 AM to 11:30 PM")),
      h("p", { class: "help", text: "Tip: if a day opens and closes at the same time (like 12:00 AM to 12:00 AM), it counts as open all day. Closing times after midnight work too." }),
      h("div", { class: "field" }, h("label", { for: "hours-tz" }, "Your time zone"), tz),
      field("Words shown when open", H.concat("openText")),
      field("Words shown when closed", H.concat("closedText"))
    ];
  }
  function refreshHoursTitle() {
    var sub = document.querySelector('details[data-key="hours"] .card-title small');
    if (sub) sub.textContent = hoursSubtitle();
  }

  /* ---------------- layout A/B ---------------- */
  function layoutBody() {
    var cur = S.content.theme.layout === "mobile" ? "mobile" : "responsive";
    function opt(val, letter, title, text) {
      return h("button", { type: "button", class: "choice layout-choice" + (cur === val ? " picked" : ""), "aria-pressed": cur === val ? "true" : "false",
        onclick: function () { commit(["theme", "layout"], val, { structural: true, rerender: true }); } },
        h("strong", null, h("span", { class: "ab", text: letter }), " " + title), h("span", { text: text }),
        cur === val ? h("em", { class: "picked-note", text: "✓ Shown to visitors" }) : null);
    }
    return [
      h("p", { class: "help", text: "Phones always get the phone layout. This decides what people on computers and big tablets see." }),
      h("div", { class: "choice-grid" },
        opt("responsive", "A", "Computer layout", "Wide sections side by side on big screens."),
        opt("mobile", "B", "Phone layout everywhere", "The phone version, as one centered column, on every screen.")),
      h("button", { type: "button", class: "btn", onclick: compareLayouts }, "Compare A and B side by side"),
      h("p", { class: "help", text: "Your choice goes live the next time you publish." })
    ];
  }

  function compareLayouts() {
    var W = 1280, Hh = 1700;
    function pane(val, letter, title) {
      var frame = h("iframe", { class: "ab-frame", title: "Layout " + letter, src: "/preview?layout=" + val + "&t=" + Date.now() });
      var box = h("div", { class: "ab-box" }, frame);
      var cur = S.content.theme.layout === "mobile" ? "mobile" : "responsive";
      return h("div", { class: "ab-pane" },
        h("div", { class: "ab-head" }, h("strong", null, h("span", { class: "ab", text: letter }), " " + title),
          h("button", { type: "button", class: "btn small " + (cur === val ? "" : "primary"), disabled: cur === val, onclick: function () {
            commit(["theme", "layout"], val, { structural: true, rerender: true });
            $("#dlg").close();
            toast("Layout " + letter + " chosen. Publish to make it live.", "good");
          } }, cur === val ? "✓ Current choice" : "Use " + letter)),
        box);
    }
    var body = h("div", { class: "ab-grid" },
      pane("responsive", "A", "Computer layout"), pane("mobile", "B", "Phone layout everywhere"));
    dialog("Compare layouts (as seen on a computer)", body, [{ label: "Close", value: null }]);
    var d = $("#dlg"); d.classList.add("xwide");
    d.addEventListener("close", function rm() { d.classList.remove("xwide"); d.removeEventListener("close", rm); });
    requestAnimationFrame(function () {
      d.querySelectorAll(".ab-box").forEach(function (box) {
        var scale = box.clientWidth / W;
        box.style.height = Math.round(Hh * scale) + "px";
        var f = box.querySelector("iframe");
        f.style.width = W + "px"; f.style.height = Hh + "px"; f.style.transform = "scale(" + scale + ")";
      });
    });
  }

  function addSection() {
    var choices = [["text", "Text block", "A heading and paragraphs"], ["feature", "Picture and text", "A picture beside some text"],
      ["list", "List", "A heading with a list of items"], ["faq", "Questions and answers", "Fold-out questions"],
      ["gallery", "Photo gallery", "Photos people can tap to enlarge"], ["links", "Links", "Groups of helpful links"],
      ["reviews", "Reviews", "Customer quotes"]];
    var picked = null;
    var grid = h("div", { class: "choice-grid" }, choices.map(function (ch) {
      return h("button", { type: "button", class: "choice", onclick: function () { picked = ch[0]; $("#dlg").close(); } },
        h("strong", { text: ch[1] }), h("span", { text: ch[2] }));
    }));
    dialog("What kind of section?", grid, [{ label: "Cancel", value: null }]).then(function () {
      if (!picked) return;
      var base = { text: { title: "New section", body: "Write something here." },
        feature: { kicker: "", title: "New section", image: "", imageAlt: "", body: "Write something here.", buttonText: "", buttonUrl: "" },
        list: { title: "New list", intro: "", numbered: false, items: ["First item"] },
        faq: { title: "Questions", intro: "", items: [{ q: "Question?", a: "Answer." }] },
        gallery: { title: "Photos", intro: "", items: [] },
        links: { title: "Links", groups: [{ title: "Links", links: [] }] },
        reviews: { title: "Reviews", linkText: "", items: [] } }[picked];
      var ids = S.content.sections.map(function (s) { return s.id; });
      var id = slug(base.title) || picked, n = 2;
      while (ids.indexOf(id) >= 0) id = slug(base.title) + "-" + n++;
      var sec = Object.assign({ id: id, type: picked, enabled: true, nav: null }, base);
      var arr = clone(S.content.sections);
      var contactAt = arr.findIndex(function (s) { return s.type === "contact"; });
      arr.splice(contactAt >= 0 ? contactAt : arr.length, 0, sec);
      S.openKeys["sec-" + id] = true;
      commit(["sections"], arr, { structural: true, rerender: true });
      setTimeout(function () { jumpTo("sections." + arr.indexOf(sec)); }, 50);
    });
  }

  /* ================================================================ save / publish / history */

  function save(note) {
    if (!isDirty()) return Promise.resolve(true);
    return api("/api/save", { content: S.content, note: note || "Saved" }).then(function (d) {
      if (!d._ok) {
        dialog("Couldn't save yet", h("ul", null, (d.errors || [d.error || "Unknown problem."]).map(function (e) { return h("li", { text: e }); })));
        return false;
      }
      S.saved = clone(S.content);
      S.savedHash = d.savedHash;
      $("#banner").hidden = true;
      updateStatus();
      toast("Saved ✓", "good");
      return true;
    });
  }

  function publishNow(force) {
    var go = isDirty() ? save("Saved before publishing") : Promise.resolve(true);
    go.then(function (ok) {
      if (!ok) return;
      if (!S.targets.length) {
        return dialog("Publishing isn't set up", h("p", { text: "Ask your son to run the editor setup so the website knows where to publish." }));
      }
      busy(true, "Publishing your website… this can take up to a minute.");
      api("/api/publish", { force: !!force }).then(function (d) {
        busy(false);
        if (d.needsConfirm) {
          return dialog("Publish anyway?", h("div", null,
            h("p", { text: "Before your changes go live, please check:" }),
            h("ul", null, d.warnings.map(function (w) { return h("li", { text: w }); }))),
            [{ label: "Go back", value: false }, { label: "Publish anyway", kind: "primary", value: true }]
          ).then(function (yes) { if (yes) publishNow(true); });
        }
        if (d.errors) {
          return dialog("Couldn't publish", h("ul", null, d.errors.map(function (e) { return h("li", { text: e }); })));
        }
        var rows = (d.results || []).map(function (r) {
          var name = r.target === "cloudflare" ? "Cloudflare" : "This computer's web server";
          return h("div", { class: "result " + (r.ok ? "good" : "bad") },
            h("strong", { text: (r.ok ? "✓ " : "✕ ") + name }),
            h("details", null, h("summary", { text: "Details" }), h("pre", { text: r.message })));
        });
        if (d.ok) {
          S.published = { hash: S.savedHash, when: new Date().toLocaleString() };
          updateStatus();
          var link = S.siteUrl ? h("p", null, h("a", { href: S.siteUrl, target: "_blank", rel: "noopener" }, "Open the website ↗")) : null;
          dialog("Your website is updated 🎉", h("div", null,
            h("p", { text: "Visitors will see the changes right away. If something looks old, they can refresh the page." }), link, rows));
        } else {
          dialog("Publishing had a problem", h("div", null, h("p", { text: d.error || "Nothing was broken: the website still shows the last version that worked." }), rows));
        }
      }).catch(function () {
        busy(false);
        toast("Lost contact with the editor while publishing.", "bad");
      });
    });
  }

  function showHistory() {
    api("/api/history").then(function (d) {
      var items = (d.items || []).slice(0, 80);
      var list = h("div", { class: "history" }, items.length ? items.map(function (it) {
        return h("div", { class: "hist-row" },
          h("div", null, h("strong", { text: it.when }), h("span", { class: "muted small", text: it.note ? " · " + it.note : "" })),
          h("div", { class: "row-btns" },
            h("a", { class: "btn small", href: "/preview?version=" + encodeURIComponent(it.id), target: "_blank", rel: "noopener" }, "Look at it"),
            h("button", { type: "button", class: "btn small primary", onclick: function () {
              api("/api/history/" + encodeURIComponent(it.id)).then(function (v) {
                if (!v.content) return toast("Couldn't open that version.", "bad");
                S.undo.push(JSON.stringify(S.content)); S.redo = [];
                S.content = v.content;
                $("#dlg").close();
                changed(true);
                toast("That version is back. Save and publish when you're happy.", "good");
              });
            } }, "Bring this back")));
      }) : h("p", { text: "No saved versions yet. Every time you save, a copy is kept here." }));
      dialog("History", h("div", null,
        h("p", { class: "help", text: "Every save and every publish keeps a copy. Bringing one back does not change the live website until you publish." }), list),
        [{ label: "Close", value: null }]);
    });
  }

  function showHelp() {
    dialog("How to use the editor", h("div", { class: "helpdoc" },
      h("ol", null,
        h("li", null, h("strong", { text: "Change things on the left. " }), "The preview on the right updates as you type. Click anything in the preview to jump to it."),
        h("li", null, h("strong", { text: "Save " }), "keeps your work on this computer. Nothing changes on the internet yet."),
        h("li", null, h("strong", { text: "Publish to website " }), "puts your saved changes on the real website for everyone."),
        h("li", null, h("strong", { text: "Made a mistake? " }), "Use Undo, or History to bring back any earlier version.")),
      h("h4", { text: "Writing tips" }),
      h("ul", null,
        h("li", null, "Select words and press ", h("b", { text: "B Bold" }), " to make them bold. They look like **this** in the box."),
        h("li", null, "Press 🔗 Link to turn words into a link."),
        h("li", null, "Leave an empty line between paragraphs.")),
      h("h4", { text: "Good to know" }),
      h("ul", null,
        h("li", { text: "The logo and the original customer reviews are locked so they can't be changed by accident." }),
        h("li", { text: "Big phone photos are shrunk automatically so the site stays fast." }),
        h("li", { text: "If you close the browser without saving, your changes are still here next time." }))));
  }

  /* ================================================================ shared with insights.js */
  window.SHI = { h: h, api: api, dialog: dialog, toast: toast, busy: busy, S: S, commit: commit,
    clone: clone, get: get, field: field, toggle: toggle, card: card };

  /* ================================================================ boot */

  $("#undoBtn").addEventListener("click", undo);
  $("#redoBtn").addEventListener("click", redo);
  $("#saveBtn").addEventListener("click", function () { save(); });
  $("#panelSaveBtn").addEventListener("click", function () { save(); });
  $("#publishBtn").addEventListener("click", function () { publishNow(false); });
  $("#historyBtn").addEventListener("click", showHistory);
  $("#helpBtn").addEventListener("click", showHelp);
  $("#logoutBtn").addEventListener("click", function () {
    var go = isDirty() ? confirmBox("Sign out?", "Your unsaved changes stay safe and will be here next time.", "Sign out") : Promise.resolve(true);
    go.then(function (ok) { if (ok) api("/api/logout", {}).finally(function () { window.location.href = "/login"; }); });
  });
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    var typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "");
    if ((e.ctrlKey || e.metaKey) && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
  });
  window.addEventListener("beforeunload", function (e) {
    if (isDirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  api("/api/state").then(function (d) {
    S.saved = d.saved;
    S.savedHash = d.savedHash;
    S.published = d.published || {};
    S.media = d.media || [];
    S.targets = d.publishTargets || [];
    S.cfReady = d.cloudflareReady;
    S.siteUrl = d.siteUrl;
    S.content = clone(d.draft || d.saved);
    if (d.draft && JSON.stringify(d.draft) !== JSON.stringify(d.saved)) {
      var b = $("#banner");
      b.textContent = "";
      b.appendChild(h("span", { text: "You have changes from last time that weren't saved yet. They're loaded below." }));
      b.appendChild(h("button", { type: "button", class: "btn small", onclick: function () { save(); } }, "Save them"));
      b.appendChild(h("button", { type: "button", class: "btn small ghost", onclick: function () {
        confirmBox("Throw away the unsaved changes?", "The editor will go back to your last saved version.", "Throw away", true).then(function (ok) {
          if (!ok) return;
          api("/api/discard-draft", {}).then(function () {
            S.content = clone(S.saved); S.undo = []; S.redo = []; b.hidden = true;
            changed(true);
          });
        });
      } }, "Throw them away"));
      b.hidden = false;
    }
    showIssues(d.issues || {});
    renderForms();
    updateStatus();
  });
})();

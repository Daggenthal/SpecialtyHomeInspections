/* Connect Cloudflare + the Website setup checklist.
   Uses the helpers editor.js shares on window.SHI. Every check runs live, so the list
   ticks itself off as things are done in Cloudflare and GoDaddy. */
(function () {
  "use strict";
  var SHI = window.SHI;
  var h = SHI.h, api = SHI.api, toast = SHI.toast, S = SHI.S;

  function link(href, text) { return h("a", { href: href, target: "_blank", rel: "noopener noreferrer" }, text); }

  /* A dialog of our own, so it never fights with the editor's other pop-ups. */
  function modal(title, wide) {
    var d = h("dialog", { class: "dlg" + (wide ? " wide" : "") });
    var body = h("div", { class: "dlg-body" });
    var foot = h("div", { class: "dlg-foot" });
    var closeBtn = h("button", { class: "icon-x", type: "button", "aria-label": "Close" }, "×");
    d.appendChild(h("div", { class: "dlg-head" }, h("h2", { text: title }), closeBtn));
    d.appendChild(body);
    d.appendChild(foot);
    document.body.appendChild(d);
    var api_ = { d: d, body: body, foot: foot, onClose: null };
    function close(v) { if (d.open) d.close(); d.remove(); if (api_.onClose) api_.onClose(v); }
    closeBtn.addEventListener("click", function () { close(false); });
    d.addEventListener("cancel", function (e) { e.preventDefault(); close(false); });
    api_.close = close;
    d.showModal();
    return api_;
  }

  /* ================================================================ Connect Cloudflare */

  function connectCloudflare(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var info = S.cloudflare || {};
      var m = modal("Connect Cloudflare");
      m.onClose = resolve;

      function field(id, label, input, help) {
        return h("div", { class: "field cf-field" },
          h("label", { for: id, class: "cf-label", text: label }), input,
          h("p", { class: "help cf-help", id: id + "-help" }, help),
          h("p", { class: "cf-err", id: id + "-err", role: "alert" }));
      }
      var token = h("input", { id: "cf-token", type: "password", class: "cf-input", autocomplete: "off", spellcheck: "false",
        "aria-describedby": "cf-token-help cf-token-err",
        placeholder: info.hasToken ? "Saved (ends in " + (info.tokenHint || "…") + "). Leave empty to keep it" : "Paste the token here" });
      var show = h("button", { type: "button", class: "btn small", "aria-pressed": "false", onclick: function () {
        var on = token.type === "password";
        token.type = on ? "text" : "password";
        show.textContent = on ? "Hide" : "Show";
        show.setAttribute("aria-pressed", String(on));
      } }, "Show");
      var account = h("input", { id: "cf-account", type: "text", class: "cf-input", autocomplete: "off", spellcheck: "false",
        maxlength: "32", value: info.accountId || "", placeholder: "32 letters and numbers",
        "aria-describedby": "cf-account-help cf-account-err" });
      var formErr = h("p", { class: "cf-err", role: "alert" });

      m.body.appendChild(h("p", { text: "Publishing puts the website on Cloudflare. It needs two things from the Cloudflare account. You only do this once, and they're kept private on this computer." }));
      m.body.appendChild(field("cf-token", "API token", h("div", { class: "cf-row" }, token, show),
        h("span", null, "In Cloudflare: ", link("https://dash.cloudflare.com/profile/api-tokens", "My Profile → API Tokens"),
          " → Create Token → \"Edit Cloudflare Workers\" → Use template. Under Permissions add Zone → DNS → Edit. Pick the account, and for the zone pick specialtyhomeinspections.biz (or All zones until it's added). Create it and copy it.")));
      m.body.appendChild(field("cf-account", "Account ID", account,
        h("span", null, "On the ", link("https://dash.cloudflare.com/?to=/:account/workers-and-pages", "Workers & Pages"), " page, on the right side.")));
      m.body.appendChild(formErr);

      var submit = h("button", { type: "button", class: "btn primary" }, opts.thenPublish ? "Connect and publish" : "Save");
      m.foot.appendChild(h("button", { type: "button", class: "btn", onclick: function () { m.close(false); } }, "Cancel"));
      m.foot.appendChild(submit);

      function setErr(id, msg) {
        var el = id ? m.d.querySelector("#" + id + "-err") : formErr;
        el.textContent = msg || "";
        var input = id && m.d.querySelector("#" + id);
        if (input) input.setAttribute("aria-invalid", msg ? "true" : "false");
      }
      function go() {
        setErr("cf-token"); setErr("cf-account"); setErr(null);
        submit.disabled = true;
        submit.textContent = "Checking with Cloudflare…";
        api("/api/cloudflare", { token: token.value.trim(), accountId: account.value.trim() }).then(function (d) {
          submit.disabled = false;
          submit.textContent = opts.thenPublish ? "Connect and publish" : "Save";
          if (!d._ok) {
            var f = d.fields || {};
            if (f.token) setErr("cf-token", f.token);
            if (f.accountId) setErr("cf-account", f.accountId);
            if (!f.token && !f.accountId) setErr(null, d.error || "Something went wrong. Please try again.");
            (f.token ? token : f.accountId ? account : submit).focus();
            return;
          }
          S.cloudflare = d;
          S.cfReady = true;
          if (d.targets) S.targets = d.targets;
          token.value = "";
          toast(d.message || "Connected to Cloudflare.", d.verified === false ? "" : "good");
          m.close(true);
        }).catch(function () {
          submit.disabled = false;
          submit.textContent = opts.thenPublish ? "Connect and publish" : "Save";
          setErr(null, "Lost contact with the editor. Is it still running?");
        });
      }
      submit.addEventListener("click", go);
      [token, account].forEach(function (el) { el.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); go(); } }); });
      (info.hasToken ? account : token).focus();
    });
  }

  /* ================================================================ Website setup checklist */

  var lastStatus = null;

  function stateOf(st) {
    var cf = st.cloudflare && st.cloudflare.ready;
    var dom = st.onCloudflare === true;
    var mail = st.emailRouting === true;
    var live = st.site && st.site.live;
    return { cf: cf, dom: dom, mail: mail, live: live, done: cf && dom && mail && live };
  }

  function badge(state, labels) {
    // state: "ok" | "todo" | "wait" | "unknown"
    var cls = { ok: "ok", todo: "warn", wait: "", unknown: "" }[state];
    return h("span", { class: "pill " + cls, text: labels[state] });
  }

  function step(n, title, state, labels, detail, howto, openByDefault) {
    var det = h("details", { class: "setup-how" }, h("summary", { text: state === "ok" ? "How this was done" : "How to do it" }), howto);
    if (openByDefault) det.open = true;
    return h("li", { class: "setup-step " + (state === "ok" ? "is-done" : "") },
      h("div", { class: "setup-top" },
        h("span", { class: "setup-num", "aria-hidden": "true", text: state === "ok" ? "✓" : String(n) }),
        h("h3", { text: title }),
        badge(state, labels)),
      detail ? h("div", { class: "setup-detail small muted" }, detail) : null,
      det);
  }

  function ol() { return h("ol", { class: "setup-list-steps" }, Array.prototype.slice.call(arguments)); }

  function render(m, st) {
    var s = stateOf(st);
    var domain = st.domain || "the domain";
    var gmail = st.gmail || "the Gmail address";
    var firstOpen = !s.cf ? 1 : !s.dom ? 2 : !s.mail ? 3 : !s.live ? 4 : 0;
    m.body.textContent = "";
    m.body.appendChild(h("p", { text: "Four steps put the website on " + domain + " with email forwarding to " + gmail + ". Each one checks itself, so come back any time and the list shows where things are." }));

    var list = h("ol", { class: "setup-list" });

    // 1. Cloudflare
    list.appendChild(step(1, "Connect Cloudflare",
      s.cf ? "ok" : "todo", { ok: "Connected", todo: "Not connected" },
      s.cf ? h("span", null, "Account " + st.cloudflare.accountId + ". ", h("button", { type: "button", class: "btn small", onclick: function () { connectCloudflare().then(function (ok) { if (ok) refresh(m, true); }); } }, "Change")) : null,
      h("div", null,
        ol(h("li", null, "Make a free account at ", link("https://dash.cloudflare.com/sign-up", "dash.cloudflare.com"), " if there isn't one yet."),
           h("li", null, "Press ", h("strong", { text: "Connect" }), " and follow the two boxes.")),
        s.cf ? null : h("button", { type: "button", class: "btn primary", onclick: function () { connectCloudflare().then(function (ok) { if (ok) refresh(m, true); }); } }, "Connect")),
      firstOpen === 1));

    // 2. Domain on Cloudflare
    var ns = st.nameservers || [];
    list.appendChild(step(2, "Move " + domain + " to Cloudflare",
      st.onCloudflare === null || st.onCloudflare === undefined ? "unknown" : s.dom ? "ok" : "todo",
      { ok: "On Cloudflare", todo: "Not yet", unknown: "Couldn't check" },
      ns.length ? "Nameservers now: " + ns.join(", ") : null,
      h("div", null,
        h("p", { text: "The website and the email both live on Cloudflare from now on. The domain registration can stay where it is; only its nameservers change." }),
        ol(h("li", null, "Find where the domain is registered: ", link("https://lookup.icann.org/en/lookup?name=" + encodeURIComponent(domain), "look it up"), " and read the \"Registrar\" line. It was GoDaddy (see README, \"Domain, DNS and email\")."),
           h("li", null, "In Cloudflare: ", link("https://dash.cloudflare.com/?to=/:account/add-site", "Add a domain"), " → type ", h("strong", { text: domain }), " → pick the ", h("strong", { text: "Free" }), " plan → continue. Keep the records it finds, but on the review page switch the orange cloud to grey (\"DNS only\") for the records named ", h("strong", { text: domain }), " and www. That keeps John@ mail arriving until step 3 is done."),
           h("li", null, "Cloudflare shows two nameservers (they end in ns.cloudflare.com). Copy both."),
           h("li", null, "At the registrar (GoDaddy: ", link("https://dcc.godaddy.com/control/portfolio", "My Domains"), " → the domain → DNS → Nameservers → Change → \"I'll use my own nameservers\"), replace the old ones with Cloudflare's two and save."),
           h("li", null, "Wait. It's usually under an hour, at most a day. Cloudflare emails when it's done, and this step turns green.")),
        h("p", { class: "help", text: "While there, turn on auto-renew and the registrar lock so the domain can't lapse or be moved." })),
      firstOpen === 2));

    // 3. Email
    list.appendChild(step(3, "Forward email to Gmail",
      st.emailRouting === null || st.emailRouting === undefined ? "unknown" : s.mail ? "ok" : (s.dom ? "todo" : "wait"),
      { ok: "Forwarding on", todo: "Not set up", wait: "After step 2", unknown: "Couldn't check" },
      st.mx && st.mx.length ? "Mail servers now: " + st.mx.join(", ") : (s.dom ? "No mail servers set yet." : null),
      h("div", null,
        h("p", null, "Every address at " + domain + " (like John@, printed on the cards) will arrive in ", h("strong", { text: gmail }), ". Nothing new to check."),
        ol(h("li", null, "In Cloudflare, open ", h("strong", { text: domain }), " → ", h("strong", { text: "Email" }), " → ", h("strong", { text: "Email Routing" }), " → Get started."),
           h("li", null, "Destination addresses → Add → ", h("strong", { text: gmail }), ". Cloudflare emails a link: open the Gmail and click ", h("strong", { text: "Verify email address" }), "."),
           h("li", null, "Routing rules → ", h("strong", { text: "Catch-all address" }), " → Edit → action \"Send to an email\" → the Gmail → Save, and switch it on. Then John@ and any other old address all forward."),
           h("li", null, "When Cloudflare offers to add the mail records, press ", h("strong", { text: "Add records and enable" }), "."),
           h("li", null, "Test it: from a different email account, send a message to John@" + domain + ". It should land in the Gmail within a minute (check Spam the first time).")),
        h("p", { class: "help", text: "Do this before step 4. Until forwarding is on, publishing leaves the old website on the address, because removing it would also stop John@ mail." })),
      firstOpen === 3));

    // 4. Website live
    var live = st.site || {};
    var liveState = s.live ? "ok" : (s.dom && s.mail ? "todo" : "wait");
    var liveDetail = s.live ? h("span", null, "Live at ", link("https://" + domain, domain), ".")
      : live.reachable && live.ours === false ? "The address still shows the old website." : null;
    list.appendChild(step(4, "Put the website on " + domain,
      liveState, { ok: "Live", todo: "Ready to publish", wait: "After steps 2 and 3" },
      liveDetail,
      h("div", null,
        ol(h("li", null, "Once steps 2 and 3 are green, press ", h("strong", { text: "Publish to website" }), "."),
           h("li", { text: "Publishing takes the address over by itself: it removes the old website's records and connects the new site to " + domain + " and www." + domain + "." }),
           h("li", { text: "The padlock (https) certificate can take up to 15 minutes the first time. After that, this step turns green." })),
        s.dom && s.mail && !s.live ? h("button", { type: "button", class: "btn primary", onclick: function () { m.close(true); document.getElementById("publishBtn").click(); } }, "Publish now") : null),
      firstOpen === 4));

    // 5. Visitor counter (optional)
    var counterOk = st.statsOnPi;
    list.appendChild(step(5, "Visitor counter (optional)",
      counterOk ? "ok" : "todo", { ok: "Counting", todo: "Not counting yet" },
      counterOk ? "Counter: " + st.statsEndpoint : "The counter still points at " + (st.statsEndpoint || "/api/hit") + ", which only works while the site runs on the Pi.",
      h("div", null,
        h("p", { text: "Visitor numbers are counted by the Pi. With the website on Cloudflare, visitors' browsers need a public address for the Pi's counter." }),
        ol(h("li", null, "Follow README, \"Visitor stats\" → \"After moving the site to Cloudflare\" (a tunnel name like stats." + domain + ")."),
           h("li", null, "Then in the editor: Visitor stats → \"Where the counter lives\" → https://stats." + domain + "/api/hit, and publish."))),
      false));

    m.body.appendChild(list);
    var checked = h("p", { class: "help", text: "Checked just now. " });
    checked.appendChild(h("button", { type: "button", class: "btn small", onclick: function () { refresh(m, true); } }, "Check again"));
    m.body.appendChild(checked);
  }

  function refresh(m, force) {
    m.body.setAttribute("aria-busy", "true");
    return api("/api/setup" + (force ? "?refresh=1" : "")).then(function (st) {
      m.body.removeAttribute("aria-busy");
      lastStatus = st;
      if (st.cloudflare) { S.cloudflare = st.cloudflare; S.cfReady = st.cloudflare.ready; }
      if (st.targets) S.targets = st.targets;
      render(m, st);
      paintButton(st);
    });
  }

  function showSetup() {
    var m = modal("Website setup", true);
    m.body.appendChild(h("p", { class: "muted", text: "Checking Cloudflare, the domain and the email…" }));
    m.foot.appendChild(h("button", { type: "button", class: "btn primary", onclick: function () { m.close(true); } }, "Done"));
    refresh(m, false);
  }

  /* header button with a dot until everything is green */
  function paintButton(st) {
    var b = document.getElementById("setupBtn");
    if (!b) return;
    var s = stateOf(st);
    b.classList.toggle("needs", !s.done);
    b.title = s.done ? "Everything is set up" : "Some setup steps are left";
  }
  var btn = document.getElementById("setupBtn");
  if (btn) btn.addEventListener("click", showSetup);
  api("/api/setup").then(function (st) { lastStatus = st; paintButton(st); if (st.cloudflare) S.cloudflare = st.cloudflare; }).catch(function () {});

  SHI.connectCloudflare = connectCloudflare;
  SHI.showSetup = showSetup;
  SHI.setupStatus = function () { return lastStatus; };
})();

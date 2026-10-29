/* Loaded only inside the editor's preview.
   - Clicking something tells the editor which field to open.
   - Call / Text / Email buttons show what they would do instead of dialing anyone. */
(function () {
  "use strict";
  document.documentElement.classList.add("no-anim", "shi-editing");

  function tell(path) {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "shi-focus", path: path }, window.location.origin);
    }
  }

  var pop = null;
  function closePop() { if (pop) { pop.remove(); pop = null; } }

  function showContact(kind, value) {
    closePop();
    var what = {
      tel: { icon: "📞", title: "Call button", verb: "starts a phone call to", field: "business.phone", change: "Change the phone number" },
      sms: { icon: "💬", title: "Text button", verb: "opens a new text message to", field: "business.phone", change: "Change the phone number" },
      mailto: { icon: "✉️", title: "Email button", verb: "opens a new email to", field: "business.email", change: "Change the email address" }
    }[kind];
    pop = document.createElement("div");
    pop.className = "shi-pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", what.title);
    var card = document.createElement("div");
    card.className = "shi-pop-card";
    var h = document.createElement("p"); h.className = "shi-pop-title"; h.textContent = what.icon + " " + what.title + " works";
    var p1 = document.createElement("p"); p1.textContent = "On a visitor's phone or computer, this " + what.verb + ":";
    var v = document.createElement("p"); v.className = "shi-pop-value"; v.textContent = value;
    var p2 = document.createElement("p"); p2.className = "shi-pop-note"; p2.textContent = "This is only the preview, so nothing was sent.";
    var row = document.createElement("div"); row.className = "shi-pop-row";
    var change = document.createElement("button"); change.type = "button"; change.textContent = what.change;
    change.addEventListener("click", function () { closePop(); tell(what.field); });
    var ok = document.createElement("button"); ok.type = "button"; ok.className = "primary"; ok.textContent = "OK";
    ok.addEventListener("click", closePop);
    row.appendChild(change); row.appendChild(ok);
    [h, p1, v, p2, row].forEach(function (n) { card.appendChild(n); });
    pop.appendChild(card);
    pop.addEventListener("click", function (e) { if (e.target === pop) closePop(); });
    document.body.appendChild(pop);
    ok.focus();
  }

  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePop(); });

  document.addEventListener("click", function (e) {
    if (e.target.closest(".shi-pop")) return;
    var link = e.target.closest("a[href]");
    if (link) {
      var href = link.getAttribute("href");
      var m = /^(tel|sms|mailto):(.*)$/i.exec(href);
      if (m) {
        e.preventDefault();
        e.stopPropagation();
        var value = decodeURIComponent(m[2].split("?")[0]);
        if (/^(tel|sms)$/i.test(m[1])) {
          var d = value.replace(/^\+1/, "").replace(/\D/g, "");
          if (d.length === 10) value = d.slice(0, 3) + "-" + d.slice(3, 6) + "-" + d.slice(6);
        }
        showContact(m[1].toLowerCase(), value);
        return;
      }
    }
    // Buttons and fold-outs on the page (show all certifications, FAQ answers, menu) work normally
    if (e.target.closest("button, [data-badge-more], [data-menu], [data-theme-toggle], [data-to-top]")) return;
    var sum = e.target.closest("summary");
    if (sum) {   // opens the answer AND shows where to edit it
      var owner = sum.closest("[data-path]");
      if (owner) tell(owner.getAttribute("data-path"));
      return;
    }
    var el = e.target.closest("[data-path]");
    if (link && !el) return;                 // menu links, "back to top", outside links: work normally
    if (link && link.closest("nav, .callbar")) return;
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    tell(el.getAttribute("data-path"));
  }, true);
})();

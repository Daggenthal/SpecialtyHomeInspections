/* Visitors dashboard and QR code maker for the website editor. */
(function () {
  "use strict";
  var X = window.SHI;
  if (!X) return;
  var h = X.h, $ = function (s) { return document.querySelector(s); };
  var SVGNS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs, kids) {
    var el = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (k) { el.appendChild(k); });
    return el;
  }
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30) || "qr"; }
  function siteUrl() { return (X.S.content.business.siteUrl || "").replace(/\/+$/, ""); }

  var MEDIUM = { search: "Search engine", direct: "Typed in / bookmark", social: "Social media", paid: "Paid ad",
    qr: "QR code", referral: "Another website", maps: "Maps", campaign: "Tagged link", email: "Email", print: "Print",
    business_profile: "Google Business Profile", cpc: "Paid ad", ppc: "Paid ad" };
  function mediumName(m) { return MEDIUM[m] || (m ? m.charAt(0).toUpperCase() + m.slice(1) : "Other"); }

  /* ================================================================ Visitors dashboard */

  function table(title, rows, cols, empty) {
    var total = rows.reduce(function (a, r) { return a + (r.count || 0); }, 0) || 1;
    return h("section", { class: "dash-card" }, h("h3", { text: title }),
      rows.length ? h("table", { class: "dash-table" },
        h("tbody", null, rows.map(function (r) {
          return h("tr", null, cols.map(function (c) { return h("td", { class: c.cls || "" }, c.get(r, total)); }));
        }))) : h("p", { class: "muted small", text: empty || "Nothing yet." }));
  }
  function bar(r, total) {
    var pct = Math.round((r.count / total) * 100);
    var b = h("span", { class: "dash-bar" }, h("span", { class: "dash-bar-fill" }));
    b.firstChild.style.width = Math.max(2, pct) + "%";
    return h("span", { class: "dash-barwrap" }, b, h("span", { class: "dash-num", text: num(r.count) + " · " + pct + "%" }));
  }

  function chart(series) {
    var W = 900, H = 200, pad = 28, n = series.length || 1;
    var max = Math.max(1, Math.max.apply(null, series.map(function (s) { return s.visitors; })));
    var bw = (W - pad * 2) / n;
    var g = svg("svg", { viewBox: "0 0 " + W + " " + (H + 30), class: "dash-chart", role: "img", "aria-label": "Visitors per day" });
    [0, 0.5, 1].forEach(function (t) {
      var y = pad + (H - pad) * (1 - t);
      g.appendChild(svg("line", { x1: pad, x2: W - pad, y1: y, y2: y, stroke: "#e2e7f0" }));
      var lbl = svg("text", { x: 2, y: y + 4, "font-size": 11, fill: "#7a8499" }); lbl.textContent = Math.round(max * t); g.appendChild(lbl);
    });
    series.forEach(function (s, i) {
      var hgt = (H - pad) * (s.visitors / max);
      var x = pad + i * bw + bw * 0.15, y = H - hgt;
      var r = svg("rect", { x: x, y: y, width: Math.max(1, bw * 0.7), height: Math.max(0, hgt), rx: 2, fill: "#1b3a8c" });
      var t = svg("title"); t.textContent = s.day + ": " + s.visitors + " visitors, " + s.views + " views, " + s.contacts + " call/text/email taps";
      r.appendChild(t); g.appendChild(r);
      if (s.contacts) {
        var c = svg("circle", { cx: x + bw * 0.35, cy: Math.max(pad - 8, y - 8), r: 4, fill: "#d3333a" });
        c.appendChild(t.cloneNode(true)); g.appendChild(c);
      }
      if (n <= 31 ? i % Math.ceil(n / 8) === 0 : i % Math.ceil(n / 6) === 0) {
        var d = svg("text", { x: x, y: H + 18, "font-size": 11, fill: "#7a8499" });
        d.textContent = s.day.slice(5).replace("-", "/"); g.appendChild(d);
      }
    });
    return g;
  }

  function openStats() {
    var days = 30;
    var body = h("div", { class: "dash" });
    function load() {
      body.textContent = "";
      body.appendChild(h("p", { class: "muted", text: "Loading…" }));
      Promise.all([X.api("/api/stats?days=" + days), X.api("/api/search-terms?days=" + Math.max(28, days))]).then(function (res) {
        render(res[0], res[1]);
      });
    }
    function render(d, gsc) {
      body.textContent = "";
      var picker = h("div", { class: "seg dash-range", role: "group", "aria-label": "Time period" },
        [[1, "Today"], [7, "7 days"], [30, "30 days"], [90, "90 days"], [365, "1 year"]].map(function (p) {
          return h("button", { type: "button", class: "seg-btn" + (p[0] === days ? " active" : ""), onclick: function () { days = p[0]; load(); } }, p[1]);
        }));
      body.appendChild(h("div", { class: "dash-top" }, picker, h("span", { class: "muted small", text: d.start + " to " + d.end + " · Central Time" })));

      if (d.empty) {
        body.appendChild(h("div", { class: "dash-empty" },
          h("strong", { text: "No visits counted yet for this period." }),
          h("p", { text: "Counting starts once the website is published from this Pi and people visit it. Nothing personal is stored: no cookies, no IP addresses." })));
      } else {
        var a = d.actions || {};
        var kpi = function (label, value, cls) { return h("div", { class: "kpi " + (cls || "") }, h("small", { text: label }), h("b", { text: num(value) })); };
        body.appendChild(h("div", { class: "kpis" },
          kpi("Visitors", d.visitors), kpi("Page views", d.views),
          kpi("Tapped Call", a.call, "hot"), kpi("Tapped Text", a.text, "hot"), kpi("Tapped Email", a.email, "hot"),
          kpi("Opened sample report", a.report)));
        body.appendChild(h("section", { class: "dash-card wide" }, h("h3", null, "Visitors per day ", h("small", { class: "muted", text: "(red dot = someone tapped Call, Text or Email)" })), chart(d.series)));

        var srcCols = [{ get: function (r) { return h("span", null, h("strong", { text: r.name }), " ", h("span", { class: "tag", text: mediumName(r.medium) })); } }, { get: bar, cls: "right" }];
        body.appendChild(h("div", { class: "dash-grid" },
          table("Where visitors came from", d.sources, srcCols),
          table("Kinds of visits", d.mediums.map(function (m) { return { name: mediumName(m.name), count: m.count }; }),
            [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }]),
          table("Who tapped Call / Text / Email came from", d.contactSources, [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }],
            "No taps on Call, Text or Email yet."),
          table("QR codes, ads and tagged links", d.sources.filter(function (s) { return /qr|paid|campaign|print|email/.test(s.medium); }).concat(
            d.campaigns.filter(function (c) { return !/^qr-/.test(c.name); }).map(function (c) { return { name: "Campaign: " + c.name, count: c.count }; })),
            [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }],
            "None yet. Make a QR code (QR codes button) and its scans will show up here."),
          table("Where visitors are", d.places, [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }],
            "Location shows up once the site runs behind Cloudflare."),
          table("Devices", d.devices, [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }])));
        if (d.terms.length) {
          body.appendChild(table("Search words passed along by search engines", d.terms,
            [{ get: function (r) { return r.name; } }, { get: bar, cls: "right" }]));
        }
      }

      // Google Search Console
      var g = h("section", { class: "dash-card wide" }, h("h3", { text: "What people searched on Google" }));
      if (!gsc.connected) {
        g.appendChild(h("p", { class: "muted", text: "Google doesn't tell websites what people searched. To see the searches that showed this website (and how many people clicked), connect Google Search Console. It's free; the setup steps are in the README under “Search phrases”." }));
      } else if (gsc.error) {
        g.appendChild(h("p", { class: "error", text: gsc.error }));
      } else if (!gsc.rows.length) {
        g.appendChild(h("p", { class: "muted", text: "Connected, but Google has no search data for " + gsc.start + " to " + gsc.end + " yet. New sites take a few weeks." }));
      } else {
        g.appendChild(h("p", { class: "muted small", text: gsc.start + " to " + gsc.end + " (Google's numbers run about two days behind) · updated " + gsc.fetched }));
        g.appendChild(h("table", { class: "dash-table gsc" },
          h("thead", null, h("tr", null, ["Search words", "Clicks", "Times shown", "Click rate", "Avg. position"].map(function (t) { return h("th", { text: t }); }))),
          h("tbody", null, gsc.rows.map(function (r) {
            return h("tr", null, h("td", { text: r.query }), h("td", { class: "right", text: num(r.clicks) }),
              h("td", { class: "right", text: num(r.impressions) }), h("td", { class: "right", text: r.ctr + "%" }), h("td", { class: "right", text: r.position }));
          }))));
      }
      body.appendChild(g);
    }
    X.dialog("Visitors", body, [{ label: "Close", value: null }]);
    var dlg = $("#dlg"); dlg.classList.add("xwide");
    dlg.addEventListener("close", function rm() { dlg.classList.remove("xwide"); dlg.removeEventListener("close", rm); });
    load();
  }

  /* ================================================================ QR codes */

  var PLACES = [["truck", "Truck / vehicle"], ["postcard", "Postcards"], ["business-card", "Business cards"],
    ["flyer", "Flyers"], ["yard-sign", "Yard sign"], ["report", "Inspection reports"], ["other", "Somewhere else"]];

  function qrMatrix(text, ecc) {
    var q = window.qrcode(0, ecc || "Q");
    q.addData(text);
    q.make();
    var n = q.getModuleCount(), rows = [];
    for (var r = 0; r < n; r++) { var row = []; for (var c = 0; c < n; c++) row.push(q.isDark(r, c)); rows.push(row); }
    return rows;
  }

  /* Printed width of the whole code (white border included), in inches. */
  var SIZES = [["0.75", "¾ inch (business card)"], ["1", "1 inch"], ["1.5", "1½ inches (postcard)"], ["2", "2 inches (flyer)"],
    ["3", "3 inches"], ["4", "4 inches"], ["6", "6 inches"], ["8", "8 inches (yard sign)"], ["10", "10 inches"],
    ["12", "12 inches (truck door)"], ["18", "18 inches"], ["24", "24 inches (truck tailgate / banner)"], ["custom", "Custom size…"]];
  var DEFAULT_SIZE = { truck: "12", postcard: "1.5", "business-card": "0.75", flyer: "2", "yard-sign": "8", report: "1", other: "2" };
  var PRINT_DPI = 300, MAX_PX = 9600;

  function fmtInches(i) { return (Math.round(i * 100) / 100) + " in"; }
  function fmtFeet(i) { var ft = i / 12; return ft < 1 ? Math.round(i) + " inches" : (Math.round(ft * 10) / 10) + " ft"; }

  function qrSvg(text, opts) {
    var m = qrMatrix(text, opts.ecc), n = m.length, quiet = 4, size = n + quiet * 2;
    var cap = opts.caption ? 6 : 0;
    var d = "";
    for (var r = 0; r < n; r++) for (var c = 0; c < n; c++) if (m[r][c]) d += "M" + (c + quiet) + " " + (r + quiet) + "h1v1h-1z";
    var esc = function (s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
    var wAttr = opts.widthIn ? (+opts.widthIn).toFixed(3) + "in" : String(size * 10);
    var hAttr = opts.widthIn ? (opts.widthIn * (size + cap) / size).toFixed(3) + "in" : String((size + cap) * 10);
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + size + " " + (size + cap) + '" width="' + wAttr + '" height="' + hAttr + '" shape-rendering="crispEdges">' +
      '<rect width="100%" height="100%" fill="#ffffff"/>' +
      '<path d="' + d + '" fill="' + opts.color + '"/>' +
      (cap ? '<text x="' + size / 2 + '" y="' + (size + cap / 2) + '" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-weight="700" font-size="2.6" fill="' + opts.color + '">' + esc(opts.caption) + "</text>" : "") +
      "</svg>";
  }

  function download(name, blob) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  function svgToPng(svgText, px) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var c = document.createElement("canvas");
        var ratio = img.naturalHeight / img.naturalWidth;
        c.width = px; c.height = Math.round(px * ratio);
        var x = c.getContext("2d"); x.imageSmoothingEnabled = false;
        x.drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(resolve, "image/png");
      };
      img.onerror = reject;
      img.src = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
    });
  }

  function openQr() {
    var b = X.S.content.business;
    var st = { place: "truck", other: "", target: "site", caption: "Scan for our website", color: "#000000", track: true,
      size: DEFAULT_SIZE.truck, custom: "12", unit: "in" };
    var sizeInfo = h("p", { class: "qr-size-info" });
    var preview = h("img", { class: "qr-img", alt: "QR code preview" });
    var linkOut = h("code", { class: "qr-link" });
    var warn = h("p", { class: "help" });
    var lastSvg = "", lastUrl = "";

    function target() {
      var name = st.place === "other" ? slug(st.other || "other") : st.place;
      if (st.target === "call") return "tel:" + (b.phone || "").replace(/[^\d+]/g, "");
      if (st.target === "contact") {
        return ["BEGIN:VCARD", "VERSION:3.0", "N:" + (b.owner || "").split(" ").reverse().join(";"), "FN:" + (b.owner || ""),
          "ORG:" + b.name, "TITLE:" + (b.credential || ""), "TEL;TYPE=CELL:" + b.phone, "EMAIL:" + b.email,
          "URL:" + siteUrl() + "/", "END:VCARD"].join("\n");
      }
      var u = siteUrl() + "/";
      return st.track ? u + "?utm_source=" + encodeURIComponent(name) + "&utm_medium=qr&utm_campaign=qr-" + encodeURIComponent(name) : u;
    }
    function widthIn() {
      if (st.size !== "custom") return +st.size;
      var v = parseFloat(st.custom);
      if (!(v > 0)) return null;
      return st.unit === "cm" ? v / 2.54 : v;
    }
    function pngPixels(w) { return Math.min(MAX_PX, Math.round(w * PRINT_DPI)); }
    function redraw() {
      lastUrl = target();
      var w = widthIn();
      customWrap.hidden = st.size !== "custom";
      try {
        lastSvg = qrSvg(lastUrl, { color: st.color, caption: st.caption.trim(), ecc: st.target === "contact" ? "M" : "Q", widthIn: w || 2 });
      } catch (e) { warn.textContent = "That's too much to fit in one QR code."; return; }
      if (!w) {
        sizeInfo.textContent = "Type a size above.";
      } else {
        var px = pngPixels(w), dpi = Math.round(px / w);
        var vb = /viewBox="0 0 (\d+) (\d+)"/.exec(lastSvg), tall = vb ? +vb[2] / +vb[1] : 1;
        var tooSmall = w < 0.6;
        sizeInfo.textContent = "Prints " + fmtInches(w) + " wide (" + (Math.round(w * 2.54 * 10) / 10) + " cm). " +
          (tall > 1 ? "With the words, it's " + fmtInches(w * tall) + " tall. " : "") +
          "Readable from about " + fmtFeet(w * 0.8 * 10) + " away. PNG: " + px + " × " + Math.round(px * tall) + " pixels at " + dpi + " dpi." +
          (tooSmall ? " ⚠ Smaller than about ⅝ inch may not scan reliably." : "") +
          (w > 7.5 ? " Bigger than a sheet of paper: send the SVG to a print or sign shop." : "");
        sizeInfo.classList.toggle("warn", tooSmall);
      }
      if (preview.src) URL.revokeObjectURL(preview.src);
      preview.src = URL.createObjectURL(new Blob([lastSvg], { type: "image/svg+xml" }));
      linkOut.textContent = st.target === "contact" ? "Saves John's contact card (name, phone, email, website)" : lastUrl;
      warn.textContent = st.target === "site" && st.track
        ? "Scans of this code show up in Visitors as “QR code: " + (st.place === "other" ? slug(st.other || "other") : st.place) + "”."
        : st.target === "site" ? "Scans won't be counted separately (tracking is off)."
        : "Scans of call or contact codes can't be counted (they don't open the website).";
    }
    function sel(label, key, choices) {
      var s = h("select", { id: "qr-" + key });
      choices.forEach(function (c) { s.appendChild(h("option", { value: c[0] }, c[1])); });
      s.value = st[key];
      s.addEventListener("change", function () {
        st[key] = s.value;
        if (key === "place" && DEFAULT_SIZE[s.value]) { st.size = DEFAULT_SIZE[s.value]; var ss = document.getElementById("qr-size"); if (ss) ss.value = st.size; }
        otherWrap.hidden = st.place !== "other"; trackWrap.hidden = st.target !== "site"; redraw();
      });
      return h("div", { class: "field" }, h("label", { for: "qr-" + key }, label), s);
    }
    function inp(label, key, ph) {
      var i = h("input", { id: "qr-" + key, type: "text", placeholder: ph || "" });
      i.value = st[key];
      i.addEventListener("input", function () { st[key] = i.value; redraw(); });
      return h("div", { class: "field" }, h("label", { for: "qr-" + key }, label), i);
    }
    var customNum = h("input", { id: "qr-custom", type: "number", min: "0.25", max: "120", step: "0.05", inputmode: "decimal" });
    customNum.value = st.custom;
    customNum.addEventListener("input", function () { st.custom = customNum.value; redraw(); });
    var unitSel = h("select", { id: "qr-unit", "aria-label": "Unit" }, h("option", { value: "in" }, "inches"), h("option", { value: "cm" }, "cm"));
    unitSel.addEventListener("change", function () { st.unit = unitSel.value; redraw(); });
    var customWrap = h("div", { class: "field" }, h("label", { for: "qr-custom" }, "Custom width"),
      h("div", { class: "qr-custom-row" }, customNum, unitSel));
    customWrap.hidden = true;
    var otherWrap = inp("Name for this spot (used in the stats)", "other", "e.g. home show booth");
    otherWrap.hidden = true;
    var trackCb = h("input", { type: "checkbox", id: "qr-track" }); trackCb.checked = true;
    trackCb.addEventListener("change", function () { st.track = trackCb.checked; redraw(); });
    var trackWrap = h("label", { class: "switch", for: "qr-track" }, trackCb, h("span", { class: "slider", "aria-hidden": "true" }), h("span", { text: "Count scans from this code in Visitors" }));

    var form = h("div", { class: "qr-form" },
      sel("Where will this code go?", "place", PLACES), otherWrap,
      sel("What happens when someone scans it?", "target", [["site", "Open the website"], ["call", "Call " + b.phone], ["contact", "Save John's contact card"]]),
      trackWrap,
      inp("Words under the code (optional)", "caption", "Leave empty for no words"),
      sel("Printed size (width)", "size", SIZES), customWrap, sizeInfo,
      sel("Color", "color", [["#000000", "Black (scans best)"], ["#1b3a8c", "Logo blue"]]),
      h("p", { class: "help", text: "Size tip: a code can be read from about 8 to 10 times its width. On a truck door, 10 to 12 inches wide reads from 8 to 10 feet. On a postcard, 1 inch or more. The SVG file prints at exactly this size." }));

    var actions = h("div", { class: "row-btns" },
      h("button", { type: "button", class: "btn primary", onclick: function () {
        download("qr-" + (st.place === "other" ? slug(st.other) : st.place) + ".svg", new Blob([lastSvg], { type: "image/svg+xml" }));
      } }, "⬇ Download SVG (best for printers)"),
      h("button", { type: "button", class: "btn", onclick: function () {
        if (!widthIn()) return X.toast("Type a size first.", "bad");
        svgToPng(lastSvg, pngPixels(widthIn())).then(function (blob) { download("qr-" + (st.place === "other" ? slug(st.other) : st.place) + ".png", blob); });
      } }, "⬇ Download PNG"),
      h("button", { type: "button", class: "btn", onclick: function () {
        var w = widthIn();
        if (!w) return X.toast("Type a size first.", "bad");
        if (w > 7.5) return X.toast("That's bigger than a sheet of paper. Download the SVG and take it to a print or sign shop.", "bad");
        var area = $("#printArea"); area.textContent = "";
        var img = h("img", { src: preview.src, alt: "" });
        img.style.width = w + "in";
        area.appendChild(img);
        window.print();
      } }, "🖨 Print"),
      h("button", { type: "button", class: "btn ghost", title: "Keep a record of this code so you know what each one was for", onclick: function () {
        var list = X.clone(X.S.content.qrCodes || []);
        var name = st.place === "other" ? (st.other || "Other") : PLACES.filter(function (p) { return p[0] === st.place; })[0][1];
        list.push({ name: name, target: st.target, link: st.target === "contact" ? "contact card" : lastUrl,
          size: widthIn() ? fmtInches(widthIn()) : "", made: new Date().toISOString().slice(0, 10) });
        X.commit(["qrCodes"], list, { structural: true });
        X.toast("Saved to your list of QR codes. Remember to Save.", "good");
        drawSaved();
      } }, "Remember this code"));

    var saved = h("div", { class: "qr-saved" });
    function drawSaved() {
      saved.textContent = "";
      var list = X.S.content.qrCodes || [];
      if (!list.length) return;
      saved.appendChild(h("h4", { text: "Codes you've made" }));
      saved.appendChild(h("ul", null, list.map(function (q, i) {
        return h("li", null, h("strong", { text: q.name }), " · " + q.made + (q.size ? " · " + q.size + " wide" : "") + " · ", h("code", { text: q.link }), " ",
          h("button", { type: "button", class: "link-btn", onclick: function () {
            var l = X.clone(X.S.content.qrCodes); l.splice(i, 1); X.commit(["qrCodes"], l, { structural: true }); drawSaved();
          } }, "remove"));
      })));
    }
    drawSaved();

    var body = h("div", { class: "qr-wrap" },
      h("div", null, form),
      h("div", { class: "qr-out" }, h("div", { class: "qr-frame" }, preview), linkOut, warn, actions),
      saved);
    X.dialog("QR codes", body, [{ label: "Close", value: null }]);
    var dlg = $("#dlg"); dlg.classList.add("wide");
    dlg.addEventListener("close", function rm() { dlg.classList.remove("wide"); dlg.removeEventListener("close", rm); });
    redraw();
  }

  window.SHI_openStats = openStats;
  window.SHI_qrSvg = qrSvg; // used by tests
  $("#statsBtn").addEventListener("click", openStats);
  $("#qrBtn").addEventListener("click", openQr);
})();

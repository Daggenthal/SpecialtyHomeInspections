/* Specialty Home Inspections LLC - site behaviour. No libraries, no tracking. */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.remove("no-js");
  root.classList.add("js");

  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* ---------- device detection: touch phones/tablets vs mouse ---------- */
  var coarse = window.matchMedia("(pointer: coarse)");
  var narrow = window.matchMedia("(max-width: 760px)");
  function device() {
    root.classList.toggle("is-touch", coarse.matches || "ontouchstart" in window);
    root.classList.toggle("is-mobile", narrow.matches || root.classList.contains("layout-mobile"));
  }
  device();
  if (narrow.addEventListener) { narrow.addEventListener("change", device); coarse.addEventListener("change", device); }

  /* ---------- theme ---------- */
  var darkMq = window.matchMedia("(prefers-color-scheme: dark)");
  function resolvedTheme() {
    var chosen = store.get("shi-theme");
    if (chosen === "light" || chosen === "dark") return chosen;
    var def = root.getAttribute("data-theme-default");
    if (def === "light" || def === "dark") return def;
    return darkMq.matches ? "dark" : "light";
  }
  function applyTheme() { root.setAttribute("data-theme", resolvedTheme()); }
  applyTheme();
  if (darkMq.addEventListener) darkMq.addEventListener("change", applyTheme);
  var themeBtn = document.querySelector("[data-theme-toggle]");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    store.set("shi-theme", resolvedTheme() === "dark" ? "light" : "dark");
    applyTheme();
  });

  /* ---------- mobile menu ---------- */
  var menuBtn = document.querySelector("[data-menu]");
  var nav = document.getElementById("site-nav");
  function setMenu(open) {
    if (!menuBtn || !nav) return;
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    menuBtn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    nav.classList.toggle("open", open);
  }
  if (menuBtn) menuBtn.addEventListener("click", function () { setMenu(menuBtn.getAttribute("aria-expanded") !== "true"); });
  if (nav) nav.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { setMenu(false); closeLightbox(); } });
  document.addEventListener("click", function (e) {
    if (nav && nav.classList.contains("open") && !e.target.closest("#site-nav") && !e.target.closest("[data-menu]")) setMenu(false);
  });

  /* ---------- header state, brand logo, back to top ---------- */
  var header = document.querySelector("[data-header]");
  var toTop = document.querySelector("[data-to-top]");
  var heroLogo = document.querySelector("[data-hero-logo]");
  var ticking = false;
  function onScroll() {
    var y = window.scrollY || window.pageYOffset;
    if (header) header.classList.toggle("scrolled", y > 8);
    if (toTop) toTop.classList.toggle("show", y > Math.max(500, window.innerHeight * 0.8));
    ticking = false;
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; window.requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();
  if (toTop) toTop.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
    var first = document.querySelector(".brand, a, button");
    if (first) first.focus({ preventScroll: true });
  });

  if (header) {
    if (heroLogo && "IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        header.classList.toggle("show-brand", !es[0].isIntersecting);
      }, { rootMargin: "-70px 0px 0px 0px" }).observe(heroLogo);
    } else {
      header.classList.add("show-brand");
    }
  }

  /* ---------- scroll spy ---------- */
  var navLinks = Array.prototype.slice.call(document.querySelectorAll("[data-nav]"));
  if (navLinks.length && "IntersectionObserver" in window) {
    var current = null;
    var spy = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) {
          current = e.target.id;
          navLinks.forEach(function (a) { a.classList.toggle("active", a.getAttribute("data-nav") === current); });
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    navLinks.forEach(function (a) { var s = document.getElementById(a.getAttribute("data-nav")); if (s) spy.observe(s); });
  }

  /* ---------- reveal on scroll ---------- */
  var reveals = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if ("IntersectionObserver" in window && !reduceMotion.matches && !root.classList.contains("no-anim")) {
    var seen = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); seen.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    reveals.forEach(function (el) {
      var sibs = el.parentElement ? Array.prototype.indexOf.call(el.parentElement.children, el) : 0;
      el.style.setProperty("--d", Math.min(sibs, 6) * 0.06 + "s");
      seen.observe(el);
    });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------- certifications: show 12, then "show all" ---------- */
  var grid = document.querySelector("[data-badge-grid]");
  var more = document.querySelector("[data-badge-more]");
  if (grid && more) {
    var showText = more.textContent;
    var hideText = "Show fewer certifications";
    grid.classList.add("collapsed");
    more.hidden = false;
    more.setAttribute("aria-expanded", "false");
    more.addEventListener("click", function () {
      var opening = grid.classList.contains("collapsed");
      grid.classList.toggle("collapsed", !opening);
      more.textContent = opening ? hideText : showText;
      more.setAttribute("aria-expanded", opening ? "true" : "false");
      if (!opening) {
        // Bring the section back into view so the button doesn't leave you far down the page
        var sec = grid.closest("section") || grid;
        if (sec.getBoundingClientRect().top < 0) sec.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth", block: "start" });
      }
    });
  }

  /* ---------- photo lightbox ---------- */
  var lb = document.querySelector("[data-lightbox-root]");
  var lastFocus = null;
  function closeLightbox() {
    if (!lb || lb.hidden) return;
    lb.hidden = true;
    document.body.style.overflow = "";
    if (lastFocus) lastFocus.focus();
  }
  if (lb) {
    document.addEventListener("click", function (e) {
      var a = e.target.closest("[data-lightbox]");
      if (!a) return;
      e.preventDefault();
      lastFocus = a;
      lb.querySelector("img").src = a.getAttribute("href");
      lb.querySelector("img").alt = a.getAttribute("data-caption") || "";
      lb.querySelector("figcaption").textContent = a.getAttribute("data-caption") || "";
      lb.hidden = false;
      document.body.style.overflow = "hidden";
      lb.querySelector(".lb-close").focus();
    });
    lb.addEventListener("click", function (e) { if (!e.target.closest("img")) closeLightbox(); });
  }

  /* ---------- years in business: counts up by itself every anniversary ---------- */
  (function () {
    var els = document.querySelectorAll("[data-years-since]");
    if (!els.length) return;
    var today;
    try {
      today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    } catch (e) { return; }
    var t = today.split("-").map(Number);
    Array.prototype.forEach.call(els, function (el) {
      var f = (el.getAttribute("data-years-since") || "").split("-").map(Number);
      if (f.length !== 3 || !f[0]) return;
      var n = t[0] - f[0] - ((t[1] < f[1] || (t[1] === f[1] && t[2] < f[2])) ? 1 : 0);
      if (n >= 0) el.textContent = String(n);
    });
  })();

  /* ---------- business hours: visitor's clock, our clock, open now / opens in ---------- */
  var hoursEls = Array.prototype.slice.call(document.querySelectorAll("[data-hours]"));
  if (hoursEls.length && window.Intl) {
    var cfg = hoursEls[0].dataset;
    var bizTz = cfg.tz || "America/Chicago";
    var visTz;
    try { visTz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { visTz = bizTz; }
    // "05:00-23:30,,05:00-23:30,…" for Sunday..Saturday; empty = closed that day
    var sched = (cfg.sched || "").split(",").map(function (d) {
      var m = /^(\d\d):(\d\d)-(\d\d):(\d\d)$/.exec(d);
      return m ? { from: +m[1] * 60 + +m[2], to: +m[3] * 60 + +m[4] } : null;
    });
    var DAYNUM = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

    function partsIn(tz, date) {
      var out = {};
      new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" })
        .formatToParts(date).forEach(function (p) { out[p.type] = p.value; });
      return { day: DAYNUM[out.weekday], min: (+out.hour % 24) * 60 + +out.minute, sec: +out.second };
    }
    function fmt(tz, date, withDay) {
      var o = { timeZone: tz, hour: "numeric", minute: "2-digit" };
      if (withDay) o.weekday = "long";
      return new Intl.DateTimeFormat("en-US", o).format(date).replace(",", " ·");
    }
    function zoneAbbr(tz, date) {
      try {
        var p = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(date);
        return (p.filter(function (x) { return x.type === "timeZoneName"; })[0] || {}).value || "";
      } catch (e) { return ""; }
    }
    function span(mins) {
      var d = Math.floor(mins / 1440), hr = Math.floor((mins % 1440) / 60), m = mins % 60;
      var out = [];
      if (d) out.push(d + (d === 1 ? " day" : " days"));
      if (hr) out.push(hr + " hr");
      if (m || !out.length) out.push(m + " min");
      return out.join(" ");
    }
    // Is the business open at local minute `min` on day `day`? Handles hours that run past midnight.
    function openAt(day, min) {
      var t = sched[day], y = sched[(day + 6) % 7];
      if (t && (t.to > t.from ? (min >= t.from && min < t.to) : min >= t.from)) return t;
      if (y && y.to <= y.from && min < y.to) return y;
      return null;
    }
    function nextChange(now, opening) {
      // walk forward minute-blocks of up to 8 days to find when the state flips
      for (var step = 1; step <= 8 * 1440; step++) {
        var d = (now.day + Math.floor((now.min + step) / 1440)) % 7;
        var m = (now.min + step) % 1440;
        if (!!openAt(d, m) !== opening) return step;
      }
      return null;
    }

    // Turn "N wall-clock minutes from now" into a real moment, correcting for daylight-saving jumps.
    function wallClockToDate(date, now, step) {
      var target = (now.min + step) % 1440;
      var guess = new Date(date.getTime() + (step * 60 - now.sec) * 1000);
      for (var i = 0; i < 2; i++) {
        var diff = target - partsIn(bizTz, guess).min;
        if (diff > 720) diff -= 1440;
        if (diff < -720) diff += 1440;
        if (!diff) break;
        guess = new Date(guess.getTime() + diff * 60000);
      }
      return guess;
    }

    function tick() {
      var date = new Date();
      var now = partsIn(bizTz, date);
      var isOpen = !!openAt(now.day, now.min);
      var change = nextChange(now, isOpen);
      var changeAt = change === null ? null : wallClockToDate(date, now, change);
      if (changeAt) change = Math.max(1, Math.round((changeAt.getTime() - date.getTime()) / 60000));
      var same = visTz === bizTz;
      var bizZone = cfg.zone || "Central Time";
      var status, next;
      if (isOpen) {
        status = cfg.openText || "Open now";
        next = changeAt ? "Taking calls until " + fmt(bizTz, changeAt) + " " + bizZone + (same ? "" : " (" + fmt(visTz, changeAt) + " your time)") : "Taking calls";
      } else {
        status = (cfg.closedText || "Closed right now");
        next = changeAt ? "Opens in " + span(change) + ", at " + fmt(bizTz, changeAt, true) + " " + bizZone + (same ? "" : " (" + fmt(visTz, changeAt) + " your time)") : "";
      }
      hoursEls.forEach(function (el) {
        el.classList.toggle("is-open", isOpen);
        el.classList.toggle("is-closed", !isOpen);
        var st = el.querySelector("[data-hours-status]");
        if (st) st.textContent = el.classList.contains("hours-pill") && !isOpen && change !== null ? status + " · Opens in " + span(change) : status;
        var nx = el.querySelector("[data-hours-next]");
        if (nx) nx.textContent = next;
        var clocks = el.querySelector(".clocks");
        if (clocks) clocks.classList.toggle("same", same);
        [["visitor", visTz], ["business", bizTz]].forEach(function (c) {
          var box = el.querySelector('[data-clock="' + c[0] + '"]');
          if (!box) return;
          box.querySelector("b").textContent = fmt(c[1], date);
          box.querySelector("span").textContent = new Intl.DateTimeFormat("en-US", { timeZone: c[1], weekday: "long" }).format(date) + " · " + zoneAbbr(c[1], date);
        });
        if (same) {
          var vs = el.querySelector('[data-clock="visitor"] small');
          if (vs) vs.textContent = "Your time (same as ours)";
        }
        el.querySelectorAll(".hours-week li").forEach(function (li) { li.classList.toggle("today", +li.dataset.day === now.day); });
      });
    }
    tick();
    setInterval(tick, 15000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
  }

  /* ---------- anonymous visit counter (no cookies, nothing personal; see sitekit/stats.py) ---------- */
  (function () {
    var ep = root.getAttribute("data-stats");
    if (!ep || !navigator.sendBeacon) return;
    if (root.hasAttribute("data-stats-dnt") && (navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl === true)) return;
    var keep = /^(utm_(source|medium|campaign|term|content)|gclid|gbraid|wbraid|msclkid|fbclid)$/i;
    var params = {}, url;
    try { url = new URL(window.location.href); } catch (e) { return; }
    url.searchParams.forEach(function (v, k) { if (keep.test(k)) params[k] = v.slice(0, 120); });
    function send(kind) {
      try {
        var body = JSON.stringify({ k: kind, r: document.referrer || "", q: params });
        navigator.sendBeacon(ep, new Blob([body], { type: "text/plain" }));
      } catch (e) { /* counting must never break the page */ }
    }
    send("view");
    // Clean the address bar so shared links don't carry tracking tags
    if (Object.keys(params).length && window.history.replaceState) {
      Object.keys(params).forEach(function (k) { url.searchParams.delete(k); });
      window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
    }
    document.addEventListener("click", function (e) {
      var a = e.target.closest("a[href]");
      if (!a) return;
      var h = a.getAttribute("href");
      if (/^tel:/i.test(h)) send("call");
      else if (/^sms:/i.test(h)) send("text");
      else if (/^mailto:/i.test(h)) send("email");
      else if (/spectora\.com/i.test(h)) send("report");
      else if (/facebook\.com|twitter\.com|x\.com|linkedin\.com|instagram\.com/i.test(h)) send("social");
      else if (/google\.[a-z.]+\/maps|maps\.apple|maps\.google/i.test(h)) send("map");
    }, true);
  })();

  /* ---------- pull down at the top of the page to refresh (touch screens) ---------- */
  var ptr = document.querySelector(".ptr");
  if (ptr && ("ontouchstart" in window)) {
    var startY = 0, startX = 0, pulling = false, dist = 0, THRESHOLD = 80, MAX = 130;
    var icon = ptr.querySelector(".ptr-icon");
    function render() {
      var t = Math.min(dist, MAX);
      ptr.style.transform = "translateY(" + (t - 50) + "px)";
      ptr.style.opacity = Math.min(1, t / 50);
      icon.style.transform = "rotate(" + t * 2.6 + "deg)";
      ptr.classList.toggle("ready", dist >= THRESHOLD);
    }
    function reset() {
      ptr.style.transition = "transform .25s ease, opacity .25s ease";
      ptr.style.transform = "translateY(-60px)";
      ptr.style.opacity = "0";
      setTimeout(function () { ptr.style.transition = ""; }, 260);
    }
    window.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1 || (window.scrollY || window.pageYOffset) > 0) { pulling = false; return; }
      if ((nav && nav.classList.contains("open")) || (lb && !lb.hidden)) { pulling = false; return; }
      startY = e.touches[0].clientY; startX = e.touches[0].clientX; pulling = true; dist = 0;
    }, { passive: true });
    window.addEventListener("touchmove", function (e) {
      if (!pulling) return;
      var dy = e.touches[0].clientY - startY, dx = Math.abs(e.touches[0].clientX - startX);
      if (dy <= 0 || dx > dy || (window.scrollY || window.pageYOffset) > 0) { if (dist) { dist = 0; render(); } return; }
      dist = dy * 0.55; // resistance so it feels springy
      render();
    }, { passive: true });
    window.addEventListener("touchend", function () {
      if (!pulling) return;
      pulling = false;
      if (dist >= THRESHOLD) {
        ptr.classList.add("loading");
        ptr.style.transform = "translateY(" + (THRESHOLD - 46) + "px)";
        setTimeout(function () { window.location.reload(); }, 350);
      } else {
        reset();
      }
      dist = 0;
    }, { passive: true });
  }
})();

(function () {
  "use strict";
  var form = document.getElementById("login");
  var msg = document.getElementById("msg");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    msg.textContent = "";
    var btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Signing in…";
    fetch("/api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-SHI": "1" },
      body: JSON.stringify({ password: document.getElementById("pw").value })
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, d: d }; });
    }).then(function (res) {
      if (res.ok) { window.location.href = "/"; return; }
      msg.textContent = res.d.error || "Couldn't sign in.";
    }).catch(function () {
      msg.textContent = "Couldn't reach the editor. Is it still running?";
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = "Sign in";
    });
  });
})();

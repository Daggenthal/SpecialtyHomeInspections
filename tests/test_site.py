"""Run with:  python3 -m unittest discover -s tests -v"""
import hashlib
import html.parser
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sitekit import render  # noqa: E402
from sitekit.build import build, redirects_text  # noqa: E402
from sitekit.imagesize import sniff_type  # noqa: E402
from sitekit.validate import validate  # noqa: E402

spec = importlib.util.spec_from_file_location("editor_server", ROOT / "editor" / "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

CONTENT = json.loads((ROOT / "content" / "site.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ROOT / "tools" / "original_manifest.json").read_text(encoding="utf-8"))
H = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()


def reviews(content):
    return [s for s in content["sections"] if s["type"] == "reviews"][0]["items"]


class ReviewText(html.parser.HTMLParser):
    """Collect the text of review quotes and names exactly as a browser would show them."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.quotes, self.names, self._grab = [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-verbatim" in a:
            self._grab = "q"; self.quotes.append("")
        elif "data-verbatim-name" in a:
            self._grab = "n"; self.names.append("")

    def handle_endtag(self, tag):
        if tag in ("blockquote", "figcaption"):
            self._grab = None

    def handle_data(self, data):
        if self._grab == "q":
            self.quotes[-1] += data
        elif self._grab == "n":
            self.names[-1] += data


class TestTestimonialsVerbatim(unittest.TestCase):
    def test_content_matches_original_fingerprints(self):
        items = reviews(CONTENT)
        originals = MANIFEST["testimonials"]
        self.assertEqual(len(items), len(originals))
        for item, orig in zip(items, originals):
            self.assertEqual(H(item["quote"]), orig["quote_sha256"], item["name"])
            self.assertEqual(H(item["name"]), orig["name_sha256"], item["name"])
            self.assertTrue(item["locked"])

    def test_rendered_page_shows_them_unchanged(self):
        page, _ = render.render_page(CONTENT)
        p = ReviewText()
        p.feed(page)
        self.assertEqual(len(p.quotes), 4)
        for q, n, orig in zip(p.quotes, p.names, MANIFEST["testimonials"]):
            self.assertTrue(q.startswith('"') and q.endswith('"'))
            self.assertEqual(H(q[1:-1]), orig["quote_sha256"])
            self.assertEqual(H(n), orig["name_sha256"])

    def test_tampering_with_a_locked_review_blocks_saving(self):
        c = json.loads(json.dumps(CONTENT))
        reviews(c)[2]["quote"] = reviews(c)[2]["quote"].replace("preformed", "performed")
        errors, _ = validate(c, check_media=False)
        self.assertTrue(any("locked" in e for e in errors))


class TestDiscounts(unittest.TestCase):
    def test_no_unapproved_discount_amounts(self):
        errors, warnings = validate(CONTENT, check_media=False)
        self.assertEqual(errors, [])
        self.assertFalse([w for w in warnings if "discount" in w.lower()])

    def test_faq7_is_the_original_wording_and_approved(self):
        faq = [s for s in CONTENT["sections"] if s["id"] == "faq"][0]["items"][6]
        self.assertEqual(faq["a"], "We offer a $25 discount to all currently active duty military personnel "
                                   "on all home inspections.")
        self.assertIs(faq["allowAmount"], True)

    def test_trust_badge_has_no_amount(self):
        trust = [s for s in CONTENT["sections"] if s["type"] == "trust"][0]
        for it in trust["items"]:
            self.assertNotRegex(it["label"] + it.get("note", ""), r"\$\s?\d|\d\s?%")

    def test_trust_badges_present(self):
        labels = [i["label"] for s in CONTENT["sections"] if s["type"] == "trust" for i in s["items"]]
        self.assertIn("Veteran Owned Business", labels)
        self.assertIn("BBB Rating: A+", labels)
        self.assertIn("Police, Firefighter, Military Discounts", labels)

    def test_adding_an_amount_warns(self):
        c = json.loads(json.dumps(CONTENT))
        c["sections"][1]["items"][2]["note"] = "Save 15% with our discount"
        _, warnings = validate(c, check_media=False)
        self.assertTrue(any("discount" in w for w in warnings))


class TestLogo(unittest.TestCase):
    def test_logo_fingerprint_matches_manifest(self):
        rec = [f for f in MANIFEST["files"] if f["dest"] == "logo.jpg"][0]
        self.assertEqual(CONTENT["business"]["logo"]["sha256"], rec["sha256"])
        p = ROOT / "content" / "media" / "logo.jpg"
        if not p.is_file():
            self.skipTest("logo not imported yet (run tools/import_old_site.py)")
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), rec["sha256"])


class TestSafety(unittest.TestCase):
    def test_text_is_escaped(self):
        out = render.inline('<script>alert(1)</script> **bold** [x](javascript:alert(1))')
        self.assertNotIn("<script>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertNotIn("javascript:", out)

    def test_review_text_never_formatted(self):
        c = json.loads(json.dumps(CONTENT))
        reviews(c).append({"quote": "**not bold** <b>x</b>", "name": "Test", "locked": False})
        page, _ = render.render_page(c)
        self.assertIn("**not bold** &lt;b&gt;x&lt;/b&gt;", page)

    def test_no_inline_style_or_script_in_public_page(self):
        page, _ = render.render_page(CONTENT)
        self.assertNotIn(" style=", page)
        self.assertNotRegex(page, r"<script>(?!\s*$)")

    def test_sniff_rejects_html(self):
        self.assertIsNone(sniff_type(b"<html><script>"))
        self.assertEqual(sniff_type(b"\x89PNG\r\n\x1a\n...."), "png")
        self.assertEqual(sniff_type(b"%PDF-1.7 ..."), "pdf")


class TestEditorSecurity(unittest.TestCase):
    def test_only_home_network_clients(self):
        for ip in ("127.0.0.1", "::1", "192.168.1.20", "10.0.0.5", "172.16.3.4", "fe80::1", "::ffff:192.168.1.9"):
            self.assertTrue(srv.client_allowed(ip), ip)
        for ip in ("8.8.8.8", "1.1.1.1", "104.16.0.1", "2606:4700::1", "not-an-ip"):
            self.assertFalse(srv.client_allowed(ip), ip)
        self.assertTrue(srv.client_allowed("100.101.102.103", ["100.64.0.0/10"]))

    def test_proxy_and_cloudflare_headers_refused(self):
        self.assertTrue(srv.proxy_headers_present({"CF-Connecting-IP": "1.2.3.4"}))
        self.assertTrue(srv.proxy_headers_present({"X-Forwarded-For": "1.2.3.4"}))
        self.assertFalse(srv.proxy_headers_present({"Host": "pi.local:8787"}))

    def test_hostnames(self):
        for h in ("localhost:8787", "127.0.0.1:8787", "192.168.1.5:8787", "raspberrypi.local:8787", "[::1]:8787"):
            self.assertTrue(srv.host_allowed(h), h)
        for h in ("specialtyhomeinspections.biz", "evil.example:8787", ""):
            self.assertFalse(srv.host_allowed(h), h)

    def test_password_hashing(self):
        stored = srv.hash_password("correct horse battery")
        self.assertTrue(srv.verify_password("correct horse battery", stored))
        self.assertFalse(srv.verify_password("wrong", stored))
        self.assertNotIn("correct", stored)


class TestSocialAndReports(unittest.TestCase):
    def test_twitter_linkedin_kept_but_hidden(self):
        names = {x["name"]: x for x in CONTENT["social"]}
        self.assertTrue(names["Facebook"]["show"])
        self.assertFalse(names["Twitter"]["show"])
        self.assertFalse(names["LinkedIn"]["show"])
        page, _ = render.render_page(CONTENT)
        self.assertIn("facebook.com/SpecialtyHomeInspections", page)
        self.assertNotIn('href="https://twitter.com"', page)
        self.assertNotIn('href="https://www.linkedin.com"', page)

    def test_showing_twitter_works(self):
        c = json.loads(json.dumps(CONTENT))
        [x for x in c["social"] if x["name"] == "Twitter"][0]["show"] = True
        page, _ = render.render_page(c)
        self.assertIn('href="https://twitter.com"', page)

    def test_sample_report_goes_to_spectora(self):
        r = [s for s in CONTENT["sections"] if s["id"] == "reports"][0]
        self.assertTrue(r["buttonUrl"].startswith("https://app.spectora.com/"))
        self.assertIn("/sample.pdf https://app.spectora.com/", redirects_text(CONTENT))
        self.assertIn("/reports.html /#reports 301", redirects_text(CONTENT))


class TestBuild(unittest.TestCase):
    def test_build_outputs(self):
        out = ROOT / "dist"
        build(CONTENT, out=out)
        for f in ("index.html", "404.html", "robots.txt", "sitemap.xml", "_headers", "_redirects", "assets/site.css", "assets/site.js", "assets/theme.css"):
            self.assertTrue((out / f).is_file(), f)
        self.assertIn("Content-Security-Policy", (out / "_headers").read_text())

    def test_old_addresses_redirect(self):
        r = redirects_text(CONTENT)
        for old in ("/about.html", "/services.html", "/faq.html", "/schedule.html", "/defects.html", "/drones.html"):
            self.assertIn(old + " /#", r)
        self.assertIn("/gallery.html / 301", r)  # gallery is empty, so it goes to the home page


if __name__ == "__main__":
    unittest.main()


class TestStats(unittest.TestCase):
    def setUp(self):
        import tempfile
        from sitekit import stats
        self.stats = stats
        self.tmp = Path(tempfile.mkdtemp())
        self._old = (stats.DATA_DIR, stats.DB_PATH)
        stats.DATA_DIR, stats.DB_PATH = self.tmp, self.tmp / "stats.sqlite"

    def tearDown(self):
        import shutil
        self.stats.DATA_DIR, self.stats.DB_PATH = self._old
        shutil.rmtree(self.tmp)

    def test_classify(self):
        c = self.stats.classify
        self.assertEqual(c("https://www.google.com/", {})[:2], ("Google", "search"))
        self.assertEqual(c("https://www.bing.com/search?q=home+inspector+pace+fl", {})[3], "home inspector pace fl")
        self.assertEqual(c("", {})[:2], ("Direct / typed in", "direct"))
        self.assertEqual(c("https://specialtyhomeinspections.biz/", {}, "specialtyhomeinspections.biz")[1], "direct")
        self.assertEqual(c("https://l.facebook.com/", {})[:2], ("Facebook", "social"))
        self.assertEqual(c("", {"gclid": "x"})[:2], ("Google Ads", "paid"))
        self.assertEqual(c("", {"utm_source": "truck", "utm_medium": "qr"})[:2], ("QR code: truck", "qr"))
        self.assertEqual(c("https://www.bbb.org/us/fl/pace", {})[:2], ("BBB", "referral"))
        self.assertEqual(c("https://randomblog.example/post", {})[:2], ("randomblog.example", "referral"))

    def test_record_and_summary(self):
        import datetime as dt
        s = self.stats
        ua = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile Safari/604.1", "CF-IPCountry": "US", "cf-ipcity": "Pensacola", "cf-region": "Florida"}
        now = dt.datetime(2026, 10, 28, 18, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(s.record({"k": "view", "r": "https://www.google.com/"}, ua, "1.2.3.4", now=now))
        self.assertTrue(s.record({"k": "view", "r": ""}, ua, "1.2.3.4", now=now))
        self.assertTrue(s.record({"k": "call", "r": "https://www.google.com/"}, ua, "1.2.3.4", now=now))
        self.assertTrue(s.record({"k": "view", "q": {"utm_source": "truck", "utm_medium": "qr"}}, ua, "5.6.7.8", now=now))
        self.assertFalse(s.record({"k": "view"}, {"User-Agent": "Googlebot/2.1"}, "9.9.9.9", now=now))
        self.assertFalse(s.record({"k": "hack"}, ua, "9.9.9.9", now=now))
        out = s.summary(7, now=now)
        self.assertEqual(out["views"], 3)
        self.assertEqual(out["visitors"], 2)
        self.assertEqual(out["actions"], {"call": 1})
        self.assertIn("QR code: truck", [x["name"] for x in out["sources"]])
        self.assertEqual(out["places"][0]["name"], "Pensacola, Florida, US")
        self.assertEqual(out["devices"][0]["name"], "Phone")
        # no IP addresses stored anywhere
        import sqlite3
        con = sqlite3.connect(s.DB_PATH)
        dump = "\n".join(con.iterdump())
        con.close()
        self.assertNotIn("1.2.3.4", dump)
        self.assertNotIn("5.6.7.8", dump)


class TestSearchConsoleSigning(unittest.TestCase):
    def test_jwt_signature_verifies(self):
        import base64, subprocess, tempfile, os
        from sitekit import searchconsole
        d = tempfile.mkdtemp()
        key, pub = os.path.join(d, "k.pem"), os.path.join(d, "p.pem")
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
        jwt = searchconsole.make_jwt({"client_email": "x@y.iam.gserviceaccount.com", "private_key": Path(key).read_text()})
        head, body, sig = jwt.split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        self.assertEqual(claims["scope"], searchconsole.SCOPE)
        sigf = os.path.join(d, "s.bin")
        Path(sigf).write_bytes(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sigf],
                           input=f"{head}.{body}".encode(), capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestHoursAndLayout(unittest.TestCase):
    def test_hours_markup(self):
        page, _ = render.render_page(CONTENT)
        self.assertIn('data-tz="America/Chicago"', page)
        self.assertIn("05:00-23:30,05:00-23:30,05:00-23:30,05:00-23:30,05:00-23:30,05:00-23:30,05:00-23:30", page)
        self.assertIn("Open every day, 5:00 AM to 11:30 PM Central Time", page)

    def test_closed_day_and_bad_time(self):
        c = json.loads(json.dumps(CONTENT))
        c["hours"]["schedule"][0]["open"] = False
        page, _ = render.render_page(c)
        self.assertIn('data-sched=",05:00-23:30', page)
        c["hours"]["schedule"][2]["from"] = ""
        errors, _ = validate(c, check_media=False)
        self.assertTrue(any("Tuesday" in e for e in errors))

    def test_mobile_layout_css(self):
        css = render.render_mobile_layout_css((ROOT / "site" / "assets" / "site.css").read_text())
        self.assertIn("html.layout-mobile .callbar", css)
        self.assertIn("html.layout-mobile .hero-grid", css)
        self.assertIn("html.layout-mobile .menu-btn", css)
        self.assertNotIn("@media (max-width", css)
        c = json.loads(json.dumps(CONTENT)); c["theme"]["layout"] = "mobile"
        self.assertIn("layout-mobile", render.render_page(c)[0][:400])
        self.assertNotIn("layout-mobile", render.render_page(CONTENT)[0][:400])

    def test_stats_attr_and_csp(self):
        from sitekit.build import headers_text
        self.assertIn('data-stats="/api/hit"', render.render_page(CONTENT)[0][:600])
        self.assertNotIn("data-stats", render.render_page(CONTENT, preview=True)[0][:600])
        c = json.loads(json.dumps(CONTENT)); c["stats"]["endpoint"] = "https://stats.example.com/api/hit"
        self.assertIn("connect-src 'self' https://stats.example.com", headers_text(c))


class TestYearsInBusiness(unittest.TestCase):
    def test_years_since(self):
        import datetime as dt
        f = dt.date(2011, 8, 31)
        self.assertEqual(render.years_since(f, dt.date(2026, 8, 30)), 14)
        self.assertEqual(render.years_since(f, dt.date(2026, 8, 31)), 15)
        self.assertEqual(render.years_since(f, dt.date(2026, 10, 28)), 15)
        self.assertEqual(render.years_since(f, dt.date(2027, 8, 31)), 16)

    def test_tokens_render_live_span(self):
        page, _ = render.render_page(CONTENT)
        self.assertRegex(page, r'for over <span data-years-since="2011-08-31">\d+</span> years')
        self.assertRegex(page, r'<span data-years-since="2011-08-31">\d+</span> Years of Professional Service since 2011')
        self.assertNotIn("{years}", page)
        self.assertNotIn("{since}", page)

    def test_users_text_edits_kept(self):
        about = [s for s in CONTENT["sections"] if s["id"] == "about"][0]["body"]
        self.assertTrue(about.startswith("John Ellis is a Pensacola Florida Home Inspector, providing unbiased"))
        self.assertTrue(about.endswith("learn more about how we can help you."))
        self.assertEqual([s for s in CONTENT["sections"] if s["id"] == "why"][0]["title"], "Why a Home Inspection matters")
        self.assertEqual([s for s in CONTENT["sections"] if s["id"] == "reports"][0]["buttonText"], "Click Here To View Samples")

    def test_bad_founded_date(self):
        c = json.loads(json.dumps(CONTENT)); c["business"]["founded"] = "2011-13-40"
        self.assertTrue(any("start date" in e for e in validate(c, check_media=False)[0]))


class TestHiding(unittest.TestCase):
    def sec(self, c, sid):
        return [s for s in c["sections"] if s["id"] == sid][0]

    def test_faq_hide_renumbers(self):
        c = json.loads(json.dumps(CONTENT))
        self.sec(c, "faq")["items"][1]["hidden"] = True
        page, _ = render.render_page(c)
        nums = re.findall(r'<span class="faq-n">(\d+)\.</span><span class="faq-q">([^<]*)', page)
        self.assertEqual([n for n, _ in nums], [str(k) for k in range(1, 10)])
        self.assertNotIn("When can I expect the reports", page)
        self.assertEqual(nums[1][1], "When do I need to pay for the inspection and how do I do so ?")

    def test_hidden_faq_still_jumps_to_right_field(self):
        c = json.loads(json.dumps(CONTENT))
        self.sec(c, "faq")["items"][1]["hidden"] = True
        page, _ = render.render_page(c, preview=True)
        fi = [k for k, s in enumerate(c["sections"]) if s["id"] == "faq"][0]
        self.assertNotIn(f'data-path="sections.{fi}.items.1"', page)
        self.assertIn(f'data-path="sections.{fi}.items.2"', page)

    def test_hidden_certification_and_count(self):
        c = json.loads(json.dumps(CONTENT))
        items = self.sec(c, "credentials")["items"]
        items[0]["hidden"] = True
        items[5]["hidden"] = True
        page, _ = render.render_page(c)
        self.assertIn(f"Show all {len(items) - 2} certifications", page)
        self.assertNotIn(items[0]["image"], page)

    def test_hidden_text_item(self):
        c = json.loads(json.dumps(CONTENT))
        svc = self.sec(c, "services")
        svc["highlights"][2] = {"text": svc["highlights"][2], "hidden": True}
        hidden_text = svc["highlights"][2]["text"]
        page, _ = render.render_page(c)
        self.assertNotIn(hidden_text, page.split('class="highlights')[1].split("</aside>")[0])
        self.assertEqual(validate(c, check_media=False)[0], [])

    def test_numbered_list_renumbers(self):
        c = json.loads(json.dumps(CONTENT))
        d = self.sec(c, "defects")
        d["items"][0] = {"text": d["items"][0], "hidden": True}
        page, _ = render.render_page(c)
        self.assertEqual(re.findall(r'<span class="num" aria-hidden="true">(\d+)</span>', page), [f"{k:02d}" for k in range(1, 10)])


class TestHetzner(unittest.TestCase):
    def test_htaccess_rules(self):
        from sitekit import hetzner
        from sitekit.build import global_headers
        t = hetzner.htaccess_text(CONTENT, global_headers(CONTENT), redirects_text(CONTENT))
        self.assertIn("RewriteRule ^api/hit$ _api/hit.php [L]", t)
        self.assertIn("ErrorDocument 404 /404.html", t)
        self.assertIn("RewriteRule ^faq\\.html$ https://%{HTTP_HOST}/#faq [R=301,L,NE]", t)
        self.assertIn("RewriteRule ^sample\\.pdf$ https://app.spectora.com/", t)
        self.assertIn("^www\\.specialtyhomeinspections\\.biz\\.?$", t)
        self.assertIn("Content-Security-Policy", t)
        self.assertIn("\\s/+index\\.html[\\s?]", t)   # no redirect loop on the home page

    def test_counter_php_and_ingest(self):
        import datetime as dt
        import tempfile
        from unittest import mock
        from zoneinfo import ZoneInfo
        from sitekit import hetzner, stats
        php = hetzner.hit_php("America/Chicago")
        self.assertIn("dirname(__DIR__, 2) . '/stats-data'", php)
        self.assertNotIn("'ip' =>", php)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.object(stats, "DATA_DIR", tmp), mock.patch.object(stats, "DB_PATH", tmp / "s.sqlite"), \
                    mock.patch.object(hetzner, "INGEST_STATE", tmp / "state.json"):
                old = (dt.datetime.now(ZoneInfo("America/Chicago")).date() - dt.timedelta(days=3)).isoformat()
                ts = int(dt.datetime.fromisoformat(old + "T12:00:00-05:00").timestamp())
                ua = "Mozilla/5.0 (iPhone) Safari/604.1"
                rec = lambda k, r: json.dumps({"t": ts, "k": k, "r": r, "q": [], "ua": ua, "v": "v1"})
                (tmp / f"hits-{old}.jsonl").write_text(
                    rec("view", "https://www.google.com/search?q=pace+inspector") + "\n" + rec("call", "") + "\n" + '{"t":', encoding="utf-8")
                added, done = hetzner.ingest_dir(tmp)
                self.assertEqual((added, done), (2, [f"hits-{old}.jsonl"]))
                self.assertEqual(hetzner.ingest_dir(tmp)[0], 0)   # nothing counted twice
                s = stats.summary(30)
                self.assertEqual((s["views"], s["actions"]), (1, {"call": 1}))
                self.assertEqual(s["terms"][0]["name"], "pace inspector")

    def test_build_writes_apache_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dist"
            build(CONTENT, out=out)
            self.assertTrue((out / ".htaccess").is_file())
            self.assertTrue((out / "_api" / "hit.php").is_file())
            self.assertIn("Require all denied", (out / "_api" / ".htaccess").read_text())
            self.assertEqual((out / ".assetsignore").read_text().split(), [".htaccess", "_api"])


class TestBackupAndKit(unittest.TestCase):
    def test_retention(self):
        spec = importlib.util.spec_from_file_location("backup", ROOT / "tools" / "backup.py")
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        names = [f"specialty-{d}{s}.tar.gz" for d in ("2026-01-01", "2026-01-15", "2026-02-03", "2026-10-20",
                                                        "2026-10-27", "2026-10-28") for s in ("", "-full")]
        self.assertEqual(sorted(b.to_keep(names, 2, 2)), ["2026-02-03", "2026-10-20", "2026-10-27", "2026-10-28"])
        self.assertNotIn("editor/config.json", b.SITE_PARTS)   # secrets never go off the Pi
        self.assertFalse(any(p.startswith("editor/") for p in b.SITE_PARTS))

    def test_windows_kit_has_placeholder(self):
        ps1 = (ROOT / "deploy" / "windows" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn('__EDITOR_URL__', ps1)
        self.assertIn("--app=$Url", ps1)


class TestPiSetup(unittest.TestCase):
    def test_units_render(self):
        spec = importlib.util.spec_from_file_location("setup_pi", ROOT / "tools" / "setup_pi.py")
        sp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sp)
        for name in sp.UNITS:
            text = sp.unit_text(name)
            self.assertNotIn("REPLACE_WITH_YOUR_USER", text, name)
            if name.endswith(".service"):
                self.assertIn(f"WorkingDirectory={ROOT}", text)
        keys = [k for k, *_ in sp.STEPS]
        for _, _, _, _, needs, _ in sp.STEPS:   # every dependency is an earlier step
            for n in needs:
                self.assertIn(n, keys)

    def test_healthcheck_imports(self):
        spec = importlib.util.spec_from_file_location("healthcheck", ROOT / "tools" / "healthcheck.py")
        hc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hc)
        level, _ = hc.check_disk({})
        self.assertIn(level, (hc.OK, hc.WARN, hc.FAIL))


class TestCloudflareSetup(unittest.TestCase):
    """Connect Cloudflare + Website setup. No network: DNS and the upload tool are faked."""

    def setUp(self):
        import tempfile
        from sitekit import cloudflare as cf
        self.cf = cf
        self.tmp = tempfile.TemporaryDirectory()
        self.secrets = Path(self.tmp.name) / "secrets.env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_fields(self):
        v = self.cf.validate_fields
        self.assertEqual(v("A" * 40, "0123456789abcdef0123456789abcdef", False), {})
        self.assertIn("accountId", v("A" * 40, "nope", False))
        self.assertIn("token", v("has spaces in it here!!", "0123456789abcdef0123456789abcdef", False))
        self.assertIn("token", v("", "0123456789abcdef0123456789abcdef", False))
        self.assertEqual(v("", "0123456789abcdef0123456789abcdef", True), {})  # keep the saved token

    def test_secrets_stay_private(self):
        import os
        import stat
        self.secrets.write_text("HETZNER_THING=keep-me\n", encoding="utf-8")
        self.cf.save_credentials("Tok_" + "x" * 36 + "9Zq1", "0123456789abcdef0123456789abcdef", path=self.secrets)
        info = self.cf.credentials_info(path=self.secrets)
        self.assertTrue(info["ready"])
        self.assertEqual(info["tokenHint"], "9Zq1")
        self.assertNotIn("Tok_", json.dumps(info))                       # never sent to the browser
        self.assertIn("HETZNER_THING=keep-me", self.secrets.read_text())   # other settings survive
        self.assertEqual(stat.S_IMODE(os.stat(self.secrets).st_mode), 0o600)

    def test_reading_dns(self):
        self.assertTrue(self.cf.on_cloudflare(["ada.ns.cloudflare.com", "bob.ns.cloudflare.com"]))
        self.assertFalse(self.cf.on_cloudflare(["ns51.domaincontrol.com", "ns52.domaincontrol.com"]))
        self.assertFalse(self.cf.on_cloudflare([]))
        self.assertTrue(self.cf.email_routing_on(["13 route1.mx.cloudflare.net", "86 route2.mx.cloudflare.net"]))
        self.assertFalse(self.cf.email_routing_on([]))
        self.assertEqual(self.cf.site_domain(CONTENT), "specialtyhomeinspections.biz")
        self.assertEqual(self.cf.site_domain({"business": {"siteUrl": "https://www.example.com/x"}}), "example.com")

    def _deploy(self, status, cleared=True):
        """Run deploy_cloudflare with DNS, the API and wrangler faked; return (ok, message, command)."""
        from unittest import mock
        from sitekit import deploy
        ran = {}

        class R:
            returncode = 0
            stdout = "Uploaded specialty-home-inspections\n  https://specialty-home-inspections.someone.workers.dev\n"
            stderr = ""

        def fake_run(cmd, **kw):
            if cmd[-1] == "--version":
                return type("V", (), {"stdout": "v22.11.0"})()
            ran["cmd"] = cmd
            return R()
        with mock.patch.object(deploy, "read_secrets", return_value={"CLOUDFLARE_API_TOKEN": "t" * 40, "CLOUDFLARE_ACCOUNT_ID": "a" * 32}), \
                mock.patch.object(deploy.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(self.cf, "domain_status", return_value=status), \
                mock.patch.object(self.cf, "clear_old_records", return_value=cleared), \
                mock.patch.object(deploy.subprocess, "run", side_effect=fake_run):
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "index.html").write_text("<p>hi</p>")
                ok, msg = deploy.deploy_cloudflare(dist=Path(d))
        return ok, msg, ran.get("cmd", [])

    def test_domain_waits_for_email(self):
        base = {"domain": "specialtyhomeinspections.biz", "nameservers": [], "mx": []}
        # not on Cloudflare yet: temporary address, no --domain
        ok, msg, cmd = self._deploy(dict(base, onCloudflare=False, emailRouting=False))
        self.assertTrue(ok)
        self.assertNotIn("--domain", cmd)
        self.assertIn("workers.dev", msg)
        # on Cloudflare but email forwarding off: still no --domain, so John@ keeps working
        ok, msg, cmd = self._deploy(dict(base, onCloudflare=True, emailRouting=False))
        self.assertNotIn("--domain", cmd)
        self.assertIn("Email forwarding isn't on", msg)
        # both ready: the site takes the real address, www gets the redirect Worker
        ok, msg, cmd = self._deploy(dict(base, onCloudflare=True, emailRouting=True))
        self.assertIn("www.specialtyhomeinspections.biz", cmd)     # the last command run is the www redirect
        self.assertIn("APEX:specialtyhomeinspections.biz", cmd)
        self.assertIn("Live at https://specialtyhomeinspections.biz", msg)
        self.assertIn("www.specialtyhomeinspections.biz sends visitors", msg)
        # old records couldn't be cleared: stay on the temporary address rather than fail
        ok, msg, cmd = self._deploy(dict(base, onCloudflare=True, emailRouting=True), cleared=False)
        self.assertNotIn("--domain", cmd)

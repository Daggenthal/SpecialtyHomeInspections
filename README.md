# Specialty Home Inspections LLC website 🏠

A fast, modern, one-page site for Dad's business, plus a private editor so he can change anything himself and publish with one button.

No frameworks, no databases, nothing to `pip install`. Python 3 (already on Raspberry Pi OS) runs everything. Publishing uses Cloudflare's `wrangler` tool (needs Node.js 22 or newer, see "Node.js on the Pi").

## What's in here

| Path | What it is |
| --- | --- |
| `content/site.json` | Every word, link, price and picture on the site. The editor writes this file. |
| `content/media/` | Pictures. Filled by the import script, plus anything Dad uploads. |
| `site/assets/` | The site's CSS, JavaScript and the Oswald font (OFL license included). |
| `sitekit/` | Builder: turns `site.json` into plain HTML in `dist/`. |
| `editor/` | The editor (server + web interface). Home network only. |
| `tools/import_old_site.py` | Copies the original logo, badges and photos from the old site, byte for byte. |
| `tools/original_manifest.json` | SHA-256 fingerprints of every original file and testimonial, taken from the live site on 2026-10-28. |
| `tools/serve.py` | Small web server on the Pi. Runs the visit counter (and can serve the site locally). |
| `tools/hetzner_setup.py` | Older plan: publishing to Hetzner Webhosting over SFTP (not used). |
| `sitekit/hetzner.py` | Makes the Apache `.htaccess` and the PHP visit counter, uploads with rclone, downloads visits. |
| `sitekit/cloudflare.py` | Connect Cloudflare and the Website setup checks (domain, email, live site). |
| `deploy/wrangler.jsonc`, `deploy/www-redirect/` | The Cloudflare website, and the tiny Worker that sends `www.` to the bare address. |
| `deploy/` | systemd services (editor, backups, health check), Windows icon installer, tunnel example. |
| `tools/setup_pi.py` | Sets up or repairs everything on the Pi in one go. Safe to re-run. |
| `tools/healthcheck.py` | Daily check of the site, certificate, domain, email record, backups; phone alerts. |
| `tools/backup.py` | Nightly backups to the Pi's M.2 and to Hetzner, and restores. |
| `tools/make_windows_kit.py`, `deploy/windows/` | The "Website Editor" icon installer for Dad's PC. |
| `tests/` | `python3 -m unittest discover -s tests -v` |
| `LICENSE` | MIT for the code. The business's name, logo, photos and text are not covered. |

## How it's set up 🧭

```
 Dad's Windows PC                Raspberry Pi (at home)                  Cloudflare
 "Website Editor" icon  --Tailscale-->  editor (port 8787)  --Publish-->  the live site (static files)
 (an Edge window, nothing             backups on the M.2                  email forwarding: John@ -> Gmail
  stored on his PC)                   visit counter                       the domain's DNS
```

- **The editor only exists on the Pi.** It's reachable from home and over Tailscale, never from the internet.
- **Dad's PC holds nothing.** A new PC just needs Tailscale and the icon.
- **The live site is plain files on Cloudflare.** There's nothing there to log in to or break into, and it's free.
- **Setup lives in the editor.** **Website setup** (top bar) walks through Cloudflare, the domain and the email, and checks each step by itself. The first **Publish to website** asks for the Cloudflare details.

## Setup checklist ✅

The Pi part is one script. The rest happens in the editor's **Website setup**, which shows what's done and what's left.

**1. The Pi**
- [ ] Fit the M.2 HAT and drive. If `lsblk` doesn't show `nvme0n1`, add `dtparam=pciex1` to `/boot/firmware/config.txt` and reboot.
- [ ] Mount it (skip if the Pi boots from the M.2):
  ```bash
  # ONLY for a new, empty drive: these two lines erase it
  sudo parted /dev/nvme0n1 --script mklabel gpt mkpart m2 ext4 0% 100%
  sudo mkfs.ext4 -L m2 /dev/nvme0n1p1
  sudo mkdir -p /mnt/m2
  echo 'LABEL=m2 /mnt/m2 ext4 defaults,noatime,nofail 0 2' | sudo tee -a /etc/fstab
  sudo mount -a && sudo mkdir -p /mnt/m2/backups && sudo chown "$USER": /mnt/m2/backups
  ```
- [ ] Copy the project folder from the Mac to `~/specialty-site` on the Pi, including `content/media/`.
- [ ] Run the setup and follow what it asks. It also installs Node.js 22 and Cloudflare's upload tool:
  ```bash
  cd ~/specialty-site && python3 tools/setup_pi.py
  ```

**2. Cloudflare (in the editor)**
- [ ] Make a free account at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up).
- [ ] Create an API token: My Profile > API Tokens > Create Token > "Edit Cloudflare Workers" template. Add **Zone > DNS > Edit**, pick the account and the domain.
- [ ] Open the editor and press **Publish to website**. It asks for the token and the account ID, checks them, and publishes. The site goes to a temporary `*.workers.dev` address first, so you can click around before the domain moves.

**3. The domain and email (in the editor's Website setup)**
- [ ] Find the account that holds `specialtyhomeinspections.biz` (spelled `specialty`, see "Domain, DNS and email"). Turn on auto-renew and the registrar lock.
- [ ] Step 2 of Website setup: add the domain to Cloudflare (Free plan) and change its nameservers at the registrar to Cloudflare's two. **Switch the imported website records to grey "DNS only"** so John@ mail keeps arriving in the meantime.
- [ ] Step 3: Email Routing, catch-all forward to `specialtyhomeinspections@gmail.com`, verify the Gmail, "Add records and enable". Send a test to John@ from another address.
- [ ] Step 4: press **Publish to website**. Publish moves the address over by itself: it removes the old website records (never mail or text records), connects the site to the domain, and sends `www.` to the bare address. It only does this once steps 2 and 3 are green, so John@ never stops working.
- [ ] On the Pi: `python3 tools/setup_pi.py --check`. Everything should be ✅.

**4. Dad's PC**
- [ ] Copy `dist-windows/Website-Editor-Setup.zip` (the setup script made it) to his PC, unzip it, double-click **Install.cmd**. See "Dad's PC".

**5. Optional, worth it**
- [ ] Visit counter on Cloudflare (see "Visitor stats" > "After moving the site to Cloudflare"). Website setup step 5 shows whether it's counting.
- [ ] Google Search Console (see that section) and his Google Business Profile link.
- [ ] Limit his PC to the editor in Tailscale (see "Tailscale").

### What `tools/setup_pi.py` does

Each step checks first and is skipped if it's already done, so it's safe to run any time, including as a quick "is everything OK?" with `--check`. If a step fails, everything that doesn't depend on it still runs, and the summary says exactly what to do next. Fix that one thing and run it again. Every run is logged to `data/setup.log`.

| Step | Checks | Fixes it by |
| --- | --- | --- |
| Packages | rclone, ssh tools, curl | `apt install` |
| Original pictures | all 73 files match their fingerprints | downloading from the old site (only while it's still up; otherwise copy them from the Mac) |
| Tests | the full test suite passes | (shows what failed) |
| Tailscale | installed and signed in | installing it and starting `tailscale up` |
| Editor password | one is set | asking for it |
| Editor access | home network + Tailscale only, the Pi's Tailscale name allowed | updating `editor/config.json` |
| Publishing | Node.js 22+, Cloudflare's upload tool, Cloudflare connected (or Hetzner, if that's the target) | installing Node.js from NodeSource and running `npm ci`; the Cloudflare details are entered in the editor |
| Backup folder | exists, writable, not on the SD card | asking which drive to use |
| Services | editor, nightly backup and daily health check installed, up to date and running | installing them into systemd with your user name filled in |
| Editor answers | the editor page loads | (shows where to look) |
| Phone alerts | an ntfy topic is set (optional) | making a random topic and sending a test |
| First backup | a backup succeeded | running one |
| Windows installer | Dad's zip exists for the current Tailscale name | making it |
| Health check | the live site, certificate, `www`, counter, mail record, domain expiry, editor, backups, disk space | (lists what's wrong) |

### Daily health check and phone alerts 📱

`tools/healthcheck.py` runs every morning and checks:
- the live site, the certificate and that `www` goes to the bare address
- the visit counter
- the mail (MX) record that keeps `john@` forwarding
- the **domain's expiry date**
- the editor, the last backup, and disk space (and the Hetzner login, only if that's set up)

If something fails it sends a notification to your phone through [ntfy](https://ntfy.sh) (free, no account; install the app and subscribe to the topic the setup prints). It sends one more when things are fine again. Run it by hand any time: `python3 tools/healthcheck.py`.

## Tailscale 🔐

Tailscale is a private network between your own devices. The editor accepts Tailscale addresses (`100.64.0.0/10`) and the Pi's Tailscale name, and still refuses everything from the public internet.

- `tools/setup_pi.py` installs Tailscale, signs the Pi in, and allows the Pi's Tailscale name in the editor.
- Add Dad's PC to your tailnet. The simplest way is to sign in on his PC as you, or invite him.
- **Recommended:** limit his PC to the editor and nothing else on your network. Tag the Pi `tag:editor` and his PC `tag:dad`, then in the Tailscale admin console under Access controls:

```json
{
  "tagOwners": { "tag:editor": ["autogroup:admin"], "tag:dad": ["autogroup:admin"] },
  "grants": [
    { "src": ["autogroup:member"], "dst": ["*"], "ip": ["*"] },
    { "src": ["tag:dad"], "dst": ["tag:editor"], "ip": ["tcp:8787"] }
  ]
}
```

The first rule keeps your own devices working as before. The second lets his PC reach port 8787 on the Pi only. Check it against Tailscale's docs for your plan before saving, since a policy replaces the default "everything can reach everything".

## Dad's PC (Windows 11) 🪟

No Electron, no Python, nothing running in the background. The icon opens the editor in its own Edge window with no address bar, so it looks and acts like a normal program.

1. `tools/setup_pi.py` makes `dist-windows/Website-Editor-Setup.zip` for the Pi's Tailscale name, with the site's own favicon as the icon. To make it by hand: `python3 tools/make_windows_kit.py http://pi.tail1234.ts.net:8787/`.
2. Copy the zip to his PC, unzip it and double-click **Install.cmd**.
   - If Tailscale isn't on his PC, it offers to install it (winget). He signs in, then runs Install.cmd again.
   - It puts **Website Editor** on the desktop and in the Start menu.
3. He double-clicks the icon, signs in with his editor password and edits as usual. Publish uploads to Hetzner from the Pi.

**New PC:** install Tailscale, sign in, run Install.cmd. Nothing else to move.

## Backups 💾

`tools/backup.py` runs every night at about 3:17 AM (systemd timer). It only makes a new backup if something changed.

| Where | What | Kept |
| --- | --- | --- |
| Pi, on the M.2 | `specialty-DATE-full.tar.gz`: everything, including the editor password hash, the Hetzner key and private settings | 30 days, plus one per month for 2 years |
| Pi, on the M.2 | `specialty-DATE.tar.gz`: content, pictures, edit history, visit counts | same |
| Hetzner, `~/backups` (outside `public_html`) | the same `specialty-DATE.tar.gz`. **No passwords or keys leave the Pi.** | same |

`tools/setup_pi.py` sets this up (folder, timer, first backup). The folder is saved in `editor/config.json` as `"backup": {"local_dir": "/mnt/m2/backups/specialty-site"}`.

- If the M.2 isn't mounted, the backup stops with a clear message instead of filling the SD card.
- If Hetzner can't be reached, the Pi copy is still made and Hetzner is retried the next night.

**Restore** (for example on a rebuilt Pi):

```bash
sudo systemctl stop specialty-editor
python3 tools/backup.py --list
python3 tools/backup.py --restore /mnt/m2/backups/specialty-site/specialty-2026-11-02-full.tar.gz
sudo systemctl start specialty-editor     # then check the preview and press Publish
```

With Cloudflare there's no off-site copy from this script, so keep the M.2 backups somewhere else now and then (or sync `/mnt/m2/backups` to another machine). If the Pi is gone entirely, restore the latest `specialty-DATE.tar.gz` from wherever that copy is. Restore it, then run `editor/server.py setup` and `tools/hetzner_setup.py` again, since keys and passwords were never in that copy.

## Cloudflare (the live site) ☁️

The site is plain static files served by Cloudflare (Workers static assets, free). The Pi only runs the editor. Everything is set up from the editor: **Website setup** in the top bar.

**What Publish does**
1. Builds the site into `dist/` (the Hetzner-only files `.htaccess` and `_api/` are left out by `dist/.assetsignore`).
2. Copies it to the local folder too, if that target is on (a ready-to-serve copy on the Pi).
3. Uploads it with `wrangler deploy --config deploy/wrangler.jsonc` using the token in `editor/secrets.env` (mode 600, git-ignored, never shown in the editor).
4. **Only when** the domain's nameservers are Cloudflare's **and** email forwarding is on: removes the old website records for the bare address and `www` (only A, AAAA and CNAME; MX and TXT are never touched), attaches the site to the bare address, and deploys `deploy/www-redirect/` on `www.` so it sends visitors to the bare address. Until then the site stays on its temporary `*.workers.dev` address and the publish result says which step is missing.

**The token** needs the "Edit Cloudflare Workers" template plus **Zone > DNS > Edit** for the domain. Change it any time in Website setup > Change. If Cloudflare ever rejects it, the publish result says so.

**Undo a publish:** History in the editor brings back any earlier version; publish it again. Cloudflare also keeps its own versions: `npx wrangler rollback --config deploy/wrangler.jsonc` (with the token loaded: `set -a; . editor/secrets.env; set +a`).

### Node.js on the Pi

Cloudflare's upload tool needs Node.js 22 or newer. Raspberry Pi OS ships an older one, so `tools/setup_pi.py` installs it from NodeSource. By hand:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o nodesource_setup.sh
less nodesource_setup.sh                 # read it first
sudo bash nodesource_setup.sh && sudo apt install -y nodejs
cd ~/specialty-site && npm ci            # installs the pinned wrangler into node_modules/
```

On Dad's Windows PC nothing is needed: the editor runs on the Pi.

## Hetzner Webhosting (older plan, not used) 🌐

Kept in case it's ever useful again. Nothing below is needed for the Cloudflare setup. To switch back, run `tools/hetzner_setup.py` and set the publish target to `hetzner` in `editor/config.json`.

How it fits together:

```
 Dad's editor (home only)  --Publish-->  Hetzner Webhosting  -->  visitors
   builds the site                          plain files + .htaccess
   holds the SFTP key                       _api/hit.php (visit counter)
   downloads visit counts  <--SFTP------    stats-data/ (outside public_html)
```

Nothing on the server can change the website. There's no admin page, no login and no database, so there's nothing to break into. If someone ever did tamper with the files, the next Publish puts them back.

**Why rclone and not rsync:** rsync needs an SSH shell on the server, and Webhosting S and M only give SFTP. `rclone sync` over SFTP does the same job: it uploads only what changed and removes what's gone. Uploads happen in two steps: new pictures and styles first, then the page itself, then old files are removed. Visitors never see half a site.

### Setting it up (once)

1. **Install rclone** on the computer that runs the editor.
   - Raspberry Pi: `sudo apt install rclone`
   - Windows: `winget install Rclone.Rclone` (then sign out and back in so it's on the PATH)
   - `ssh-keygen` and `ssh-keyscan` are already there on both.
2. In **konsoleH**, look up the SFTP server name and the **main** FTP user (Hetzner only allows key logins for the main user).
3. Run `python3 tools/hetzner_setup.py`. It:
   - makes a key in `editor/keys/` (git-ignored; the private half never leaves this computer)
   - prints the public key in the **RFC4716** format konsoleH asks for. Paste all of it, including the `---- BEGIN` and `---- END` lines, into konsoleH's SSH key field for the main FTP user
   - saves the server's fingerprint, so uploads refuse any other server
   - tests the login and turns on the `hetzner` Publish target
   - If konsoleH doesn't accept the key, run it again with `--rsa`. `--test` only checks the connection.
4. **SSL:** turn on the free certificate for the domain in konsoleH. The `.htaccess` sends every visitor to `https://`, but lets the certificate check (`/.well-known/`) through.
5. Restart the editor and press **Publish**.

**Try it before moving the domain:** konsoleH gives the account a temporary address. Publish, open that address and click around. The `.htaccess` only redirects `www.` to the real domain, so the temporary address works as is.

### What the Publish uploads

| File | What it does |
| --- | --- |
| `index.html`, `404.html`, `assets/`, `media/` | The site |
| `.htaccess` | https only, one address (`www.` goes to the bare domain), security headers (the same as Cloudflare's `_headers`), caching, gzip, the old page redirects (`/faq.html` goes to `/#faq`, `/sample.pdf` to Spectora), the 404 page, and it hides build files |
| `_api/hit.php` | The visit counter (see below). Everything else in `_api/` is blocked from the web. |

Never touched on the server: `.well-known/`, `cgi-bin/`, `stats-data/`, `.user.ini`. Anything else in `public_html` that isn't part of the site gets removed on Publish, so don't keep other files there.

### Visitor stats on Hetzner

Shared hosting can't keep a Python program running, so the counter there is one small PHP file, `_api/hit.php`. It keeps exactly what the Pi version keeps, and it **never stores IP addresses**. The daily visitor code is made on the server with a salt that's replaced every day.

- Each visit is one line in `~/stats-data/hits-YYYY-MM-DD.jsonl`, **next to** `public_html`, not inside it, so nobody can read it over the web.
- When Dad opens **Visitors** in the editor, the editor downloads new lines over SFTP (at most every 5 minutes), adds them to `data/stats.sqlite` and deletes finished days from the server.
- Bots and junk are ignored, and a day's file stops growing at 20 MB, so it can never fill the account.
- Cities and regions aren't available on Hetzner (that came from Cloudflare's headers). Sources, search words, QR codes, ads, devices and Call/Text/Email taps all still work.
- If PHP isn't allowed to create `~/stats-data`, it falls back to `public_html/_api/data/` (still blocked from the web). Then set `"stats_dir": "public_html/_api/data"` under `deploy.hetzner` in `editor/config.json`.

### Settings (`editor/config.json`)

```json
"deploy": {
  "targets": ["hetzner"],
  "hetzner": {
    "host": "www123.your-server.de",
    "port": 22,
    "user": "main-ftp-user",
    "remote_dir": "public_html",
    "stats_dir": "stats-data"
  }
}
```

`key_file` and `known_hosts` default to `editor/keys/hetzner` and `editor/keys/known_hosts`.

**Change the key** (new computer, or if it might have leaked): delete `editor/keys/`, run `tools/hetzner_setup.py` again, paste the new key into konsoleH and delete the old one there.

## Domain, DNS and email 📬

### What the public records showed (2026-10-28)

- The domain is **specialtyhomeinspections.biz**, spelled `specialty` with no "i" after the "t". Search for that spelling.
- DNS is on **GoDaddy** (`ns51.domaincontrol.com`). The site is on a GoDaddy hosting server (`148.72.8.248`). DNS was last changed on 2026-10-21.
- **There are no MX (mail) records.** Mail to `John@specialtyhomeinspections.biz` still arrives because senders fall back to the domain's A record, which happens to be the GoDaddy server that also handles his mail. When the A record moves to Hetzner, that address stops working unless MX is set up.
- There's no SPF or DMARC either.

### His email

The website now shows **specialtyhomeinspections@gmail.com** (Dad finds Gmail easier to check). The old `John@specialtyhomeinspections.biz` is printed on cards, invoices and old listings, so keep it alive as a **forward to the Gmail**: nothing new to check, nothing lost.

### Checklist

- [ ] Find which GoDaddy account holds the domain (Dad's other login, or the developer's).
- [ ] Make sure the **registrant is Dad** (the business), not the developer.
- [ ] Turn on **auto-renew** and the **registrar lock**. Check that the renewal email goes to an address someone actually reads. Moving the registration to Cloudflare Registrar later is optional.
- [ ] Follow the editor's **Website setup**: nameservers to Cloudflare (step 2), Email Routing catch-all to the Gmail (step 3), then Publish (step 4).
- [ ] After forwarding works, add the anti-spoofing record in Cloudflare > DNS: `_dmarc` TXT `v=DMARC1; p=reject`. Email Routing adds its own SPF record; leave it.
- [ ] Verify the domain in Google Search Console with its TXT record (Cloudflare can add it for you).
- [ ] Update his Google Business Profile, Facebook page and the BBB listing to the new site link and email.

### DNS records for Hetzner (older plan, not used)

| Name | Type | Value | Why |
| --- | --- | --- | --- |
| `@` | A | `_____` (Hetzner server IPv4) | the website |
| `@` | AAAA | `_____` (Hetzner server IPv6) | the website |
| `www` | CNAME | `specialtyhomeinspections.biz.` | `www.` address (redirected to the bare one) |
| `@` | MX 10 | `_____` (Hetzner mail server) | keeps `john@` working (forwarded to Gmail) |
| `@` | TXT | `v=spf1 -all` | he sends from Gmail, so nothing sends as `@specialtyhomeinspections.biz`. This stops scammers sending fake mail as the business. If he ever sends from the domain again, change it to Hetzner's SPF value. |
| `_dmarc` | TXT | `v=DMARC1; p=reject` | same reason: mail faking the domain gets rejected |
| `@` | TXT | `google-site-verification=_____` | Search Console |

Record names and values here are placeholders; use exactly what konsoleH and Google give you.

## Business hours and clocks 🕔

The top of the page shows a green **Open now** or an amber **Closed right now · Opens in 5 hr 15 min**. The Contact section shows the visitor's clock and ours side by side, with the day of the week, plus the weekly hours.

- Time is calculated from the real `America/Chicago` zone, so it says CDT or CST correctly and handles the daylight-saving switch (tested on the night it changes).
- The default is every day, 5:00 AM to 11:30 PM. Opening and closing at the same time means open all day; closing after midnight works too.
- Visitors in Central Time see a single clock ("same as ours").

## Visitor stats 📈

Counted by `tools/serve.py` on the Pi, or by `_api/hit.php` on Hetzner (see "Visitor stats on Hetzner" above), and stored with the editor in `data/stats.sqlite`. No Google Analytics, no cookies, no consent banner needed.

- **Kept:** time, source (search engine, social site, ad, QR code, other website, typed in), search words when the referring site shares them (Bing and DuckDuckGo sometimes do, Google never does), device, city/region/country from Cloudflare, and taps on Call, Text, Email, Facebook and the sample report.
- **Never kept:** IP addresses, cookies or anything that identifies a person. Unique visitors use a hash with a random salt that's replaced every day, so nobody can be followed from one day to the next.
- Visitors whose browser sends Do Not Track or Global Privacy Control aren't counted (switchable in the editor). Bots are ignored. About two years of history are kept.
- For city and region: in Cloudflare, turn on Rules > Transform Rules > Managed Transforms > "Add visitor location headers". Country comes through either way.

**Ads:** Google Ads auto-tagging is recognized on its own. For anything else, add tags to the link, e.g. `?utm_source=nextdoor&utm_medium=paid&utm_campaign=spring`.
**Google Business Profile:** set its website link to `https://specialtyhomeinspections.biz/?utm_source=google&utm_medium=business_profile` and those visits get their own row.

**After moving the site to Cloudflare:** the counter still runs on the Pi. Add a tunnel hostname such as `stats.specialtyhomeinspections.biz` pointing at `http://127.0.0.1:8080`, then in the editor (Visitor stats) set "Where the counter lives" to `https://stats.specialtyhomeinspections.biz/api/hit` and publish. The site's security policy picks up the new address automatically.

## Search phrases (Google Search Console) 🔍

Google never tells websites what people searched, so this is the only way to see it. It's free.

1. Add the domain at [search.google.com/search-console](https://search.google.com/search-console) as a **Domain** property and verify it with the DNS record it gives you (easy once the domain is on Cloudflare).
2. In Google Cloud Console: create a project, enable the **Google Search Console API**, create a **service account**, and create a **JSON key** for it.
3. Save the key on the Pi as `editor/google-service-account.json`, then `chmod 600 editor/google-service-account.json` (git-ignored).
4. In Search Console > Settings > Users and permissions, add the service account's email with **Restricted** access.
5. Run `python3 editor/server.py setup` and enter `sc-domain:specialtyhomeinspections.biz` when asked.

The Visitors dashboard then lists the top searches with clicks, times shown, click rate and average position (Google's data runs about 2 days behind; refreshed every 6 hours). The login token is signed with the Pi's `openssl`, so nothing extra to install. Heads up: I tested the signing and request format here, but couldn't test against Google's live servers.

## How the editor stays private 🔒

The public site is static files and can't touch the editor. The editor itself refuses a request unless all of these are true:

- It comes from the Pi itself or a home-network address (never a public IP).
- It did **not** arrive through Cloudflare or any proxy (`CF-Connecting-IP`, `X-Forwarded-For` and friends are rejected). So even if the tunnel got pointed at it by mistake, it answers 403.
- It's addressed to a local hostname (`localhost`, `*.local`, a LAN IP). This blocks DNS-rebinding tricks.
- The browser is signed in (PBKDF2 password hash, HttpOnly + SameSite=Strict cookie, lockout after 5 wrong tries).
- Changes come from the editor page itself (Origin check + custom header), so other websites can't post to it.

Uploads are checked by their bytes (JPEG/PNG/GIF/WebP only). Deleted pictures go to `content/.trash/`, never hard-deleted. **Over Tailscale:** `python3 editor/server.py setup` asks about it. That allows Tailscale's private address ranges and the machine's Tailscale name, and still refuses everything from the public internet.

## What Dad can do in the editor ✍️

- Edit every piece of text, price, question, service, link, phone number and email. Tapping Call, Text or Email in the preview shows what the button does (nothing is dialed or sent) with a "Change the phone number" shortcut.
- **Years in business** count themselves: write `{years}` in any text for the years since the start date (Business info > "Business started on", set to Aug 31, 2011) and `{since}` for the year. The number goes up by itself every Aug 31 in visitors' browsers, no republish needed.
- Reorder any list by dragging the ⠿ handle (mouse or finger), or with the ↑ ↓ buttons. The item stays put on screen.
- **Hide without deleting:** every list item (FAQ questions, certifications, services, highlights, prices, links, reviews, photos) has a 👁 button. Hidden items stay in the editor, dimmed and marked "Hidden on website", and come back with one tap. Numbers on the website (FAQ 1, 2, 3… and the Top 10 list) and the "Show all N certifications" count skip hidden items automatically.
- 💾 Save buttons sit at the bottom of every open section and in a bar that appears whenever there are unsaved changes, so he never has to scroll up to save. The preview updates while he types, and he can click anything in the preview to jump to where it's edited.
- **Bold** and links with buttons, no code.
- Add, hide, reorder or delete whole sections; add new ones (text, picture + text, list, Q&A, photo gallery, links, reviews).
- Upload photos (big phone photos are shrunk automatically, iPhone HEIC converted when the browser can).
- Preview as computer, tablet or phone, or open the preview on his own phone.
- Social pages with show/hide switches, and buttons that can link to a web page or an uploaded PDF.
- **Hours of operation:** a switch per day plus "opens" and "closes" times, "Copy Monday to every day", "Open 24 hours", and the time zone.
- **Page layout A/B:** A is the computer layout, B is the phone layout on every screen. "Compare A and B side by side" shows both, and one click picks what visitors get.
- **📈 Visitors:** visitors per day, where they came from (Google, Bing, Facebook, ads, QR codes, other sites, typed in), who tapped Call / Text / Email and where they came from, city, device, and Google search phrases once Search Console is connected.
- **QR codes:** for the truck, postcards, business cards, flyers, yard signs or anywhere else. Each one opens the website (with its scans counted separately), calls him, or saves his contact card. Pick a printed size (¾ inch business card up to 24 inch tailgate, or a custom size in inches or cm). The SVG prints at exactly that size, the PNG is 300 dpi, and it says how far away it can be read and warns below about ⅝ inch.
- Colors (with a "Use the logo colors" reset), dark mode setting, animations on/off, Google title and description.
- Undo/Redo, a full History of every save and publish with "Bring this back", and unsaved work survives closing the browser.
- **Save** keeps changes on the Pi. **Publish to website** puts them live.

Protected on purpose:

- **The logo** can't be changed or edited. The build also refuses to publish if `media/logo.jpg` doesn't match its original fingerprint.
- **The four original reviews** are locked. Editing one requires "Unlock to edit" plus a confirmation, and the save is refused if a locked review's text changes. New reviews can be locked with one click too.
- **Discount amounts**: if any text mentions a discount together with a dollar or percent amount, publishing stops and asks "Publish anyway?". Items approved on purpose (like FAQ #7) are skipped.

## Things I changed from the old site (please check) 👀

Everything else is Dad's original wording, copied from the old pages' HTML.

1. **FAQ #7 (discounts)** keeps the original wording, including the $25 amount, as you asked. It's marked "approved" in the editor, so the discount-amount check skips it. Any other text that pairs a discount with an amount still triggers "Publish anyway?".
2. **FAQ intro.** It told people to use a comments box at the bottom of the page. That box never had a working form, so it now says to call, text or email.
3. **Gallery.** All 24 photos on the old gallery page are already broken (404). They were hosted on forrestmarketing.com under `/sample/sample/pictures/`, so they look like the developer's template stock photos, not Dad's. The gallery stays hidden until Dad uploads his own.
4. **Sample Reports** is its own section again (same picture as the old page). The picture and the "Sample Residential Report" button open the Spectora report, and the old `/sample.pdf` address redirects there. The editor can also take an uploaded PDF for any button if he ever wants one.
5. **Social links.** Facebook shows. Twitter and LinkedIn are kept exactly as they were (they pointed at twitter.com and linkedin.com, not a profile) but switched off. Dad can turn either on, fix the address, or add new ones under Business info.
6. **Search keywords.** The old meta keywords included "Dahlonega" and "Adairsville", which are Georgia towns left over from a template. Replaced with Pensacola/Pace terms.
7. **Headline.** "Pensacola Florida Home Inspections" at the top is the one new line I wrote. Easy to change in the editor.
8. **Small wording fixes I did NOT make**, because it's his text: "it's location" (its), "allow you to to look". The review typos ("preformed", "to informs") stay forever, since reviews are word for word.
9. **John's photo** has white borders baked into the file. The site crops them off on display; the file is untouched ("Undo trim" in the editor).
10. **Forrest Marketing credit** removed from the footer. The copyright year updates itself.
11. **Old addresses** like `/faq.html`, `/about.html` or `/reports.html` redirect to the matching section, so Google results and old links keep working.
12. **Useful Information links** are kept as they were. Several look stale (about.com, servicemagic.com, apestcontrol.com, homefair.com). I couldn't test them from here; Dad can remove any dead ones in the editor.

## Checking my work ✅

- `python3 tools/import_old_site.py --check` re-verifies every picture against the original fingerprints.
- The tests check each testimonial three ways: the text in `site.json`, the text as rendered in the HTML, and the recorded SHA-256 of the original from the live site.
- `sha256sum content/media/logo.jpg` should print `3b7c85641176f946cf283d1774047ab6333909ee7458c80e20744e7b8c5d632a`.

## Committing

Nothing is committed. When you're happy:

```bash
cd ~/specialty-site
git init
git add -A
git commit -S --author="Daggenthal <112846802+Daggenthal@users.noreply.github.com>" \
  -m "Modern site and private editor for Specialty Home Inspections LLC" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
  -m "Claude-Session: https://claude.ai/code/session_01UAtbF4qbLhjo71kK82eHsr"
```

## GitHub 🐙

The repo is `Daggenthal/SpecialtyHomeInspections`. Nothing has been pushed yet. When it's time:

```bash
cd ~/specialty-site
git init -b main
git config user.name "Daggenthal"
git config user.email "112846802+Daggenthal@users.noreply.github.com"
git remote add origin git@github.com:Daggenthal/SpecialtyHomeInspections.git

# Anything you never want in the repo (real name, Mac user name, home address...), one per line.
# This file is git-ignored, so the list itself is never committed.
nano .privacy-words

python3 tools/privacy_check.py        # must say "Clean"
printf '#!/bin/sh\nexec python3 tools/privacy_check.py\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

git add -A && git status              # read the list once
git commit -S -m "Specialty Home Inspections website and editor" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
git push -u origin main
```

Never committed (see `.gitignore`): the editor password hash, the Hetzner key, `secrets.env`, the Google key, visit counts, edit history, backups and the built site.

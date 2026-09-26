# Someless Mail Server

Welcome to **Someless Mail Server**: your own mail server in a single Docker image. Install it on your server, open the web interface, connect your domain, and send email from your apps and websites through your own server, signed and trusted like mail from the big providers.

**Version:** 1.0.0

> **Status:** sending works. Connect and authenticate your domain, add the addresses your mail comes from, and your apps send through your own server. Inboxes, and receiving mail, come next.

This guide takes you from installing to your first email landing in a Gmail inbox. Follow the steps in order; each one takes a few minutes, apart from waiting for DNS changes to show up.

## How it fits together

- **The web interface** (port 17080) is where you set everything up: domains, senders, SMTP keys.
- **The mail engine**, [Stalwart](https://github.com/stalwartlabs/stalwart), runs in the same container and sends the mail. You never set it up yourself: the web interface does it for you.
- **[Nginx Proxy Manager](https://nginxproxymanager.com/)** (optional, recommended) puts the web interface on HTTPS, and passes Let's Encrypt's check through to the mail engine so your mail server gets its own certificate.

## What you need

- **A Linux server (VPS)** with [Docker](https://docs.docker.com/engine/install/) and a fixed public IP address.
- **A domain you own**, like `example.com`, and access to its DNS settings at your domain provider (Namecheap, Cloudflare, GoDaddy…).
- **Outgoing port 25 open at your provider.** Mail servers deliver to each other on port 25, and many VPS providers block it until you ask. See [Step 6](#step-6-reverse-dns-and-port-25).
- **Recommended:** Nginx Proxy Manager on the same server, for HTTPS.

## The names you'll use

Three names come up in this guide. With the domain `example.com`:

| Name | Example | What it's for |
|---|---|---|
| Your mail domain | `example.com` | The part of your addresses after the @, like `no-reply@example.com` |
| Your mail server's name | `mail.example.com` | What your apps connect to, what your server's certificate is for, and what other mail servers see. Someless Mail gives you its record in [Step 4](#step-4-connect-and-authenticate-your-domain) |
| The web interface's name (optional) | `panel.example.com` | Opening the web interface over HTTPS, in [Step 3](#step-3-https-for-the-web-interface) |

Keep the web interface and the mail server on **different names**. `mail.example.com` belongs to the mail server: its certificate depends on it (see [Step 5](#step-5-your-mail-servers-certificate)).

## Step 1: Install

Pick one of the two ways below. Both keep all your data in a `data` folder right where you install Someless Mail, so it's easy to find and back up, and it survives updates and restarts (see [Your data](#your-data)).

First make sure the ports are free on your server. This should print nothing:

```
sudo ss -tulpn | grep -E ':(587|465|17080|17081) '
```

### Option 1: Docker Compose (recommended)

Create a folder, and save this as `docker-compose.yml` inside it (the same file is in this repository):

```yaml
services:
  someless-mail:
    image: ghcr.io/boyoftime/someless-mail:1.0.0
    container_name: someless-mail
    restart: unless-stopped
    ports:
      - "17080:17080"   # web interface (behind Nginx Proxy Manager you can drop this line: see Step 3)
      - "587:17587"     # your apps send mail here (STARTTLS)
      - "465:17465"     # your apps send mail here (TLS from the start)
      # - "80:17081"    # only without a reverse proxy: Let's Encrypt's check of your mail server's name
    volumes:
      - ./data:/data    # all your data, in a "data" folder next to this file
```

Then start it from that folder:

```
docker compose up -d
```

The `data` folder appears next to `docker-compose.yml` on the first start.

### Option 2: `docker run`

Run this from the folder where you want your `data` folder:

```
docker run -d --name someless-mail --restart unless-stopped \
  -p 17080:17080 -p 587:17587 -p 465:17465 \
  -v "$(pwd)/data:/data" \
  ghcr.io/boyoftime/someless-mail:1.0.0
```

### Open your firewall

If your server has a firewall, allow inbound TCP `587` and `465` (your apps send mail there), and `17080` if you open the web interface by IP. With `ufw`:

```
sudo ufw allow 587/tcp && sudo ufw allow 465/tcp && sudo ufw allow 17080/tcp
```

### Open it

Go to `http://your-server-ip:17080` in your browser. You'll see a short welcome animation, then the login page. The very first start takes a little longer (up to a minute): Someless Mail sets its mail engine up before the web interface opens.

## Step 2: Log in and lock it down

| Username | Password |
|---|---|
| `admin` | `admin` |

Change both right after your first login in **Settings**. Until you change the password, the dashboard shows a warning: anyone who knows the default can log in.

### Two-factor authentication

In **Settings → Two-factor authentication**, switch on **Use PIN**. Scan the QR code with any authenticator app (Google Authenticator, Microsoft Authenticator, Authy…), or copy the key into it, then enter the 6-digit PIN the app shows. From then on, logging in asks for your password and then the PIN. The password is always required.

After 5 wrong PINs in a row, no PIN is accepted for 5 minutes.

**Lost your phone?** Switch the PIN off from the server, then log in with just your password:

```
docker exec -u someless someless-mail flask --app someless two-factor off
```

## Step 3: HTTPS for the web interface

Optional, but worth it: your login then travels encrypted, and you open Someless Mail at `https://panel.example.com` with no port number. This uses [Nginx Proxy Manager](https://nginxproxymanager.com/); any reverse proxy works the same way.

1. **At your domain provider**, add an A record for the web interface's name, pointing to your server's IP address:

   | Type | Host | Value |
   |---|---|---|
   | A | `panel` | your server's IP address |

2. **Put Someless Mail on the proxy's Docker network.** With Nginx Proxy Manager on a network called `nginx-proxy`, your `docker-compose.yml` becomes:

   ```yaml
   services:
     someless-mail:
       image: ghcr.io/boyoftime/someless-mail:1.0.0
       container_name: someless-mail
       restart: unless-stopped
       ports:
         - "587:17587"     # your apps send mail here (STARTTLS)
         - "465:17465"     # your apps send mail here (TLS from the start)
       expose:
         - "17080"         # web interface, for the proxy only
         - "17081"         # Let's Encrypt's check of your mail server's name (Step 5)
       volumes:
         - ./data:/data
       networks:
         - nginx-proxy

   networks:
     nginx-proxy:
       external: true
   ```

   Then run `docker compose up -d` again. The mail ports stay published: a web proxy can't carry mail.

3. **In Nginx Proxy Manager**, add a proxy host:

   | Setting | Value |
   |---|---|
   | Domain names | `panel.example.com` |
   | Scheme | `http` |
   | Forward hostname | `someless-mail` |
   | Forward port | `17080` |
   | SSL tab | Request a new SSL certificate, with **Force SSL** and **HTTP/2** on |

4. Open `https://panel.example.com` and log in.

## Step 4: Connect and authenticate your domain

In **Domains**, click **Add domain** and type the part of your email address after the @ (like `example.com`). Then click **Authenticate** next to it. The page lists the DNS records to add at your domain provider, each with copy buttons:

| Record | What it does |
|---|---|
| Someless code (TXT) | Shows that the domain is yours |
| A (host `mail`) | Points your mail server's name, `mail.example.com`, at your server |
| SPF (TXT) | Lets your server send the domain's mail |
| DKIM (TXT) | Signs your mail so nobody can fake it. The private key never leaves your server (it's in `data/`) |
| DMARC (TXT) | Tells other mail servers what to do with mail that fails these checks |

Add them all, then click **Authenticate this email domain**. Someless Mail looks the records up and marks each one found, missing or different; once all five are right, the domain shows as **Authenticated**, and the mail engine starts signing its mail. Someless Mail asks your domain's own name servers (at Namecheap, Cloudflare…), not a DNS cache, so a change shows up as soon as your provider publishes it: usually within minutes, sometimes longer. The page looks again when you open it (if its last look is over a minute old), and **Authenticate this email domain** checks right away.

The page also shows the **MX** record, which sends all new mail for the domain to your server. **Don't add it yet**: receiving mail comes next, so keep your current MX records until then.

### A domain that already has mail

If nothing else uses the domain, a green bar at the top says it's ready to set up. If it already uses a mail service (Zoho Mail, Google Workspace, Microsoft 365, Namecheap Private Email, Brevo…), the records are fitted around it, and a summary at the end of the page names the service and says what to do with its records:

- **SPF:** a domain can have only one SPF record, so the SPF card gives your own record with your server added (like `v=spf1 include:zohomail.com a:mail.example.com ~all`) and says to replace your current one with it; don't add a second one. If the record is near SPF's limit of 10 DNS lookups, your server goes in by its IP address instead.
- **DMARC:** a domain can have only one, so yours stays: the card shows it, marked "Already there".
- **MX:** keep your current MX records until you move the domain's mail here. Then replace them; don't keep both, or some mail would go to the old service and some here.
- **`mail.example.com` in use** (by webmail or an old mail server): your server takes a free name instead, like `mx.example.com`, and every record follows it. Use that name wherever this guide says `mail.example.com`.

The summary's **What to remove** lists the records you won't need, and when to delete each:

- **Now:** what gets in the way, like a second SPF or DMARC record.
- **When your mail moves here:** the old service's MX records, its part of your SPF record, its verification code, its DKIM keys and the names that lead mail apps to it.
- **If you no longer use it:** what's left of services that no longer handle your mail.

Services that only send (Brevo, Mailchimp…) can stay: several services can send for one domain.

## Step 5: Your mail server's certificate

Once your domain is authenticated, its mail name (`mail.example.com`) becomes your mail server's name, and Someless Mail asks [Let's Encrypt](https://letsencrypt.org/) for a free certificate for it, so your apps connect over a trusted, encrypted line. Let's Encrypt checks that the name is yours by visiting it over plain HTTP, on port 80. Pass that visit through to Someless Mail:

**With Nginx Proxy Manager** (Someless Mail on its network, as in Step 3), add a second proxy host:

| Setting | Value |
|---|---|
| Domain names | `mail.example.com` |
| Scheme | `http` |
| Forward hostname | `someless-mail` |
| Forward port | `17081` |
| SSL tab | **None.** Leave SSL off and Force SSL off for this one |

SSL stays off here on purpose: Someless Mail gets this certificate itself, and when Nginx Proxy Manager holds a certificate for a name, it answers Let's Encrypt's visits to that name on its own, so they'd never reach Someless Mail. Port 17081 answers Let's Encrypt's check and nothing else.

**Without a proxy**, and with nothing else on port 80: uncomment the `"80:17081"` line in your `docker-compose.yml` and run `docker compose up -d`.

Then, on **SMTP & API**, click **Check again**: Someless Mail asks Let's Encrypt again straight away, so you don't wait for its next try, which can be hours after a failed check. Let's Encrypt allows only a few failed checks of a name an hour, so **Check again** asks at most every 10 minutes. The certificate usually arrives within a few minutes after that, and Someless Mail renews it by itself. **SMTP & API** shows when it's there (see [Step 8](#step-8-check-ready-to-send)).

**More than one domain?** The mail server has one name. It takes the first authenticated domain's mail name; on **SMTP & API** you can pick another one.

## Step 6: Reverse DNS and port 25

These two are set at your VPS provider, not in Someless Mail. Mail can go out without them, but Gmail and Outlook trust it far less.

- **Reverse DNS (PTR):** the name your server's IP address answers with. Set it to your mail server's name, `mail.example.com`. In your provider's control panel, look for **Reverse DNS** or **PTR** next to your server's IP address; some providers set it from the server's name, or on a support request.
- **Outgoing port 25:** your server hands your mail to Gmail, Outlook and every other mail server on their port 25. Many providers block it on new servers to stop spam. Check from your server:

  ```
  timeout 5 bash -c '</dev/tcp/gmail-smtp-in.l.google.com/25' && echo "port 25 is open" || echo "port 25 is blocked"
  ```

  If it's blocked, ask your provider's support to unblock outgoing port 25 for sending your own domain's mail.

## Step 7: Add a sender

A sender is the name and address your mail comes from, like `Google <no-reply@google.com>`. In **Senders**, click **Add sender**, type the name and the address, and the phone beside the form shows how it will look in an inbox. The address has to be at a domain you've authenticated in **Domains**; for any other domain, authenticate it first and come back. Deleting a domain deletes its senders.

Your apps can send only from the senders on this list: anything else is refused, so a leaked key can't be used to fake your other addresses.

## Step 8: Check Ready to send

The top of **SMTP & API** says whether your server is ready to send, and what's left to do:

| Check | What it means |
|---|---|
| Mail engine running | The mail engine inside the container is up. It restarts by itself if it stops |
| Server name points here | `mail.example.com` has its A record pointing to this server ([Step 4](#step-4-connect-and-authenticate-your-domain)) |
| Certificate | Let's Encrypt's certificate for `mail.example.com` is in ([Step 5](#step-5-your-mail-servers-certificate)) |
| Outgoing port 25 | A warning if your provider blocks it ([Step 6](#step-6-reverse-dns-and-port-25)) |
| Reverse DNS | A warning until your IP answers with `mail.example.com` ([Step 6](#step-6-reverse-dns-and-port-25)) |
| A sender | At least one sender on the list ([Step 7](#step-7-add-a-sender)) |

Once everything but the warnings is ticked, the card glows green: **Ready to send**. After you fix something, click **Check again**.

## Step 9: Send a test email

In **Senders**, click **Send test email** on a sender, and send it to an inbox you can check, like your Gmail. The dialog follows it: **Delivered** (with the server that took it), **Bounced** (with the reason), or **Trying again later**. The sender's card keeps the last result.

In Gmail, open the message, click **⋮ → Show original**, and look for three passes:

```
SPF:   PASS
DKIM:  PASS
DMARC: PASS
```

If one of them fails, check that record on the domain's **Authenticate** page. If the mail landed in spam, a new server often needs a few days of normal sending to build its reputation; reverse DNS ([Step 6](#step-6-reverse-dns-and-port-25)) helps a lot.

## Step 10: Send from your apps and websites

In **SMTP & API**, click **Generate SMTP key**, give it a name (like the app that will use it), and choose:

- **Standard** (64 characters, the safest) or **Short** (15 characters, for apps that take only short passwords)
- when it expires: from 7 days to 1 year, or never

Each key comes with its **own login**, made from its name, like `website-7f3a`. Use them together:

| Setting | Value |
|---|---|
| SMTP server | `mail.example.com` |
| Port | `587` with STARTTLS (or `465` with TLS/SSL) |
| Username | the key's login, like `website-7f3a` |
| Password | the key |

The key is shown only once, so copy it then: Someless Mail keeps only its fingerprint, so a lost key can't be shown again, only replaced. The login stays listed with the key. Delete a key to stop the apps that use it; an expired key stops working by itself.

The round button with the animation beside **Generate SMTP key** opens the guide: a working example for Python, Node.js, PHP, Java, C# and Go, filled in with your settings, and what to type into apps and plugins (WordPress, shops, CRMs…). The examples read the login and the key from the `SOMELESS_SMTP_LOGIN` and `SOMELESS_SMTP_KEY` environment variables, so the key never ends up in your code.

**API keys**, for using Someless Mail from your own code, are coming too.

## Troubleshooting

- **The certificate doesn't arrive.** Check that `mail.example.com` points to your server ([Step 4](#step-4-connect-and-authenticate-your-domain)), that its proxy host forwards to port `17081` with SSL off ([Step 5](#step-5-your-mail-servers-certificate)), and that port 80 is open in your firewall; then click **Check again** on **SMTP & API** (it asks Let's Encrypt at most every 10 minutes). Opening `http://mail.example.com/.well-known/acme-challenge/test` should say *Someless Mail: nothing here but Let's Encrypt's checks.* If you see a page from Nginx Proxy Manager instead, the request isn't reaching Someless Mail.
- **"535 Authentication failed" in an app:** the login or the key is wrong, or the key has expired. Each key has its own login: use the one listed with it.
- **"501 You are not allowed to send from this address":** the app sends from an address that isn't on your **Senders** list. Add it there, or change the app's "from" address.
- **"Connection refused" or a timeout in an app:** ports `587`/`465` aren't open in your firewall, or the network your app runs on blocks them.
- **A test email bounced:** the dialog and the sender's card show the receiving server's reason.
- **The mail engine's state**, from the server:

  ```
  docker exec -u someless someless-mail flask --app someless engine status
  ```

  It prints how far the mail engine's setup got, and when the web interface last brought it up to date. `docker logs someless-mail` shows the rest.

## Ports

Inside the container, Someless Mail uses its own port numbers so it never clashes with other services, and runs as its own user, never as root.

| What it's for | Port inside the container | Port on your server |
|---|---|---|
| Web interface | 17080 | 17080, or none behind a proxy ([Step 3](#step-3-https-for-the-web-interface)) |
| Your apps send mail (STARTTLS) | 17587 | 587 |
| Your apps send mail (TLS from the start) | 17465 | 465 |
| Let's Encrypt's check of your mail server's name | 17081 | none behind a proxy, or 80 ([Step 5](#step-5-your-mail-servers-certificate)) |
| Receiving mail from other servers | — | 25 (coming next) |
| Reading mail in mail apps | — | 993 (coming next) |

Your server also *sends* to other mail servers' port 25; that's outgoing, so nothing to publish, but your provider must allow it ([Step 6](#step-6-reverse-dns-and-port-25)).

## Your data

Everything Someless Mail keeps is in the `data` folder next to your `docker-compose.yml`:

```
your-folder/
├── docker-compose.yml
└── data/
    ├── someless/
    │   ├── someless.db    ← login, settings, domains, senders, SMTP keys (their fingerprints)
    │   └── secret_key     ← signs your login, so it survives restarts
    └── stalwart/          ← the mail engine: its settings, its mail queue, its certificate
```

So the database is at `data/someless/someless.db`.

- **Updates keep it.** `docker compose pull && docker compose up -d` never touches it.
- **Back it up regularly**, both folders together. See [Back up and restore](#back-up-and-restore) below.
- **Don't delete it** unless you want to start over with `admin` / `admin`.
- **No permissions to set up.** Someless Mail runs as its own user (ID 2001), not as root, and takes the folder over by itself when it starts.

### Back up and restore

Run these in the folder with your `docker-compose.yml`.

**Back up:** stop Someless Mail for a moment so nothing changes while you copy, pack the `data` folder into one file, and start it again:

```
docker compose stop
tar czf someless-backup-$(date +%F).tar.gz data
docker compose start
```

You get one file, such as `someless-backup-2026-09-25.tar.gz`, with both the web interface's data and the mail engine's. Keep a copy somewhere other than this server.

**Restore:** stop Someless Mail, put the old `data` folder aside, unpack the backup, and start it again:

```
docker compose stop
mv data data-before-restore
tar xzf someless-backup-2026-09-25.tar.gz
docker compose start
```

Once everything looks right, delete `data-before-restore`.

**Always restore while Someless Mail is stopped, then start it.** Files you copy in as root (with `cp`, or an SFTP app logged in as root) belong to root, and Someless Mail can't write to them, so saving anything would fail. When it starts, it gives every file in `data` that isn't its own back to its user, so after `docker compose start` everything works again. No `chown` needed. If you ever copied files in while it was running, run `docker compose restart`.

### Moving from an older install

Early installs kept the data in a Docker volume instead. To move it into the `data` folder, run this in the folder with your `docker-compose.yml`. Docker names the volume after that folder, so replace `someless_mail` with your folder's name:

```
docker compose down
mkdir -p data
cp -a /var/lib/docker/volumes/someless_mail_someless-data/_data/. data/
```

Then replace your `docker-compose.yml` with the one above and start again with `docker compose pull && docker compose up -d`. Once everything works, remove the old volume: `docker volume rm someless_mail_someless-data`.

## Updating

In the folder with your `docker-compose.yml`:

```
docker compose pull && docker compose up -d
```

## Development

Requires Python 3.12+.

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
SOMELESS_DATA_DIR=./devdata .venv/bin/python -m flask --app app/someless:create_app run --port 17080
```

The tests use a stand-in for the mail engine. To run them against the real one too, point `STALWART_BIN` at a Stalwart v0.16.23 binary (they use ports 17587, 17465 and 17880):

```
STALWART_BIN=/path/to/stalwart .venv/bin/python -m pytest tests/test_engine_live.py
```

The mail engine in the image is built from source by the **Build Stalwart (open source)** workflow (`.github/workflows/stalwart.yml`), for the version in `stalwart/VERSION`, and published as `ghcr.io/boyoftime/someless-stalwart:<version>`. When a push brings a new version (the first push included), both workflows start together; the Rust build takes about an hour, so **Test and publish image** runs its tests, notes that the mail engine isn't built yet, and builds the image by itself once **Build Stalwart (open source)** finishes. To build the image on your own machine, log in first with `docker login ghcr.io`, since the mail engine's image is private to the repository.

## Credits

- Mail engine: [Stalwart](https://github.com/stalwartlabs/stalwart) v0.16.23, built from source without its Enterprise features (AGPL-3.0). Its licence and a link to its source are in the image at `/usr/share/doc/stalwart/`.
- Font: [Google Sans](https://github.com/googlefonts/googlesans), SIL Open Font License 1.1 (`app/someless/static/fonts/OFL.txt`).
- Animation player: [lottie-web](https://github.com/airbnb/lottie-web) 5.13.0 (MIT).
- Login background: [PixiJS](https://github.com/pixijs/pixijs) 8.21.0 (MIT).
- QR codes for two-factor authentication: [segno](https://github.com/heuer/segno) 1.6.6 (BSD-3-Clause).
- DKIM signing keys: [cryptography](https://github.com/pyca/cryptography) 50.0.1 (Apache-2.0 or BSD-3-Clause).
- DNS checks: [dnspython](https://github.com/rthalley/dnspython) 2.8.0 (ISC).
- Programming language logos in the SMTP guide: [Devicon](https://github.com/devicons/devicon) 2.16.0 (MIT). The logos belong to their owners.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.png">
    <img src="docs/banner-light.png" alt="Someless Mail Server" width="720">
  </picture>
</p>

<h3 align="center">The powerful mail server for businesses and enterprises, on your own server.</h3>

Welcome to **Someless Mail Server**: your own mail server in a single Docker image. Install it on your server, open the web interface, connect your domain, send email from your apps and websites through your own server, signed and trusted like mail from the big providers, and receive it in your own mailboxes. No monthly fee per user, no one else holding your company's mail: just your server, your domains and your rules.

**Version:** 1.0.0

> **Status:** sending and receiving work. Connect and authenticate your domain, add the addresses your mail comes from, create mailboxes, and read them in any mail app. The webmail's sign-in works; its inbox comes next.

## Why Someless Mail

Hosted suites charge for every user, every month, and keep your mail on their servers. Classic mail servers take days of setup across many separate programs. Someless Mail is one install, with a panel that does the hard parts for you:

- **Your mail, your server.** Every message and mailbox stays on your own server. Nobody else keeps it or reads it.
- **No fee per mailbox.** Create as many mailboxes, aliases and domains as your server holds, for a team of five or five thousand.
- **Trusted delivery.** Every message is signed with DKIM, with SPF and DMARC in place, so it lands like mail from the big providers.
- **DNS made simple.** The panel shows the exact records for your provider, checks them for you, and can hand them over as a file or a link for your developer.
- **Built for your apps.** Websites and apps send through SMTP keys of their own, with expiry dates, apart from your team's mailboxes.
- **On every device.** IMAP, POP3 and SMTP for any mail app, with quick setup for Android, iPhone and Windows.
- **Secure by design.** Two-factor sign-in for the web interface, a lock after wrong passwords in the webmail, and encrypted connections for every mail app.
- **A modern engine.** Built on [Stalwart](https://github.com/stalwartlabs/stalwart), a fast, secure mail engine written in Rust, in a single Docker image you update with one command.

Try it now: it takes minutes to install, and your first message goes out as soon as your domain is authenticated.

This guide takes you from installing to your first email landing in a Gmail inbox, and your first reply landing in your own mailbox. Follow the steps in order; each one takes a few minutes, apart from waiting for DNS changes to show up.

## How it fits together

- **The web interface** (port 17080) is where you set everything up: domains, senders, SMTP keys.
- **The mail engine**, [Stalwart](https://github.com/stalwartlabs/stalwart), runs in the same container: it sends the mail, receives it into your mailboxes, and serves your mail apps. You never set it up yourself: the web interface does it for you.
- **The webmail** (port 17090) is where the people with a mailbox sign in with its address and password.
- **[Nginx Proxy Manager](https://nginxproxymanager.com/)** (optional, recommended) puts the web interface on HTTPS, and passes Let's Encrypt's check through to the mail engine so your mail server gets its own certificate.

## What you need

- **A Linux server (VPS)** with [Docker](https://docs.docker.com/engine/install/) and a fixed public IP address.
- **A domain you own**, like `example.com`, and access to its DNS settings at your domain provider (Namecheap, Cloudflare, GoDaddy…).
- **Port 25 open at your provider,** both ways. Mail servers deliver to each other on port 25: your server sends out on it, and receives your mail on it. Many VPS providers block outgoing port 25 until you ask. See [Step 6](#step-6-reverse-dns-and-port-25).
- **Recommended:** Nginx Proxy Manager on the same server, for HTTPS.

## The names you'll use

These names come up in this guide. With the domain `example.com`:

| Name | Example | What it's for |
|---|---|---|
| Your mail domain | `example.com` | The part of your addresses after the @, like `no-reply@example.com` or `ceo@example.com` |
| Your mail server's name | `mail.example.com` | What your apps connect to, what your server's certificate is for, and what other mail servers see. Someless Mail gives you its record in [Step 4](#step-4-connect-and-authenticate-your-domain) |
| The web interface's name (optional) | `panel.example.com` | Opening the web interface over HTTPS, in [Step 3](#step-3-https-for-the-web-interface) |
| The webmail's name (optional) | `webmail.example.com` | Opening the webmail over HTTPS, in [Step 12](#step-12-the-webmail) |

Keep the web interface and the mail server on **different names**. `mail.example.com` belongs to the mail server: its certificate depends on it (see [Step 5](#step-5-your-mail-servers-certificate)).

## Step 1: Install

Someless Mail keeps all your data in a `data` folder right where you install it, so it's easy to find and back up, and it survives updates and restarts (see [Your data](#your-data)).

First make sure the ports are free on your server. This should print nothing:

```
sudo ss -tulpn | grep -E ':(25|587|465|993|995|17080|17081|17090) '
```

Create a folder, and save this as `docker-compose.yml` inside it (the same file is in this repository). It's the only one you need, with or without Nginx Proxy Manager; its comments say what to change later:

```yaml
services:
  someless-mail:
    image: ghcr.io/boyoftime/someless-mail:1.0.0
    container_name: someless-mail
    restart: unless-stopped
    ports:
      # Mail: always open, since mail doesn't go through a web proxy
      - "25:25"         # other mail servers deliver your mail here
      - "587:17587"     # your apps send mail here (STARTTLS)
      - "465:17465"     # your apps send mail here (TLS from the start)
      - "993:17993"     # mail apps read your mail here (IMAP)
      - "995:17995"     # mail apps read your mail here (POP3)
      # The web interface and the webmail by IP: http://your-server-ip:17080 and :17090.
      # Once Nginx Proxy Manager serves them on HTTPS (Steps 3 and 12), put a # at the start of
      # these two lines and run docker compose up -d again: then they open only through it.
      - "17080:17080"   # web interface
      - "17090:17090"   # webmail
      # Using Nginx Proxy Manager? Leave the next line as it is, with its #: Nginx Proxy Manager
      # passes Let's Encrypt's check on for you (Step 5). Only with no proxy at all, remove the #.
      # - "80:17081"
    expose:             # what Nginx Proxy Manager reaches, over the nginx-proxy network
      - "17080"         # web interface (Step 3)
      - "17090"         # webmail (Step 12)
      - "17081"         # Let's Encrypt's check of your mail server's name (Step 5)
    sysctls:
      - net.ipv4.ip_unprivileged_port_start=0   # the mail engine doesn't run as root, and takes port 25
    volumes:
      - ./data:/data    # all your data, in a "data" folder next to this file
    networks:
      - nginx-proxy

networks:
  nginx-proxy:          # Nginx Proxy Manager's network (Step 1 makes it if it isn't there yet)
    external: true
```

Someless Mail joins Nginx Proxy Manager's Docker network, `nginx-proxy`, so the proxy can reach it later ([Step 3](#step-3-https-for-the-web-interface)). This makes the network if it isn't there yet, and does nothing if it is:

```
docker network inspect nginx-proxy >/dev/null 2>&1 || docker network create nginx-proxy
```

Then start Someless Mail from the folder with `docker-compose.yml`:

```
docker compose up -d
```

The `data` folder appears next to `docker-compose.yml` on the first start.

The `sysctls` line lets the mail engine take port 25 inside the container: it doesn't run as root, and ports below 1024 are normally for root. It's Docker's own default since version 20.10, written out so it holds everywhere.

### Open your firewall

If your server has a firewall, allow inbound TCP `25` (your mail comes in there), `587` and `465` (your apps send mail there), `993` and `995` (mail apps read mail there), and `17080` and `17090` if you open the web interface and the webmail by IP. With `ufw`:

```
sudo ufw allow 25/tcp && sudo ufw allow 587/tcp && sudo ufw allow 465/tcp
sudo ufw allow 993/tcp && sudo ufw allow 995/tcp
sudo ufw allow 17080/tcp && sudo ufw allow 17090/tcp
```

### Open it

Go to `http://your-server-ip:17080` in your browser. You'll see a short welcome animation, then the login page (your password is in [Step 2](#step-2-log-in-and-lock-it-down)). On the very first start, it says **Preparing your Someless Mail server** for up to a minute while it sets its mail engine up, then moves on by itself.

## Step 2: Log in and lock it down

The username is `admin`. The password is made at random on the very first start, just for your server, so nobody can guess it. It's printed in the container's logs, and this shows it again, on your server:

```
docker exec -u someless someless-mail flask --app someless initial-password
```

Change it to one of your own right after your first login, in **Settings**: from then on, that command no longer shows it, and the dashboard stops reminding you. Forgot your password later? This makes a new one, shown the same way:

```
docker exec -u someless someless-mail flask --app someless reset-password
```

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

2. **In Nginx Proxy Manager**, add a proxy host (Someless Mail is on its network already, from [Step 1](#step-1-install)):

   | Setting | Value |
   |---|---|
   | Domain names | `panel.example.com` |
   | Scheme | `http` |
   | Forward hostname | `someless-mail` |
   | Forward port | `17080` |
   | SSL tab | Request a new SSL certificate, with **Force SSL** and **HTTP/2** on |

3. Open `https://panel.example.com` and log in.

4. **Close the way in by IP.** In `docker-compose.yml`, put a `#` at the start of the `"17080:17080"` line, then run `docker compose up -d`. The web interface now opens only at `https://panel.example.com`. If you opened port 17080 in your firewall, close it again: `sudo ufw delete allow 17080/tcp`.

## Step 4: Connect and authenticate your domain

In **Domains**, click **Add domain** and type the part of your email address after the @ (like `example.com`). Then click **Authenticate** next to it. The page lists the DNS records to add at your domain provider, each with copy buttons:

| Record | What it does |
|---|---|
| Someless code (TXT) | Shows that the domain is yours |
| A (host `mail`) | Points your mail server's name, `mail.example.com`, at your server |
| SPF (TXT) | Lets your server send the domain's mail |
| DKIM (TXT) | Signs your mail so nobody can fake it. The private key never leaves your server (it's in `data/`) |
| DMARC (TXT) | Tells other mail servers what to do with mail that fails these checks |
| MX | Sends the domain's incoming mail to your server, into its mailboxes ([Step 11](#step-11-mailboxes-receive-mail)) |

Add them all, then click **Authenticate this email domain**. Someless Mail looks the records up and marks each one found, missing or different; once all six are right, the domain shows as **Authenticated**, and the mail engine starts signing its mail. Someless Mail asks your domain's own name servers (at Namecheap, Cloudflare…), not a DNS cache, so a change shows up as soon as your provider publishes it: usually within minutes, sometimes longer. The page looks again when you open it (if its last look is over a minute old), and **Authenticate this email domain** checks right away.

The **MX** record is needed too: a domain is authenticated once its mail comes to your server. From then on, all new mail for the domain comes here, so create its mailboxes right after ([Step 11](#step-11-mailboxes-receive-mail)): mail to an address without one is refused.

### Add them all at once

Some DNS providers can import records from a file. Click **Download zone file** at the top of the domain's **Authenticate** page for all six in one file. At Cloudflare, open the domain, then **DNS → Records → Import and Export**, upload the file, and leave **Proxy imported DNS records** off: mail doesn't go through Cloudflare's proxy. A record the domain has already is left out of the file, and so is one to change by hand: if the domain has an SPF record of its own, edit it to the one on the page, since a domain can have only one.

### Someone else looks after the DNS?

Click **Need help?** at the bottom of the domain's **Authenticate** page, and make a link to send to your developer or IT. It opens a page of its own, on your web interface's address, with no login: the records, how to add them at your DNS provider (or all at once, with the zone file), and an **Authenticate** button. You choose when the link expires (1 hour to 30 days, or never) and whether it asks for a password. The dialog shows whether each link was opened, and you can delete one at any time. Once its check finds all six records right, the domain is authenticated and the link closes.

### A domain that already has mail

If nothing else uses the domain, a green bar at the top says it's ready to set up. If it already uses a mail service (Zoho Mail, Google Workspace, Microsoft 365, Namecheap Private Email, Brevo…), the records are fitted around it, and a summary at the end of the page names the service and says what to do with its records:

- **SPF:** a domain can have only one SPF record, so the SPF card gives your own record with your server added (like `v=spf1 include:zohomail.com a:mail.example.com ~all`) and says to replace your current one with it; don't add a second one. If the record is near SPF's limit of 10 DNS lookups, your server goes in by its IP address instead.
- **DMARC:** a domain can have only one, so yours stays: the card shows it, marked "Already there".
- **MX:** replace your current MX records with this one: the domain is authenticated only once its mail comes here. Don't keep both, or some mail would go to the old service and some here. Moving from a service with mail in it? Copy that mail out first (its export, or your mail app), since new mail arrives here from then on.
- **`mail.example.com` in use** (by webmail or an old mail server): your server takes a free name instead, like `mx.example.com`, and every record follows it. Use that name wherever this guide says `mail.example.com`.

The summary's **What to remove** lists the records you won't need, and when to delete each:

- **Now:** what gets in the way, like a second SPF or DMARC record.
- **When your mail moves here:** the old service's MX records, its part of your SPF record, its verification code, its DKIM keys and the names that lead mail apps to it.
- **If you no longer use it:** what's left of services that no longer handle your mail.

Services that only send (Brevo, Mailchimp…) can stay: several services can send for one domain.

## Step 5: Your mail server's certificate

Once your domain is authenticated, its mail name (`mail.example.com`) becomes your mail server's name, and Someless Mail asks [Let's Encrypt](https://letsencrypt.org/) for a free certificate for it, so your apps connect over a trusted, encrypted line. Let's Encrypt checks that the name is yours by visiting it over plain HTTP, on port 80. Pass that visit through to Someless Mail:

**With Nginx Proxy Manager** (Someless Mail is on its network already), add a second proxy host:

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

**More than one domain?** The mail server has one name, whichever domain your mail comes from. It takes the first authenticated domain's mail name; choose another one in **Settings → Mail server name**. That page also shows what the name needs (its A record, the proxy host, reverse DNS and the certificate) and how each stands.

## Step 6: Reverse DNS and port 25

These two are set at your VPS provider, not in Someless Mail. Mail can go out without them, but Gmail and Outlook trust it far less.

- **Reverse DNS (PTR):** the name your server's IP address answers with. Set it to your mail server's name, `mail.example.com`. In your provider's control panel, look for **Reverse DNS** or **PTR** next to your server's IP address; some providers set it from the server's name, or on a support request.
- **Outgoing port 25:** your server hands your mail to Gmail, Outlook and every other mail server on their port 25. Many providers block it on new servers to stop spam. Check from your server:

  ```
  timeout 5 bash -c '</dev/tcp/gmail-smtp-in.l.google.com/25' && echo "port 25 is open" || echo "port 25 is blocked"
  ```

  If it's blocked, ask your provider's support to unblock outgoing port 25 for sending your own domain's mail.

## Step 7: Add a sender

A sender is the name and address your mail comes from, like `Google <no-reply@google.com>`. In **Senders**, click **Add sender**, type the name and the address, and the phone beside the form shows how it will look in an inbox. The address has to be at a domain you've authenticated in **Domains**; for any other domain, authenticate it first and come back. Deleting a domain deletes its senders; a domain with mailboxes can't be deleted until its mailboxes are.

Your apps can send only from the senders on this list: anything else is refused, so a leaked key can't be used to fake your other addresses.

## Step 8: Check Ready to send

The top of **SMTP & API** says whether your server is ready to send, and what's left to do:

| Check | What it means |
|---|---|
| Mail engine running | The mail engine inside the container is up. It restarts by itself if it stops |
| Server name points here | `mail.example.com` has its A record pointing to this server ([Step 4](#step-4-connect-and-authenticate-your-domain)) |
| Certificate | Let's Encrypt's certificate for `mail.example.com` is in ([Step 5](#step-5-your-mail-servers-certificate)) |
| Outgoing port 25 | A warning if your provider blocks it ([Step 6](#step-6-reverse-dns-and-port-25)) |
| Incoming port 25 | A warning until other mail servers can reach port 25 here, to deliver your mail ([Step 11](#step-11-mailboxes-receive-mail)) |
| IMAP port 993, POP3 port 995 | Warnings until mail apps can reach them. Each warning says what to add to `docker-compose.yml` and to your firewall |
| Reverse DNS | A warning until your IP answers with `mail.example.com` ([Step 6](#step-6-reverse-dns-and-port-25)) |
| A sender | At least one sender on the list ([Step 7](#step-7-add-a-sender)) |

Once everything but the warnings is ticked, the card glows green: **Ready to send**. After you fix something, click **Check again**. The incoming ports are checked from your server itself, by your mail server's name, the way the world reaches them; a firewall at your VPS provider can still block them from outside.

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

## Step 11: Mailboxes: receive mail

A mailbox is an inbox at one of your domains, like `ceo@example.com`. In **Mailboxes**, click **Create mailbox**:

- **Email address:** type the part before the @ and pick the domain: one you've authenticated.
- **Password and Confirm password:** it follows your password rules (**Settings → Password rules**). Someless Mail keeps only a fingerprint of it, like your own.
- **Mailbox storage:** how much mail it can hold, in GB or MB. New mail is refused once it's full. The dialog shows how much room your server has.

Each mailbox's card shows how much of its storage is used, and has buttons to open its webmail (in a new tab, already signed in: no password asked), to change its password or storage, to delete it (with all its mail), and:

- **Aliases:** other addresses whose mail lands in this mailbox, like `hello@example.com` or `sales@example.com`, at any of your authenticated domains. Add as many as you like.
- **Configuration details:** what to type in a mail app (Outlook, Apple Mail, Thunderbird, the mail app on your phone), each with a copy button:

  | Setting | Value |
  |---|---|
  | Username | the mailbox's address, like `ceo@example.com` |
  | Password | the mailbox's password |
  | Incoming (IMAP) | `mail.example.com`, port `993`, SSL/TLS |
  | Incoming (POP3) | `mail.example.com`, port `995`, SSL/TLS |
  | Outgoing (SMTP) | `mail.example.com`, port `465` with SSL/TLS, or `587` with STARTTLS |

  Click the phone at the top right of **Configuration details**, and the card turns over to **Set it up on a device**: step by step for the Gmail app on Android, for an iPhone, and for Outlook on Windows. The iPhone gets a configuration profile that sets up its Mail app: scan the QR code with the iPhone's camera (the link works for an hour), or download the profile and send it to the iPhone. It asks for the mailbox's password while it's installed, and it works on a Mac too.

The domain's **MX** record, added when you authenticated it ([Step 4](#step-4-connect-and-authenticate-your-domain)), already sends its mail here. If it ever points elsewhere, the Mailboxes page says so, and the domain is no longer authenticated. Mail to an address at the domain that isn't a mailbox or an alias is refused.

To try it, send a message from your Gmail to the new mailbox, and open it in your mail app. A message from an unknown sender can land in **Junk Mail** at first: mark it as not junk.

## Step 12: The webmail

The people with a mailbox sign in at `http://your-server-ip:17090` with the mailbox's address and password. After 5 wrong passwords in a row, the address can't sign in for 5 minutes; choose other numbers in **Settings → Miscellaneous → Webmail sign-in lock**. The inbox itself is coming soon; until then, the page shows the mail app settings from [Step 11](#step-11-mailboxes-receive-mail).

**On HTTPS, at `webmail.example.com`:** add an A record `webmail` pointing to your server's IP address, then a proxy host in Nginx Proxy Manager:

| Setting | Value |
|---|---|
| Domain names | `webmail.example.com` |
| Scheme | `http` |
| Forward hostname | `someless-mail` |
| Forward port | `17090` |
| SSL tab | Request a new SSL certificate, with **Force SSL** and **HTTP/2** on |

Then, in **Settings → Miscellaneous → Webmail address**, type `https://webmail.example.com`, so the Mailboxes page opens the webmail there. And close the way in by IP: in `docker-compose.yml`, put a `#` at the start of the `"17090:17090"` line and run `docker compose up -d` (and `sudo ufw delete allow 17090/tcp` if you opened it).

Signing in to the webmail and to the web interface are separate: a mailbox's password never opens the web interface.

## Troubleshooting

- **The certificate doesn't arrive.** Check that `mail.example.com` points to your server ([Step 4](#step-4-connect-and-authenticate-your-domain)), that its proxy host forwards to port `17081` with SSL off ([Step 5](#step-5-your-mail-servers-certificate)), and that port 80 is open in your firewall; then click **Check again** on **SMTP & API** (it asks Let's Encrypt at most every 10 minutes). Opening `http://mail.example.com/.well-known/acme-challenge/test` should say *Someless Mail: nothing here but Let's Encrypt's checks.* If you see a page from Nginx Proxy Manager instead, the request isn't reaching Someless Mail.
- **"535 Authentication failed" in an app:** the login or the key is wrong, or the key has expired. Each key has its own login: use the one listed with it.
- **"501 You are not allowed to send from this address":** the app sends from an address that isn't on your **Senders** list. Add it there, or change the app's "from" address.
- **"Connection refused" or a timeout in an app:** ports `587`/`465` aren't open in your firewall, or the network your app runs on blocks them.
- **A test email bounced:** the dialog and the sender's card show the receiving server's reason.
- **Mail doesn't arrive in a mailbox.** Check that the domain's MX record points to `mail.example.com` (the Mailboxes page says when it doesn't), that port `25` is open in your firewall, and that the address is a mailbox or an alias of one. Look in the mailbox's **Junk Mail** folder too. From another server, `timeout 5 bash -c '</dev/tcp/mail.example.com/25' && echo open` should print *open*.
- **A mail app can't connect:** ports `993`/`995` (reading) or `465`/`587` (sending) aren't open in your firewall, or the username isn't the whole address, like `ceo@example.com`.
- **The mail engine's state**, from the server:

  ```
  docker exec -u someless someless-mail flask --app someless engine status
  ```

  It prints how far the mail engine's setup got, and when the web interface last brought it up to date. `docker logs someless-mail` shows the rest.

## Ports

Inside the container, Someless Mail uses its own port numbers so it never clashes with other services, and runs as its own user, never as root. Receiving is the one exception: other mail servers deliver to port 25 and nowhere else.

| What it's for | Port inside the container | Port on your server |
|---|---|---|
| Web interface | 17080 | 17080, or none behind a proxy ([Step 3](#step-3-https-for-the-web-interface)) |
| Webmail | 17090 | 17090, or none behind a proxy ([Step 12](#step-12-the-webmail)) |
| Receiving mail from other servers | 25 | 25 |
| Your apps and mail apps send mail (STARTTLS) | 17587 | 587 |
| Your apps and mail apps send mail (TLS from the start) | 17465 | 465 |
| Mail apps read mail (IMAP) | 17993 | 993 |
| Mail apps read mail (POP3) | 17995 | 995 |
| Let's Encrypt's check of your mail server's name | 17081 | none behind a proxy, or 80 ([Step 5](#step-5-your-mail-servers-certificate)) |

Your server also *sends* to other mail servers' port 25; that's outgoing, so nothing to publish, but your provider must allow it ([Step 6](#step-6-reverse-dns-and-port-25)).

## Your data

Everything Someless Mail keeps is in the `data` folder next to your `docker-compose.yml`:

```
your-folder/
├── docker-compose.yml
└── data/
    ├── someless/
    │   ├── someless.db    ← login, settings, domains, senders, mailboxes, SMTP keys (their fingerprints)
    │   ├── secret_key     ← signs your login, so it survives restarts
    │   ├── webmail_secret_key  ← the same, for the webmail
    │   ├── initial_password    ← your first password, until you change it (Step 2)
    │   └── avatar.webp         ← your profile picture, if you set one
    └── stalwart/          ← the mail engine: its settings, the mail in your mailboxes, its queue, its certificate
```

So the database is at `data/someless/someless.db`.

- **Updates keep it.** `docker compose pull && docker compose up -d` never touches it.
- **Back it up regularly**, both folders together. See [Back up and restore](#back-up-and-restore) below.
- **Don't delete it** unless you want to start over (with a new first password, [Step 2](#step-2-log-in-and-lock-it-down)).
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
SOMELESS_DATA_DIR=./devdata .venv/bin/python -m flask --app "app/someless.webmail:create_webmail_app" run --port 17090
```

The tests use a stand-in for the mail engine. To run them against the real one too, point `STALWART_BIN` at a Stalwart v0.16.23 binary (they use ports 25, 17587, 17465, 17993, 17995 and 17880):

```
STALWART_BIN=/path/to/stalwart .venv/bin/python -m pytest tests/test_engine_live.py
```

The mail engine in the image is built from source by the **Build Stalwart (open source)** workflow (`.github/workflows/stalwart.yml`), for the version in `stalwart/VERSION`, and published as `ghcr.io/boyoftime/someless-stalwart:<version>`. When a push brings a new version (the first push included), both workflows start together; the Rust build takes about an hour, so **Test and publish image** runs its tests, notes that the mail engine isn't built yet, and builds the image by itself once **Build Stalwart (open source)** finishes. To build the image on your own machine, log in first with `docker login ghcr.io`, since the mail engine's image is private to the repository.

## Credits

<p align="center">
  <img src="docs/images/someless-tricks.png" alt="Someless Tricks" width="420">
</p>

All the credit goes to **Someless Tricks**, who brought this mail server to life.

<p align="center">
  <img src="docs/images/someless.png" alt="Someless" width="180">
</p>

<p align="center"><b>Someless</b><br>Web developer, and the maker of Someless Mail</p>

> *"Every business deserves mail it truly owns: fast, trusted and private, on its own server. That's why I built Someless Mail."*

I've been a web developer for more than three years. I build my tools with the help of AI, to move faster as technology grows day by day, and Someless Mail is the biggest of them yet.

It was never easy to make. A mail server has to get countless small things right before the rest of the internet trusts it, and Someless Mail brings them all together: a mail engine built from source, DNS checks that know how each provider works, a signing key for every domain, mailboxes and aliases, the webmail, two-factor sign-in, and a web interface that makes all of it simple. Every piece was built, tested, and built again, over many long nights, until it felt effortless to use. And it isn't finished: more updates will keep coming to make it even more powerful.

Thanks to the **Stalwart team**: their open-source mail engine is the heart of Someless Mail. Thank you for building it in the open.

### Support Someless Mail

Your donation is what lets me keep building, and keep making this tool better with every update. Together, we build a community.

<p align="center"><a href="https://nowpayments.io/donation/someless"><b>❤ Donate to Someless Mail</b></a></p>

The same thanks, and the donate button, are in the web interface too: **Credits**, at the end of the menu.

### Open-source software it's built with

- Mail engine: [Stalwart](https://github.com/stalwartlabs/stalwart) v0.16.23, built from source without its Enterprise features (AGPL-3.0). Its licence and a link to its source are in the image at `/usr/share/doc/stalwart/`.
- Profile pictures: [Pillow](https://github.com/python-pillow/Pillow) 12.3.0 (MIT-CMU).
- Font: [Google Sans](https://github.com/googlefonts/googlesans), SIL Open Font License 1.1 (`app/someless/static/fonts/OFL.txt`).
- Animation player: [lottie-web](https://github.com/airbnb/lottie-web) 5.13.0 (MIT).
- Login background: [PixiJS](https://github.com/pixijs/pixijs) 8.21.0 (MIT).
- QR codes for two-factor authentication: [segno](https://github.com/heuer/segno) 1.6.6 (BSD-3-Clause).
- DKIM signing keys: [cryptography](https://github.com/pyca/cryptography) 50.0.1 (Apache-2.0 or BSD-3-Clause).
- DNS checks: [dnspython](https://github.com/rthalley/dnspython) 2.8.0 (ISC).
- Programming language logos in the SMTP guide: [Devicon](https://github.com/devicons/devicon) 2.16.0 (MIT). The logos belong to their owners.
- Android, Apple and Windows logos in the device setup: [Iconify's "logos"](https://github.com/gilbarbara/logos) and [Simple Icons](https://github.com/simple-icons/simple-icons) sets (CC0). The logos belong to their owners.
- iPhone setup QR codes: [segno](https://github.com/heuer/segno), as above; the phone animation is from [LottieFiles](https://lottiefiles.com/).

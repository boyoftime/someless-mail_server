# Mailboxes, receiving and webmail — design

Approved by the user on 2026-09-27 ("build"): Part 1 = receiving, the Mailboxes page (create,
storage, password, unlimited aliases, delete, configuration details) and mail apps over IMAP/POP3;
Part 2 = webmail on its own port (17090) with its own login, showing "coming soon" after login.

## Verified on Stalwart v0.16.23 (spike, 2026-09-27)
- Listeners made in normal mode bind after a restart. Inbound SMTP must be on port **25 inside the
  container**: Stalwart's defaults treat local port 25 as inbound (no login asked, SPF/DKIM/DMARC
  checked, Received headers) and every other port as submission.
- A mailbox is a `User` account in its own domain: `name` = the part before the @, `quotas.maxDiskQuota`
  = bytes, `aliases` = `{"0": {"name", "domainId", "enabled"}}`, credential secret = a PHC
  `$pbkdf2-sha256$i=…,l=32$salt$hash` string (Stalwart verifies it; the panel never hands over a
  plain password). `usedDiskQuota` gives the use. Login name for IMAP/POP3/SMTP: the full address.
- Mail to a mailbox or an alias is accepted on 25; unknown addresses get 550, relaying 550.
- IMAP (implicit TLS, 17993) and POP3 (implicit TLS, 17995) work. Folders: INBOX, Sent Items,
  Drafts, Junk Mail, Deleted Items. The spam filter is on by default.
- **Senders without a group**: `x:MtaStageAuth.mustMatchSender` =
  `{"match": {"0": {"if": "sender == 'a@x' || …", "then": "false"}}, "else": "true"}` lets any
  logged-in account send as a Sender, and otherwise only as its own address and aliases. This
  replaces the `someless-senders` group, so an address can be both a Sender and a mailbox.

## Engine (sync, setup)
- Listeners: `smtp` [::]:25, `imaps` [::]:17993 (tlsImplicit), `pop3s` [::]:17995 (tlsImplicit), next
  to the existing ones. New installs make them in recovery mode; existing installs get the missing
  ones at start (normal mode) and Stalwart restarts once.
- Engine domains = authenticated domains ∪ the domains of existing mailboxes: a domain with mailboxes
  is never destroyed (that would lose mail), even when it loses authentication.
- Accounts outside someless.internal are mailboxes: made, updated (quota, aliases, password when
  changed) and destroyed (when deleted in the panel) by the sync.
- The `someless-senders` group goes; key and panel accounts leave it; the send-as rule lists the
  Senders (an address with a quote or backslash is left out of the rule, and logged).

## Panel
- Tables `mailboxes` (email, domain, quota bytes, password hash (the same PHC string), whether the
  engine still needs the password) and `mailbox_aliases`. Addresses unique across both.
- Side menu **Mailboxes** (after Senders). **Create mailbox**: the part before the @ + a list of
  authenticated domains, password + confirm (the admin's password rules), storage + GB/MB.
- Each mailbox: address, aliases, storage bar ("0.9% used, 14.87 GB available"); **Configuration
  details** (IMAP 993 SSL, SMTP 465 SSL or 587 STARTTLS, POP3 995 SSL, server = the mail server
  name, username = the address, with copy buttons), **Manage aliases** (unlimited, any
  authenticated domain), **Edit storage**, **Change password**, **Delete** (asks first: its mail goes).
- A domain with mailboxes can't be deleted until they are.
- The Authenticate page's MX card now says to add it when ready to receive here.

## Webmail (port 17090)
- Its own Flask app in the same image (`create_webmail_app`), its own gunicorn, its own session
  cookie. Login with the mailbox address and password, checked against the panel's hash (Stalwart
  isn't asked, so failed logins can't get 127.0.0.1 banned there); 5 failures in a row lock that
  address for 5 minutes. After login: "Your inbox is coming soon", the mail app settings meanwhile,
  and Log out.

## Container
- Ports: 25 (inbound), 993→17993, 995→17995, 17090 (webmail). The engine binary gets
  `cap_net_bind_service` (Docker ≥20.10 allows low ports anyway).
- README: receiving (MX, port 25 inbound), mail apps, webmail behind Nginx Proxy Manager
  (`webmail.example.com` → someless-mail:17090, SSL on).

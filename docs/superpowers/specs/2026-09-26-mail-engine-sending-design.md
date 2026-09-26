# Mail engine, step 1: sending

Date: 2026-09-26
Status: design approved in conversation; this spec is waiting for review
Version: stays 1.0.0 (no version change in this work)

## Goal

Someless Mail gets its mail engine, Stalwart, so that the admin's apps and websites can
send real mail through the server, and the admin can prove it works with a test email.
Receiving mail comes in a later step.

**Success looks like this:** an app on any machine follows the SMTP guide with one of the
admin's SMTP keys, sends from a Sender on the list, and the message arrives in a Gmail
inbox (not spam). The message headers show DKIM pass, SPF pass and DMARC pass.

## Decisions made with the admin

| Question | Decision |
|---|---|
| What "sending" covers now | Apps send with SMTP keys; the panel has a "Send a test email" action. Receiving comes next. |
| How the engine ships | Inside the same image: one container, same one-line `docker run`. |
| TLS certificate for 587/465 | Let's Encrypt by HTTP-01 over port 80: a proxy host in Nginx Proxy Manager, or `-p 80:17081` without a proxy. |
| Which "From" addresses a key may use | Only the addresses on the Senders page. |
| How panel and engine work together | Approach A: the panel keeps everything and pushes it to Stalwart through its management API. |
| Where the Stalwart program comes from | Our own build of the open-source code, without the Enterprise parts. |

## What the research established (Stalwart v0.16.23, released 2026-09-21)

Sources: the stalw.art docs and the stalwartlabs/stalwart source at v0.16.23 / main.

**Program and first start**
- The binary is `stalwart`, run as `stalwart --config <path>/config.json`. `config.json` holds only the data store (RocksDB path); everything else lives in the database.
- With no `config.json`, it starts in bootstrap mode: HTTP only (port set with `STALWART_RECOVERY_MODE_PORT`), and only the `Bootstrap` object is writable.
- `STALWART_RECOVERY_ADMIN=admin:<password>` pins the admin login. `x:Bootstrap/set` (with `serverHostname`, `defaultDomain`, `requestTlsCertificate: false`, `generateDkimKeys: false`) writes `config.json` and creates the admin account. The process must then be restarted.
- On the first normal start with no listeners, Stalwart creates defaults on ports 25/465/993/995/4190/443/8080. There is no 587 by default.

**Management API**
- `POST /jmap/` with `Authorization: Bearer <api key>` (or Basic). The body is a JMAP request using `urn:ietf:params:jmap:core` and `urn:stalwart:jmap`, with methods like `x:Domain/set`. Sets are encoded as objects, e.g. `{"[::]:587": true}`.
- API keys: `x:ApiKey/set` create; the secret is returned once.
- Applying changes: `x:Action` `ReloadSettings`, `ReloadTlsCertificates`. A new listening port probably needs a process restart.

**DKIM**
- `x:DkimSignature/set` with `@type: Dkim1RsaSha256`, `domainId`, `selector`, and `privateKey: {"@type": "Text", "secret": "<PEM>"}` imports our existing PKCS#8 keys.
- The domain's `dkimManagement` stays `Manual`.
- Signing happens when the sender's domain is a Stalwart domain and the session is authenticated.

**Accounts and passwords**
- `x:Account/set` creates a `User` with a `Password` credential. A secret starting with `{` or `$` that is a recognised hash is stored as-is.
- `{SHA256}` means standard base64, with padding, of the raw 32-byte digest.
- Only one password per account; app passwords can't be set from outside. **One Stalwart account per SMTP key.**

**Restricting senders**
- `MtaStageAuth.mustMatchSender` (on by default) makes the envelope MAIL FROM equal the account's address, one of its aliases, or an address of a group it's in. Otherwise: `501 5.5.4 You are not allowed to send from this address.`

**Certificates (ACME)**
- `AcmeProvider` with `challengeType: Http01`. Its default is TlsAlpn01, so it must be set explicitly.
- `Domain.certificateManagement` set to `Automatic` with `acmeProviderId` and explicit `subjectAlternativeNames`.
- Any HTTP listener serves `/.well-known/acme-challenge/<token>`.
- Clients without SNI get `SystemSettings.defaultCertificateId`.

**Delivery results**
- Messages leave the queue once final, so polling can't tell delivered from bounced.
- The `WebHook` object (not Enterprise-gated) reports events such as `delivery.delivered`, `delivery.dsn-perm-fail`, `delivery.rcpt-to-rejected` and `delivery.completed`.
- The SMTP DATA reply carries the queue id: `250 2.0.0 Message queued with id <hex>.`

**Licence**
- Dual-licensed `AGPL-3.0-only OR LicenseRef-SEL`. Official binaries include Enterprise (SEL) code, so we build without the `enterprise` feature.
- Redistributing the unmodified AGPL build means shipping its licence, notices, and access to the exact corresponding source.

## 1. Packaging, processes and ports

### Building Stalwart

- **A new workflow,** `.github/workflows/stalwart.yml`, builds Stalwart from its source at the tag pinned in `stalwart/VERSION` (`v0.16.23`).
  - It uses the default feature set, never `enterprise`.
  - It builds on Debian trixie, like our base image, so the binary's glibc needs are met.
  - It runs by hand (`workflow_dispatch`) and when `stalwart/VERSION` changes.
- **The build's image,** `ghcr.io/boyoftime/someless-stalwart:<version>`, holds:
  - `/usr/local/bin/stalwart`
  - `/usr/share/doc/stalwart/`: the AGPL licence, the third-party notices, and `SOURCE` (the repository URL and the exact tag and commit)
- **The main Dockerfile** copies both from that image. The README credits Stalwart and points to that source.

### Two programs, one container

- **The supervisor.** The entrypoint (root only to fix data ownership, as today) now runs `someless-run`, a small Python supervisor, as user 2001. It is PID 1. It:
  1. Creates `/data/stalwart/` if missing.
  2. Starts Stalwart, runs first-time setup if needed (see below), then starts gunicorn exactly as today (2 gthread workers).
  3. Restarts Stalwart if it exits, waiting longer each time (1 s, 2 s, 4 s … up to 60 s).
  4. Restarts Stalwart when the panel asks (`SIGUSR1` to the supervisor, sent from a panel request after changes that need a restart).
  5. Runs `flask --app someless engine sync` every hour.
  6. On `SIGTERM`, stops both; if gunicorn exits, stops Stalwart and exits, so Docker restarts the container.
- **Health.** The container healthcheck stays the panel's `/healthz`. Stalwart's health appears in the panel's checklist, not in Docker's.

### Ports

Nothing runs as root, so the container uses ports above 1024:

| Inside the container | Host (compose) | Purpose |
|---|---|---|
| 17080 | 17080 | Panel, as today |
| 17587 | 587 | SMTP submission, STARTTLS (Stalwart listener `submission`) |
| 17465 | 465 | SMTP submission, implicit TLS (Stalwart listener `submissions`) |
| 17081 | 80 through the proxy, or `80:17081` without one | The supervisor's challenge relay: answers Let's Encrypt HTTP-01 and returns 404 for everything else |
| 127.0.0.1:17880 | not published | Stalwart's HTTP listener: management API, and the challenge answers the panel relays |

- **Nothing listens on port 25** in this step. Outbound delivery uses port 25 as a client.
- `docker-compose.yml`, the `docker run` line and the README's Ports table get 587 and 465.
- **Before release,** the admin confirms on the server with `sudo ss -tulpn` that 587, 465 and 17081 are free.

### Data

- **`/data/stalwart/config.json` and `/data/stalwart/db/`:** Stalwart's RocksDB store.
- **The panel's engine secrets** go in a new single-row SQLite table `engine`:
  - the Stalwart admin password
  - the admin login first-time setup made (the panel's management login)
  - the webhook secret
  - the panel's own sending account's password
  - the chosen server name
  - the setup state
- **Backups:** backing up `data/` still covers everything. The README's backup section mentions `data/stalwart/`.

### First-time setup (automatic)

Run by the supervisor through `flask --app someless engine setup`:
1. With no `config.json`, start Stalwart in bootstrap mode on 127.0.0.1:17880 with `STALWART_RECOVERY_ADMIN=admin:<random 32 chars>`. The password is stored in the `engine` table.
2. Call `x:Bootstrap/set`:
   - `serverHostname`: the internal name `someless.internal` until a real server name exists
   - `defaultDomain`: `someless.internal`
   - `requestTlsCertificate: false`
   - `generateDkimKeys: false`
3. Before the first normal start, provision our own listeners (17587 submission, 17465 submissions, 127.0.0.1:17880 http), so Stalwart never creates its defaults on privileged ports. Planned route: restart in recovery mode (`STALWART_RECOVERY_MODE=1`) and create the listeners, then restart normally. **Verify in the first implementation task.** Fallback: after the first normal start, delete the default listeners, create ours, and restart.
4. Keep the admin login that step 2 made (`updated.singleton.username` and `secret`). The panel signs in to the management API with it (Basic auth): one fewer secret than a separate API key, with the same trust. The webhook and the panel's sending account (section 4) are made by the first sync.
5. Restart Stalwart normally. From then on it starts without `STALWART_RECOVERY_ADMIN`; the admin password stays stored for emergencies.

Setup is idempotent: each step checks whether its result already exists, so an interrupted setup resumes.

## 2. Keeping Stalwart in line

New module `app/someless/engine/`:

| Unit | What it does | Depends on |
|---|---|---|
| `client.py` | JMAP management client: `call(method, args)`, `get`, `set`, `query`; raises `EngineUnavailable` or `EngineError` | the `engine` table (API key), HTTP |
| `setup.py` | First-time setup (section 1) | `client`, supervisor signals |
| `sync.py` | Works out the desired Stalwart state from the panel's database and applies the difference | `client`, the panel's tables |
| `checks.py` | The Ready-to-send checklist (section 3) | `client`, dnspython, sockets |
| `deliveries.py` | Webhook endpoint, `deliveries` table, test-email sending (section 4) | `client`, smtplib |
| `cli.py` | `flask engine setup`, `flask engine sync`, `flask engine status` | the above |

### What the panel pushes

| Panel | Stalwart |
|---|---|
| Each authenticated domain | `Domain` (name; `dkimManagement: Manual`; `certificateManagement: Manual`, except the server name's domain, see section 3) and one `DkimSignature` (`Dkim1RsaSha256`, selector `someless`, our stored private key) |
| A domain not authenticated, lost, or deleted | Its `Domain` and `DkimSignature` removed |
| Each SMTP key that hasn't expired | An `Account` (`User`, in domain `someless.internal`): the name is the key's login; the password is `{SHA256}` + base64 of the key's stored digest; a member of `someless-senders`; `encryptionAtRest: Disabled` |
| Every Sender address | An alias of one `Group` account, `someless-senders` (an address can belong to one account only: Stalwart refuses the same alias twice with `primaryKeyViolation`) |
| An expired or deleted key | Its `Account` removed |
| The panel's own sending account (`someless-panel`) | An `Account` with a random password, a member of `someless-senders` |

### How a sync runs

- **Idempotent.** A sync reads Stalwart's current objects (the ones the panel manages carry a description starting `someless:`), compares them with the desired state, and creates, updates or destroys only the difference. Objects not marked `someless:` are left alone.
- **When it runs:**
  - after each change: domain check result, domain delete, key create/delete, sender add/edit/delete
  - at start
  - hourly (supervisor)
- **One at a time.** Only one sync runs at once across gunicorn's workers and the CLI: a file lock, `/data/someless/engine.lock` (`fcntl.flock`).
- **Failure.** If Stalwart can't be reached or refuses, the panel's change is still saved. The failure is logged, the sync retries on the next trigger, and SMTP & API shows "Mail engine catching up…" until a sync succeeds. The `engine` table records the last success and the last error.
- **After DKIM or listener changes,** the sync sends `ReloadSettings`.

### One login per key (SMTP & API changes)

- **The new column.** `smtp_keys.login`: unique, made from the key's name as lowercase ASCII (up to 20 characters) plus `-` and 4 random hex characters, like `website-7f3a`. A name with no usable characters gives `key-7f3a`.
- **Existing keys** get a login in a database migration at start.
- **"Your SMTP key" dialog:** shows the login and the key, each with a copy button.
- **Keys table:** gets a Login column with a copy button.
- **Settings card:** Login becomes "The login of the key you use".
- **The guide's examples:** read the login from `SOMELESS_SMTP_LOGIN` and the key from `SOMELESS_SMTP_KEY`.
- **`smtp_settings.login`** is no longer shown. The column stays, unused.
- **Stalwart logins:** a login without `@` gets the default domain (`someless.internal`) appended, so apps just type `website-7f3a`. Verify this.

## 3. Server name, certificate, Ready-to-send checks

### Server name

- **One name for the server:** its SMTP greeting (`SystemSettings.defaultHostname`, outbound EHLO), its certificate, the SMTP server shown to apps, and the name its reverse DNS should match.
- **Default:** `<mail host>.<domain>` of the first authenticated domain (alphabetical), for example `mail.pineloop.online`.
- **Changing it:** a dropdown on SMTP & API offers each authenticated domain's mail host. Changing it re-syncs and requests a new certificate.
- **No authenticated domain yet:** the checklist says so, and nothing can send.

### Certificate

- **Setup.**
  - The sync creates one `AcmeProvider` (`Http01`, Let's Encrypt production, contact `postmaster@<server name's domain>`).
  - It sets the server name's domain `certificateManagement` to `Automatic` with `subjectAlternativeNames: {<server name>: true}`.
- **Let's Encrypt's check.** It requests `http://<server name>/.well-known/acme-challenge/<token>`. The admin's proxy (or port mapping) sends it to container port 17081.
- **Port 17081 is a tiny relay in the supervisor,** apart from the panel's pages. It answers only `GET /.well-known/acme-challenge/<token>`, by fetching the same path from Stalwart at 127.0.0.1:17880 and relaying status and body. Everything else gets 404. Stalwart's HTTP side is never exposed.
- **Once issued,** the sync sets `SystemSettings.defaultCertificateId` and sends `ReloadTlsCertificates`. Stalwart renews it by itself.
- **Until then** there's no trusted certificate, and the checklist explains the proxy-host step.

### Ready-to-send checklist (top of SMTP & API, replacing the "Sending starts…" note)

| Item | Check | When not met |
|---|---|---|
| Mail engine running | `client` answers | "The mail engine isn't answering. It restarts by itself; if this lasts, restart the container." |
| Server name points here | A record of the server name equals the server's public IP | "Add the A record on the Authenticate page of <domain>." (link) |
| Certificate | a `Certificate` exists for the server name and isn't expired | Waiting: the Nginx Proxy Manager proxy-host steps, or `80:17081`. Failed: Let's Encrypt's reason |
| Outgoing port 25 | TCP connect to `gmail-smtp-in.l.google.com:25` within 5 s | "Your VPS provider blocks outgoing port 25. Ask them to open it; mail can't reach other servers until then." (warning) |
| Reverse DNS | PTR of the server's IP equals the server name | "At your VPS provider, set the reverse DNS of <IP> to <server name>." (warning) |
| A Sender | at least one Sender | link to Senders |

- **Timing.** Checks run when the page opens, cached for 5 minutes, and on **Check again**.
- **Can send when** the engine is running, the certificate exists and there's a Sender. Port 25 and reverse DNS are warnings.

## 4. Test email and delivery results

### The panel's sending account

`someless-panel`, created at setup and synced like a key account. The panel sends through `127.0.0.1:17587` with STARTTLS; it doesn't verify the certificate, because it's loopback inside the container.

### "Send test email"

- **Where:** a button on each Sender card on the Senders page. It opens a dialog:
  - **To:** required, one address
  - **Subject:** "Test from Someless Mail", editable
  - **Text:** a short prefilled message, editable
- **Sending.** `POST /senders/<id>/test` sends through the panel's account from that Sender's address. It reads the queue id from the DATA reply, stores a row in `deliveries` (queue id, sender id, recipient, status `queued`, time) and returns the id.
- **Live status.** The dialog polls `GET /senders/<id>/tests/<queue id>` every 2 s for up to 60 s. It shows:
  - Queued
  - Delivered to <remote server>
  - Bounced: <remote reply>
  - Trying again later: <reply>
  - after 60 s: "Still on its way; the result will show on the card"
- **The card** shows the last result: "Last test: delivered to you@gmail.com, 2 minutes ago".
- **Engine not ready:** the button is disabled, and its tooltip gives the checklist's reason.

### Delivery results (webhook)

- **Setup.** A Stalwart `WebHook` object posts delivery events to `http://127.0.0.1:17080/engine/events` with the webhook secret. Accepted only from loopback, with a valid secret.
- **The loopback check** uses the socket's own address (the WSGI `REMOTE_ADDR` before `ProxyFix` rewrites it). A forged `X-Forwarded-For: 127.0.0.1` sent straight to the published port 17080 doesn't pass. The secret is the real guard; loopback is a second one.
- **What the panel records.** It updates `deliveries` by queue id and recipient, from:
  - `delivery.delivered` → delivered
  - `delivery.dsn-perm-fail` and `delivery.rcpt-to-rejected` → bounced
  - temporary failures → retrying
  - `delivery.completed` → final
- **Verify** the exact payload fields in the first implementation task.
- **Which messages.** Only messages the panel sent are recorded. App mail isn't tracked in this step.

## Errors

- **Engine unreachable:**
  - panel pages keep working
  - the checklist shows it
  - syncs retry
  - the test button is disabled
- **Stalwart crash loop:** the supervisor backs off, up to 60 s between restarts. The panel shows the last error from the `engine` table.
- **Apps get standard SMTP replies:**
  - `535` authentication failed (wrong login or key, or an expired or deleted key)
  - `501 5.5.4` sender not allowed (not on the Senders list)
  - `454` or TLS errors while no certificate exists
- **A failing sync never blocks the admin's action.** It's reported and retried.

## Testing

**Unit tests (pytest)**
- A fake engine client records calls and holds objects in memory.
- The sync's desired state and diff:
  - domains in and out with authentication
  - DKIM import payload
  - key accounts: `{SHA256}` format from a stored hex digest, in the Senders group, expired and deleted keys removed
  - the panel account
  - untouched non-`someless:` objects
- Login generation, uniqueness, and the migration of existing keys.
- The file lock: two syncs don't overlap.
- Each checklist item, with DNS and sockets faked.
- The challenge-only port: only the challenge path is answered; everything else is 404.
- The webhook: secret required, loopback only, updates `deliveries`.
- The test-email flow with a fake SMTP server.

**Container test in CI** (extends `.github/workflows/docker.yml`)
- The image starts; setup completes; Stalwart listens on 17587/17465; the panel is healthy.
- Through the panel's code paths (a test-only CLI, not an HTTP route):
  - add an authenticated test domain, a Sender and a key
- Then a Python script sends on 17587 with STARTTLS and the key:
  - from the Sender → accepted (queued, DKIM-signed as seen in the queue)
  - from another address → `501`
  - with a wrong key → `535`
- No real outbound delivery in CI.

**On the admin's VPS**
- Send to a Gmail address and check the headers: DKIM, SPF and DMARC pass; the inbox, not spam.
- Check the certificate through the proxy host.

## Out of scope

- Receiving mail
- The MX move, inboxes, IMAP, webmail
- Bounce and suppression lists
- Sending limits and rates
- Tracking app mail
- The API keys page
- Per-domain certificates beyond the server name
- DNS-API certificate issuance

## To verify first (first implementation task, a spike kept as tests or discarded)

1. The FOSS build of v0.16.23 (default features, no `enterprise`) on Debian trixie. Build time and memory on GitHub's runners; binary size.
2. ✓ The first-start route (spike on Windows, v0.16.23): `x:Bootstrap/set` returns `{"username": "admin@someless.internal", "secret": …}` and writes config.json; listeners made in recovery mode (the object is `x:NetworkListener`) persist, and a normal start then opens only ours (17587, 17465, 127.0.0.1:17880; nothing on 25/465/443). Basic auth with the bootstrap login works in normal mode.
3. Partly ✓: STARTTLS on 17587 works before any certificate (Stalwart's own self-signed one). Running as uid 2001 is checked in the image's smoke test.
4. ✓ `{SHA256}` + base64 of the digest logs in with the bare login (`235`). `mustMatchSender` is on by default (`x:SenderAuth`): a MAIL FROM that isn't an alias gets `501 5.5.4 You are not allowed to send from this address.` Mail from an alias is signed `a=rsa-sha256; s=someless; d=<domain>` (default `dkimSignDomain`: the sender's domain when it's local and the sender logged in).
5. ✓ DATA replies `250 2.0.0 Message queued with id 49a58608ba00200.` (hex). The webhook posts `{"events": [{"id", "createdAt", "type", "data": {…}}]}`; `data.queueId` is the same id as a decimal number. `delivery.dsn-perm-fail` carries `to` (one address), `hostname` and `details`; `delivery.completed` carries `to` as a list. `X-Signature` is base64 HMAC-SHA256 of the body. The WebHook object needs `eventsPolicy: "include"` (the default is exclude) and `signatureKey: {"@type": "Value", "secret": …}`; `throttle: 0` is refused. Bounces of mail sent by a key account land in that account's mailbox.
6. HTTP-01 answered through the relay on 17081 (on the VPS, with a real name).

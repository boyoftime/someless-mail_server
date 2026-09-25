# Someless Mail Server

Welcome to **Someless Mail Server** — your own mail server in a single Docker image. Install it on your server, open the web interface, connect your domain, create inboxes, and send and receive email.

**Version:** 1.0.0

> **Status: in development.** The web interface works today (welcome page, login, settings). Connecting domains, inboxes, and sending and receiving mail are being built next.

## What you need

- A Linux server (VPS) with [Docker](https://docs.docker.com/engine/install/) installed
- For sending and receiving mail (coming next): a fixed public IP address, port 25 open at your provider, and a domain you control

## Install

Pick one of the two ways below. Both keep all your data in a `data` folder right where you install Someless Mail, so it's easy to find and back up, and it survives updates and restarts (see [Your data](#your-data)).

### Option 1: `docker run`

Run this from the folder where you want your `data` folder:

```
docker run -d --name someless-mail --restart unless-stopped \
  -p 17080:17080 \
  -v "$(pwd)/data:/data" \
  ghcr.io/boyoftime/someless-mail:1.0.0
```

### Option 2: Docker Compose

Create a folder, save this as `docker-compose.yml` inside it (the same file is in this repository):

```yaml
services:
  someless-mail:
    image: ghcr.io/boyoftime/someless-mail:1.0.0
    container_name: someless-mail
    restart: unless-stopped
    ports:
      - "17080:17080"   # web interface
    volumes:
      - ./data:/data    # all your data, in a "data" folder next to this file
```

Then start it from that folder:

```
docker compose up -d
```

The `data` folder appears next to `docker-compose.yml` on the first start.

### Open it

Go to `http://your-server-ip:17080` in your browser. You'll see a short welcome animation, then the login page.

## First login

| Username | Password |
|---|---|
| `admin` | `admin` |

Change both right after your first login in **Settings**. Until you change the password, the dashboard shows a warning — anyone who knows the default can log in.

## Use a domain instead of `ip:17080` (optional)

If you run a reverse proxy such as [Nginx Proxy Manager](https://nginxproxymanager.com/), you can reach Someless Mail at `https://mail.yourdomain.com` with no port number.

1. Put Someless Mail on the same Docker network as the proxy and remove the public port. With Nginx Proxy Manager on a network called `nginx-proxy`:

   ```yaml
   services:
     someless-mail:
       image: ghcr.io/boyoftime/someless-mail:1.0.0
       container_name: someless-mail
       restart: unless-stopped
       expose:
         - "17080"
       volumes:
         - ./data:/data
       networks:
         - nginx-proxy

   networks:
     nginx-proxy:
       external: true
   ```

2. In Nginx Proxy Manager, add a proxy host: domain `mail.yourdomain.com`, forward to `someless-mail` on port `17080`, and request an SSL certificate.

## Ports

Someless Mail uses its own port numbers so it doesn't collide with other services on your server. The easy rule: **Someless port = standard mail port + 17000**.

| Service | Port inside container | Host port | What it is for |
|---|---|---|---|
| Web interface | 17080 | 17080 | Welcome page, login, admin panel, webmail |
| SMTP | 25 | 25 | Receiving mail from other mail servers (coming next) |
| SMTP Submission | 587 | 587 | Sending mail from mail apps (coming next) |
| SMTPS | 465 | 465 | Sending mail from mail apps (coming next) |
| IMAPS | 993 | 993 | Reading mail in mail apps (coming next) |

The mail ports will be added to the install commands above when the mail engine arrives.

- **Port 25 cannot be changed.** Every mail server on the internet delivers to port 25 only, and only one mail server per IP address can receive mail.
- Many VPS providers **block port 25 by default** — check with your provider and ask them to unblock it.
- **Testing next to another mail server?** Map the test ports `17025`, `17587`, `17465` and `17993` to the container's `25`, `587`, `465` and `993`. Real mail from the internet only ever arrives on port 25, so a test setup can't receive it.

**Firewall:** allow inbound TCP `17080` if you open the web interface by IP. When the mail engine arrives, also allow `25`, `465`, `587` and `993`.

## Your data

Everything Someless Mail keeps (your login, settings, password rules and, later, your mail) is in the `data` folder next to your `docker-compose.yml`:

```
your-folder/
├── docker-compose.yml
└── data/
    └── someless/
        ├── someless.db    ← login, settings and password rules
        └── secret_key     ← signs your login, so it survives restarts
```

So the database is at `data/someless/someless.db`.

- **Updates keep it.** `docker compose pull && docker compose up -d` never touches it.
- **To back up,** copy the whole `data` folder. For a perfect copy, stop Someless Mail first (`docker compose stop`), copy, then `docker compose start`.
- **Don't delete it** unless you want to start over with `admin` / `admin`.
- **No permissions to set up.** Someless Mail runs as its own user (ID 2001), not as root, and takes the folder over by itself when it starts.

### Moving from an older install

Early installs kept the data in a Docker volume instead. To move it into the `data` folder, run this in the folder with your `docker-compose.yml`. Docker names the volume after that folder, so replace `someless_mail` with your folder's name:

```
docker compose down
mkdir -p data
cp -a /var/lib/docker/volumes/someless_mail_someless-data/_data/. data/
```

Then replace your `docker-compose.yml` with the one above and start again with `docker compose pull && docker compose up -d`. Once everything works, remove the old volume: `docker volume rm someless_mail_someless-data`.

## Development

Requires Python 3.12+.

```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
SOMELESS_DATA_DIR=./devdata .venv/bin/python -m flask --app app/someless:create_app run --port 17080
```

## Credits

- Mail engine: [Stalwart](https://github.com/stalwartlabs/stalwart) (AGPL-3.0) — being added next.
- Font: [Google Sans](https://github.com/googlefonts/googlesans), SIL Open Font License 1.1 (`app/someless/static/fonts/OFL.txt`).
- Animation player: [lottie-web](https://github.com/airbnb/lottie-web) 5.13.0 (MIT).
- Login background: [PixiJS](https://github.com/pixijs/pixijs) 8.21.0 (MIT).

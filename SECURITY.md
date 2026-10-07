# Security policy

Someless Mail runs people's mail: a problem in it can expose their messages, their passwords or their domains. If you find one, thank you for telling us privately first.

## Who looks after it

**Someless Ado** (Samwel N Adonia, [@boyoftime](https://github.com/boyoftime) on GitHub), the maker of Someless Mail, is its security maintainer: they read every report, fix what's found, and publish the fixed version.

## Reporting a vulnerability

Please don't open a public issue for it. Report it privately on GitHub instead:

**[Report a vulnerability](https://github.com/boyoftime/someless-mail_server/security/advisories/new)** (the repository's **Security** tab, then **Report a vulnerability**).

Say what you found, where (the web interface, the webmail, the API, the Docker image…), how to make it happen, and what it lets someone do. You'll hear back as soon as it has been looked at, the fix is made together with you where that helps, and you're credited in the advisory unless you'd rather not be.

## Supported versions

Fixes go into the latest version, which every server gets with:

```
docker compose pull && docker compose up -d
```

| Version | Supported |
|---|---|
| 1.0.0 (latest) | Yes |

## What's covered

- The web interface (port 17080), the webmail (port 17090), the API (`/api/s1`), and the Docker image as published.
- The mail engine inside it, [Stalwart](https://github.com/stalwartlabs/stalwart), is built by its own team: a problem in Stalwart itself goes to them, following [Stalwart's security policy](https://github.com/stalwartlabs/stalwart/security/policy). If you're not sure which side it's on, report it here and it's passed on.

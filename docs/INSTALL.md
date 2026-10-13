# Installation

The easiest way to install is the guided installer: run `sudo ./install.sh` from a
checkout and pick an option from the menu. It asks for the domain, the administrator
account and the timezone, then calls the scripts described below. The rest of this
page covers non-interactive installation and what each step does.

Supported: **Ubuntu 22.04 LTS and 24.04 LTS** on x86_64 or arm64, for both the control
plane and the agents. Python ≥ 3.10 comes from the Ubuntu archive. PostgreSQL is the
distribution package: 14 on 22.04, 16 on 24.04.

## 1. Control plane

### Requirements

- Sizing guidance (an estimate, not a benchmark): start with 2 vCPU and 2 GB RAM for
  a few dozen agents. Each agent writes one system sample plus one row per interface
  every 10 s, which is roughly 5–15 MB per agent per day including indexes. Metrics are
  kept for 30 days by default (`IPF3_RETENTION_METRICS_DAYS`).
- A DNS name pointing at the host (for Let's Encrypt), or a private CA certificate, or a
  self-signed certificate.
- Inbound TCP 443 from operators and agents. TCP 80 is needed only for the ACME HTTP-01
  challenge and the redirect.

### Install

```bash
git clone https://github.com/amirali272/ipf3.git
cd ipf3
sudo ./deploy/install-server.sh --domain ipf3.example.com --tls letsencrypt --email ops@example.com
```

| Option | Meaning |
|---|---|
| `--domain` | Name or IP that browsers and agents use. Required. |
| `--tls auto` (default) | Uses Let's Encrypt when the domain resolves, falling back to self-signed if that fails. Uses self-signed for IP addresses. |
| `--tls letsencrypt --email …` | Obtains a certificate with certbot (webroot) and installs a renewal hook that reloads nginx. |
| `--tls self-signed` | Generates a 3072-bit RSA certificate with the correct SAN in `/etc/ipf3/tls/`. Agents then need `--ca-file` pointing at a copy of `server.crt`. |
| `--tls existing --cert --key` | Uses your own certificate, for example from an internal CA. |
| `--admin-user` | Name of the administrator. Default `admin`. Set `IPF3_ADMIN_PASSWORD` in the environment to choose its password; otherwise a random password is printed once. |
| `--timezone` | Calendar used for daily and monthly traffic totals, for example `Asia/Tehran`. |
| `--workers N` | Number of uvicorn worker processes. Default 2. |
| `--ufw` | Allows OpenSSH, 80 and 443 in ufw, then enables ufw. |
| `--skip-web-build` | Uses a prebuilt `web/dist`, so Node.js isn't needed on the server. |

What the script does:

1. Installs `postgresql`, `nginx`, `python3-venv` and Node.js. Node.js is used only to
   build the UI: it comes from the Ubuntu archive on 24.04 and from the signed NodeSource
   repository on 22.04.
2. Creates the `ipf3` system account (no shell, no home), `/opt/ipf3` (root-owned code),
   and `/etc/ipf3` (`root:root 0755`; secret files inside are `0640`: `server.env` group `ipf3`, `agent.json` group `ipf3-agent`, so the server and an agent can share a host).
3. Creates a PostgreSQL role and database `ipf3` with **peer authentication over the Unix
   socket**. There's no database password to leak. The role isn't a superuser, and
   `PUBLIC` privileges are revoked.
4. Writes `/etc/ipf3/server.env` (mode 0640) with a random 256-bit `IPF3_SECRET_KEY`.
5. Installs the Python app from the pinned `server/requirements.lock` into
   `/opt/ipf3/venv`. Builds the UI unprivileged (npm never runs as root) into
   `/opt/ipf3/web`. Applies the Alembic migrations.
6. Installs the hardened `ipf3-api`, `ipf3-worker` and `ipf3-backup.timer` units, plus
   the nginx site with TLS 1.2/1.3, HSTS, CSP and rate limits on login and enrollment.
7. Creates the admin user and prints a random password **once**.

Re-running the script is safe. It keeps the secret key, database and users.

## 2. Agents

On each Ubuntu host you want to monitor:

1. In the UI, go to **Servers → Enroll server** and create a token. Tokens are single-use
   and expire (24 h by default).
2. Run the installer:

```bash
git clone https://github.com/amirali272/ipf3.git && cd ipf3
sudo ./deploy/install-agent.sh \
  --server https://ipf3.example.com \
  --token ipf3e_XXXXXXXX \
  --name fra1-edge-03 \
  --iperf3-server            # optional: run an iperf3 endpoint here
  # --ca-file ./server.crt   # when the server uses a self-signed / private CA cert
```

The installer:

- Installs `iperf3`, `iputils-ping`, `traceroute`, `mtr-tiny` and `iproute2` from the
  Ubuntu archive. Debconf is preseeded so the distribution's own iperf3 daemon stays
  disabled.
- Creates the `ipf3-agent` system account and a virtualenv in `/opt/ipf3-agent`.
- Enrolls the agent. The token is exchanged for a per-agent credential, stored in
  `/etc/ipf3/agent.json` (`root:ipf3-agent 0640`).
- Starts `ipf3-agent.service`. Its only capability is `CAP_NET_RAW`, used for ICMP/TCP
  traceroute and MTR.
- With `--iperf3-server`, starts `ipf3-iperf3.service`: `iperf3 -s` under a transient
  `DynamicUser` with no capabilities.

The agent connects **outbound only** to `https://<server>/api/agent/v1`. No inbound port
is needed, unless you enabled the iperf3 endpoint.

### Firewalling the iperf3 endpoint

iperf3 has no access control by default. Allow TCP **and** UDP on the port (default
5201) only from the hosts that run tests against it:

```bash
sudo ufw allow from 10.20.0.0/16 to any port 5201 proto tcp
sudo ufw allow from 10.20.0.0/16 to any port 5201 proto udp
```

iperf3 ≥ 3.7 also supports RSA authentication. You can pass the extra server arguments
through `/etc/ipf3/iperf3.env`:

```
IPF3_IPERF3_PORT=5201
IPF3_IPERF3_EXTRA_ARGS=--rsa-private-key-path /etc/ipf3/iperf3-private.pem --authorized-users-path /etc/ipf3/iperf3-users.csv
```

## 3. Verify

```bash
systemctl status ipf3-api ipf3-worker            # control plane
curl -fsS https://ipf3.example.com/healthz
systemctl status ipf3-agent                      # each host
journalctl -u ipf3-agent -f
sudo -u ipf3-agent /opt/ipf3-agent/venv/bin/ipf3-agent check   # tools + a live sample
```

In the UI the server shows as **Online** within about 10 s. Charts start filling after
the second sample, because rates need two counter readings.

## Uninstalling an agent

```bash
sudo ./deploy/uninstall-agent.sh
```

Then delete the server in **Servers → (server) → Settings**. That removes its stored
metrics and history.

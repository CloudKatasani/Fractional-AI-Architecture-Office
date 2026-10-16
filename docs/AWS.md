# Hosting the Fractional AI Architecture Office on AWS

A step-by-step guide to run the prototype on **one EC2 instance with Caddy and a free `sslip.io`
HTTPS address** — for a shared team demo, a client walkthrough or a workshop.

> **Read [hosting-prerequisites.md](hosting-prerequisites.md) first.** It is short. The prototype
> needs **no code changes** for this deployment, but it has **no authentication** (B1), so the
> Caddy password in [§6](#6-https-and-a-password-caddy--sslipio) is not optional. The `B*` and `C*`
> identifiers below refer to that document.

For running it on a laptop, see the [README](../README.md) and [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

---

## 1. The architecture

```
 Browser ──HTTPS 443──► EC2 · Ubuntu 24.04 LTS · Elastic IP
                        ┌────────────────────────────────────────────────────────┐
                        │ caddy (systemd)                                         │
                        │   Let's Encrypt certificate for <ip-with-dashes>.sslip.io│
                        │   basic_auth password                                   │
                        │   └─► reverse_proxy 127.0.0.1:8000                      │
                        │                                                         │
                        │ arch-office (systemd) · 1 × uvicorn · FastAPI           │
                        │   /api/v1/…  agents, approvals, audit, knowledge graph  │
                        │   /docs      OpenAPI explorer                           │
                        │   /…         React UI from frontend/dist                │
                        │   data/northgrid.db · data/meridian.db  (SQLite, WAL)   │
                        │                                                         │
                        │ cron: nightly SQLite backup ──► /var/backups (+ S3)     │
                        └────────────────────────────────────────────────────────┘
```

| Choice | Why |
|---|---|
| **One EC2 instance** | The app is one Python process with SQLite files on local disk and in-memory caches (C1). One instance with an EBS volume is the shape it was built for. |
| **Caddy** | Obtains and renews the TLS certificate by itself, adds the password the app lacks (B1), and is three lines of configuration. |
| **sslip.io** | A free wildcard DNS service: `3-140-25-17.sslip.io` resolves to `3.140.25.17`. Real HTTPS with no domain to buy and no Route 53 to configure. You can switch to your own domain at any time ([§8.6](#86-use-your-own-domain-instead-of-sslipio)). |
| **Elastic IP** | Keeps the public IP — and therefore the `sslip.io` name and its certificate — the same across stop/start. Costs the same as the automatic public IP it replaces. |
| **No Docker** | Not needed: Python, Node (for the one-off UI build) and Caddy are installed from packages. Fewer moving parts to debug in a demo. |

**What will not work:** S3 static hosting, Amplify Hosting or CloudFront alone (the app needs the
running API for agent runs, approvals and the copilot), Lambda (in-memory state, SQLite on local disk),
and more than one instance or worker (C1).

**Rough cost** (us-east-1, on-demand list price): **~USD 19/month** running 24×7 on a t3a.small,
**~USD 7/month** for business hours only, **~USD 1.60/month** while stopped. Details in [§9](#9-sizing-and-cost).

---

## 2. Prerequisites

| You need | Notes |
|---|---|
| An AWS account with permission to create EC2 instances, security groups, Elastic IPs and IAM roles | An administrator account is simplest for a demo account |
| A web browser | Everything is done in the AWS console and a browser terminal |
| ~40 minutes | Most of it waiting for packages and the UI build |

You do **not** need a domain name, Docker, the AWS CLI on your computer, or an Anthropic API key —
the demo runs in deterministic mock mode by default ([§7](#7-live-llm-mode-on-aws)).

Throughout, replace:

| Placeholder | Example |
|---|---|
| `<public-ip>` | `3.140.25.17` |
| `<site>` | `3-140-25-17.sslip.io` (the IP with dashes, plus `.sslip.io`) |
| `<account-id>` | your 12-digit AWS account id |

---

## 3. Provision the instance

### 3.1 Security group

AWS console → **EC2** → check the **region** (top right) → **Security Groups** → **Create security group**.

| Setting | Value |
|---|---|
| Name | `arch-office` |
| Description | `Architecture Office demo: HTTPS via Caddy` |
| VPC | default |
| Inbound rule 1 | **HTTP**, TCP 80, Source **Anywhere-IPv4** (0.0.0.0/0) — Let's Encrypt validates the certificate over port 80; Caddy then redirects all HTTP to HTTPS |
| Inbound rule 2 | **HTTPS**, TCP 443, Source **Anywhere-IPv4**, or your office CIDR for a tighter demo ([§6.5](#65-tighten-access-further)) |
| Inbound rule 3 *(only if you will SSH)* | **SSH**, TCP 22, Source **My IP** |
| Outbound | leave the default (all traffic) — needed for packages, certificates and live LLM mode |

**Do not open port 8000.** The app listens on `127.0.0.1` only (B3).

### 3.2 IAM role for Session Manager (recommended over SSH keys)

Session Manager gives you a browser terminal with no open SSH port and no key file to lose.

IAM → **Roles** → **Create role** → *Trusted entity*: **AWS service** → *Use case*: **EC2** → Next →
attach **`AmazonSSMManagedInstanceCore`** → Next → name **`arch-office-ec2`** → **Create role**.

(The same role gets S3 backup permission later, in [§8.4](#84-backups).)

### 3.3 Launch the instance

EC2 → **Instances** → **Launch instance**.

| Setting | Value |
|---|---|
| Name | `arch-office` |
| Application and OS image | **Ubuntu** → **Ubuntu Server 24.04 LTS** (HVM, SSD Volume Type), **64-bit (x86)** |
| Instance type | **t3a.small** (2 vCPU, 2 GB) — see [§9](#9-sizing-and-cost) |
| Key pair | **Proceed without a key pair** if you use Session Manager; otherwise create one (`arch-office`, RSA, `.pem`) |
| Network settings → **Edit** | VPC: default · Subnet: no preference · **Auto-assign public IP: Enable** · Firewall: **Select existing security group** → `arch-office` |
| Configure storage | **20 GiB**, **gp3** |
| Advanced details → **IAM instance profile** | `arch-office-ec2` |
| Advanced details → **Metadata version** | **V2 only (token required)** |

**Launch instance**. Wait for **Instance state = Running** and **Status check = 3/3 checks passed**
(1–3 minutes).

### 3.4 Elastic IP

EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**. Select it → **Actions →
Associate Elastic IP address** → *Instance*: `arch-office` → **Associate**.

Note the address: this is `<public-ip>` from now on, and `<site>` is it with dashes plus `.sslip.io`.

> Skipping the Elastic IP works, but the IP changes on every stop/start. [§8.5](#85-stop-and-start-to-save-money)
> installs a boot-time script that moves the `sslip.io` name automatically either way.

### 3.5 Connect

* **Session Manager (recommended):** select the instance → **Connect** → **Session Manager** →
  **Connect**. If the tab says the instance is not connected, wait two minutes after the launch — the
  SSM agent preinstalled on Ubuntu images registers itself — and check the IAM role from §3.2 is
  attached (instance → *Security* tab).
* **SSH:** `ssh -i arch-office.pem ubuntu@<public-ip>` (`chmod 400 arch-office.pem` first on
  macOS/Linux). *EC2 Instance Connect* also works, but it connects from AWS's address range, not
  *My IP*; open the SSH rule to that range or use your own client.

Session Manager opens a `sh` shell as `ssm-user`; type `bash` first. Every block below is pasted
into that terminal, and each is safe to paste again if it was interrupted.

---

## 4. Install the system packages

```bash
# 2 GB swap so the UI build fits in memory on a 2 GB instance
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

sudo apt-get update -y
sudo apt-get install -y git curl make sqlite3 python3 python3-venv python3-pip \
  debian-keyring debian-archive-keyring apt-transport-https gnupg

# Node.js 22 LTS — only used to build the UI (needs Node 18+)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Caddy from its official apt repository
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -y && sudo apt-get install -y caddy

python3 --version   # 3.12 or newer
node --version      # v22.x
caddy version       # v2.x
```

Installing the `caddy` package starts a placeholder site on port 80; §6 replaces it.

---

## 5. Install the application

### 5.1 Get the code

```bash
# Service user that owns the app and its data; it cannot log in
id archoffice >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin archoffice

[ -d /opt/arch-office ] || sudo git clone https://github.com/CloudKatasani/Fractional-AI-Architecture-Office.git /opt/arch-office
sudo chown -R archoffice:archoffice /opt/arch-office
```

> **Private repository:** clone with a GitHub personal access token,
> `https://<token>@github.com/CloudKatasani/Fractional-AI-Architecture-Office.git`.
> **Another branch:** add `-b <branch>` to the clone.

### 5.2 Configure, install dependencies, generate data, build the UI

```bash
cd /opt/arch-office
sudo -u archoffice bash -c '
  set -e
  # Configuration. DEMO_TODAY pins every synthetic date to the install day (C3).
  [ -f .env ] || cp .env.example .env
  sed -i "s/^DEMO_TODAY=.*/DEMO_TODAY=$(date +%F)/" .env
  chmod 600 .env

  # Python dependencies
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt -q

  # Synthetic tenants NorthGrid Energy and Meridian Telecom (~15 s; C2)
  PYTHONPATH=backend:. .venv/bin/python -m data_gen.generate --all --if-missing

  # UI into frontend/dist (2-5 minutes on a small instance; C4)
  cd frontend && npm ci --no-audit --no-fund && npm run build
'
ls -l data/*.db frontend/dist/index.html
```

Expect the generator to print a summary per tenant, the build to end with `✓ built in …s`, and the
`ls` to show `meridian.db`, `northgrid.db` and `index.html`.

### 5.3 Run it as a service

One worker, bound to localhost (C1, B3). systemd starts it at boot and restarts it if it stops.

```bash
sudo tee /etc/systemd/system/arch-office.service >/dev/null <<'EOF'
[Unit]
Description=Fractional AI Architecture Office (FastAPI + UI)
After=network-online.target
Wants=network-online.target

[Service]
User=archoffice
Group=archoffice
WorkingDirectory=/opt/arch-office/backend
Environment=PYTHONPATH=/opt/arch-office/backend:/opt/arch-office
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/arch-office/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now arch-office
sleep 3
curl -s http://127.0.0.1:8000/api/health; echo          # {"status":"ok","llm_mode":"mock"}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/     # 200 — the UI is being served
```

The app reads `/opt/arch-office/.env` at start, so every change to it needs
`sudo systemctl restart arch-office`.

---

## 6. HTTPS and a password (Caddy + sslip.io)

### 6.1 Write the Caddyfile

The block reads the public IP from the instance metadata service, turns it into an `sslip.io` name,
generates a random password and writes the configuration.

```bash
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300')
IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
SITE=${SITE_ADDRESS:-${IP//./-}.sslip.io}
ADMIN_USER=${ADMIN_USER:-admin}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-$(openssl rand -hex 12)}
HASH=$(caddy hash-password --plaintext "$ADMIN_PASSWORD")
echo "Site: $SITE"

sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$SITE {
	encode zstd gzip
	basic_auth {
		$ADMIN_USER $HASH
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
	reverse_proxy 127.0.0.1:8000
}
EOF

sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy || sudo systemctl restart caddy

printf 'URL:      https://%s\nUser:     %s\nPassword: %s\n' "$SITE" "$ADMIN_USER" "$ADMIN_PASSWORD" \
  | sudo tee /root/arch-office-credentials.txt
sudo chmod 600 /root/arch-office-credentials.txt
```

It ends by printing:

```
URL:      https://3-140-25-17.sslip.io
User:     admin
Password: 9f2c4e…
```

They stay in `/root/arch-office-credentials.txt` (`sudo cat /root/arch-office-credentials.txt`).

To choose the user name or password yourself, set `ADMIN_USER=…` and `ADMIN_PASSWORD='…'` on their own
lines before pasting the block.

### 6.2 What Caddy does with that

* On the first request for `<site>` it obtains a **Let's Encrypt** certificate (HTTP-01 challenge on
  port 80) and renews it automatically about 30 days before expiry. Certificates live in
  `/var/lib/caddy/.local/share/caddy`.
* All `http://` requests are redirected to `https://`.
* Every request — UI, API and `/docs` — must carry the password (B1, B2). The browser asks once and
  remembers it for the session.
* Requests are proxied to the app on `127.0.0.1:8000`.

### 6.3 Open it

Open `https://<site>` in a browser. The first visit can take ~30 seconds while the certificate is
issued. Enter the user name and password; the dashboard opens on **NorthGrid Energy** (switch to
**Meridian Telecom** in the header). Then follow [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) exactly as on a
laptop.

| Check | Expect |
|---|---|
| `https://<site>/` | Dashboard, *Mock LLM* badge in the header |
| `https://<site>/portfolio`, then refresh | Portfolio page — deep links work |
| `https://<site>/docs` | OpenAPI explorer for `/api/v1` |
| `https://<site>/api/health` | `{"status":"ok","llm_mode":"mock"}` |
| `curl -sI https://<site>/` from your laptop | `HTTP/2 401` — the password is enforced |

**The prototype is hosted.** Everything below is optional, but read §6.4 before sharing the link.

### 6.4 What the password does and does not protect

One shared password is the whole access model (B1). Everyone who has it:

- can pick any demo user in the header, including the principal architect, and **approve or reject
  any proposal** — the audit trail records the name they picked, not who they are;
- can **reset a tenant** (`POST /api/v1/admin/reset`) and **switch live LLM mode on** for everyone (B2);
- sees only synthetic data (C5).

So share it with the people in the demo, change it afterwards ([§8.7](#87-change-the-password)), and
reset the demo data between audiences ([§8.3](#83-reset-the-demo-data)).

### 6.5 Tighten access further

Pick what fits the audience — they combine:

- **Office-only:** in the `arch-office` security group, change the **443** rule's source from
  *Anywhere* to your office or VPN CIDR. Leave **80** open to *Anywhere* so certificate renewal keeps
  working (Caddy only redirects there; nothing is served on 80).
- **Open link, no password** (a public showcase): remove the `basic_auth { … }` block from
  `/etc/caddy/Caddyfile` and `sudo systemctl reload caddy`. Every visitor can then do everything listed
  in §6.4. Leave `ANTHROPIC_API_KEY` unset on such a server, and put the password back afterwards by
  re-running §6.1.

---

## 7. Live LLM mode on AWS

Mock mode — the default — produces deterministic narratives from templates, makes no outbound call,
and is what you want for repeatable client demos. Findings are computed from the data in both modes;
live mode only changes who writes the summary and ranking.

To let Claude write the narratives:

```bash
cd /opt/arch-office
read -rsp 'Anthropic API key: ' KEY; echo
sudo -u archoffice sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$KEY|" .env
sudo -u archoffice sed -i 's/^LLM_MODE=.*/LLM_MODE=live/' .env   # or leave mock and use the header badge
unset KEY
sudo systemctl restart arch-office
curl -s http://127.0.0.1:8000/api/health; echo     # "llm_mode":"live"
```

- The key lives only in `.env`, mode `600`, owned by `archoffice` — not in the repository, the
  shell history (`read -s`) or the Caddyfile.
- With the key set, any signed-in visitor can flip mock ↔ live from the header badge (B2); the switch
  is in memory and reverts to `.env`'s `LLM_MODE` on restart.
- Outbound HTTPS to `api.anthropic.com` must be allowed — the default security group allows all
  outbound traffic, and the instance is in a public subnet, so no NAT gateway is needed.
- If a live call fails validation the app retries once, then falls back to the mock narrative, so a
  demo does not break on a bad response.

To go back: `sudo -u archoffice sed -i 's/^LLM_MODE=.*/LLM_MODE=mock/' /opt/arch-office/.env` and
restart. To remove the key entirely, blank `ANTHROPIC_API_KEY` too.

---

## 8. Operations

### 8.1 Day-to-day commands

| Task | Command |
|---|---|
| Status | `systemctl status arch-office caddy` |
| App logs (JSON lines) | `sudo journalctl -u arch-office -f` |
| Caddy / certificate logs | `sudo journalctl -u caddy -f` |
| Restart the app | `sudo systemctl restart arch-office` |
| Reload Caddy after editing the Caddyfile | `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy` |
| Back up now | `sudo /usr/local/bin/arch-office-backup` (after §8.4) |
| Disk space | `df -h /` |

### 8.2 Deploy the latest code

```bash
cd /opt/arch-office
sudo -u archoffice bash -c '
  set -e
  git pull --ff-only
  .venv/bin/pip install -r requirements.txt -q
  cd frontend && npm ci --no-audit --no-fund && npm run build
'
sudo systemctl restart arch-office      # picks up the new UI (C4)
```

A few seconds of downtime; the tenant databases are kept. If the release changed the data model,
follow it with a reset (§8.3).

### 8.3 Reset the demo data

Regenerates both tenants from the seed, the same as `make reset` on a laptop. **Every approval,
decision and audit event recorded on the server is discarded** — back up first if you want them.

```bash
cd /opt/arch-office
sudo systemctl stop arch-office
# optional: move the demo to today's date first (C3)
# sudo -u archoffice sed -i "s/^DEMO_TODAY=.*/DEMO_TODAY=$(date +%F)/" .env
sudo -u archoffice bash -c 'PYTHONPATH=backend:. .venv/bin/python -m data_gen.generate --all'
sudo systemctl start arch-office
```

### 8.4 Backups

The two `data/*.db` files are the system of record for everything the demo changes. `sqlite3 .backup`
takes a consistent copy while the app is running (WAL mode, C1).

**Nightly on-server backup, 7 days kept:**

```bash
sudo tee /usr/local/bin/arch-office-backup >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
DEST=/var/backups/arch-office
STAMP=$(date -u +%Y-%m-%d)
mkdir -p "$DEST"
for db in /opt/arch-office/data/*.db; do
  name=$(basename "$db" .db)
  sqlite3 "$db" ".backup '$DEST/$name-$STAMP.db'"
  gzip -f "$DEST/$name-$STAMP.db"
  if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
    aws s3 cp --only-show-errors "$DEST/$name-$STAMP.db.gz" "s3://$BACKUP_S3_BUCKET/backups/$name-$STAMP.db.gz"
  fi
done
find "$DEST" -name '*.db.gz' -mtime +7 -delete
EOF
sudo chmod 755 /usr/local/bin/arch-office-backup

echo '15 1 * * * root /usr/local/bin/arch-office-backup >> /var/log/arch-office-backup.log 2>&1' \
  | sudo tee /etc/cron.d/arch-office
sudo /usr/local/bin/arch-office-backup && ls -l /var/backups/arch-office
```

**Optional off-server copy in S3:**

1. **S3 → Create bucket** → `arch-office-backups-<account-id>`, same region, **Block all public
   access** on → **Create bucket**. Bucket → **Management → Create lifecycle rule** → *Expire current
   versions of objects* after **30 days**.
2. IAM → Roles → `arch-office-ec2` → **Add permissions → Create inline policy → JSON**:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "s3:PutObject",
       "Resource": "arn:aws:s3:::arch-office-backups-<account-id>/backups/*"
     }]
   }
   ```

   Name it `write-backups`.
3. On the server:

   ```bash
   sudo snap install aws-cli --classic
   BUCKET=arch-office-backups-<account-id>
   echo "15 1 * * * root BACKUP_S3_BUCKET=$BUCKET /usr/local/bin/arch-office-backup >> /var/log/arch-office-backup.log 2>&1" \
     | sudo tee /etc/cron.d/arch-office
   sudo BACKUP_S3_BUCKET=$BUCKET /usr/local/bin/arch-office-backup    # files appear under backups/
   ```

**Restore:**

```bash
sudo systemctl stop arch-office
gunzip -c /var/backups/arch-office/northgrid-YYYY-MM-DD.db.gz \
  | sudo -u archoffice tee /opt/arch-office/data/northgrid.db >/dev/null
sudo rm -f /opt/arch-office/data/northgrid.db-wal /opt/arch-office/data/northgrid.db-shm
sudo systemctl start arch-office
```

### 8.5 Stop and start to save money

EC2 bills the instance only while it runs; the 20 GB disk (~USD 1.60/month) is billed always. An
associated Elastic IP is free of extra charge while the instance runs, ~USD 3.60/month while it is
stopped.

* **Stop:** EC2 → instance → **Instance state → Stop instance**. Data is kept.
* **Start:** **Instance state → Start instance**. The app and Caddy start by themselves in 1–2 minutes.

With an Elastic IP nothing else is needed. **Without one**, the IP — and so the `sslip.io` name —
changes on every start. Install this once and the server moves its own address at boot, before Caddy
starts; Caddy then fetches a certificate for the new name on the first visit:

```bash
sudo tee /usr/local/bin/arch-office-set-address >/dev/null <<'EOF'
#!/usr/bin/env bash
# Point the Caddy site at <current-public-ip>.sslip.io. Leaves a custom domain alone.
set -euo pipefail
CF=/etc/caddy/Caddyfile
CUR=$(head -1 "$CF" | awk '{print $1}')
case "$CUR" in *.sslip.io) ;; *) exit 0 ;; esac
TOKEN=$(curl -sf -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
IP=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
NEW=${IP//./-}.sslip.io
[ "$CUR" = "$NEW" ] && exit 0
sed -i "1s/^${CUR//./\\.} /$NEW /" "$CF"
sed -i "s#^URL: .*#URL:      https://$NEW#" /root/arch-office-credentials.txt 2>/dev/null || true
echo "sslip.io address moved: $CUR -> $NEW"
EOF
sudo chmod 755 /usr/local/bin/arch-office-set-address

sudo tee /etc/systemd/system/arch-office-address.service >/dev/null <<'EOF'
[Unit]
Description=Move the Caddy sslip.io address to the current public IP
After=network-online.target
Wants=network-online.target
Before=caddy.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/arch-office-set-address

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable arch-office-address
```

After a start, read the new address with `sudo cat /root/arch-office-credentials.txt`, or take the new
*Public IPv4 address* from the console and replace the dots with dashes. The password is unchanged.

> Never choose **Terminate** unless you want to delete the server and its data.

### 8.6 Use your own domain instead of sslip.io

1. At your DNS provider, create an **A record** `archoffice.example.com → <public-ip>` (the Elastic IP).
2. On the server:

   ```bash
   sudo sed -i -E '1s/^\S+/archoffice.example.com/' /etc/caddy/Caddyfile
   sudo sed -i 's#^URL: .*#URL:      https://archoffice.example.com#' /root/arch-office-credentials.txt
   sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
   ```

Caddy fetches a certificate for the new name on the first visit. The boot-time script (§8.5) leaves a
custom domain alone.

### 8.7 Change the password

```bash
NEW_PASSWORD='choose-a-new-one'
HASH=$(caddy hash-password --plaintext "$NEW_PASSWORD")
sudo sed -i -E "s#^(\s+admin) .*#\1 $HASH#" /etc/caddy/Caddyfile     # replace admin if you chose another user
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
sudo sed -i "s#^Password: .*#Password: $NEW_PASSWORD#" /root/arch-office-credentials.txt
```

---

## 9. Sizing and cost

Approximate on-demand rates in us-east-1; check the [AWS Pricing Calculator](https://calculator.aws)
for your region before quoting a number to anyone. At runtime the app uses ~120 MB of memory; the
size is driven by the one-off UI build.

| Type | vCPU / RAM | ~USD / month 24×7 | Notes |
|---|---|---|---|
| t3a.micro | 2 / 1 GB | ~7 | Runs the app, but the UI build crawls on swap. Fine if you resize up for the build and back down |
| **t3a.small** | 2 / 2 GB | **~14** | **Recommended.** Builds in a few minutes with the 2 GB swap |
| t3a.medium | 2 / 4 GB | ~27 | Faster builds; a larger audience using it at once |
| t4g.small | 2 / 2 GB (Arm/Graviton) | ~12 | Cheaper. Choose the **64-bit (Arm)** Ubuntu image; every step is unchanged |
| t3.small | 2 / 2 GB | ~15 | Where `t3a` is not offered |

Plus: 20 GB gp3 disk **~1.60**, public IPv4 / Elastic IP **~3.60**.

| Usage (t3a.small) | ~USD / month |
|---|---|
| Running 24×7 | ~19 |
| Business hours only (~50 h/week) | ~7 |
| Stopped | ~5 (disk + Elastic IP; ~1.60 without an Elastic IP) |

Live LLM mode adds Anthropic API usage, billed by Anthropic. S3 backups cost cents.

---

## 10. Teardown

1. EC2 → instance → **Instance state → Terminate** (deletes the server and its disk — back up first).
2. EC2 → **Elastic IPs** → select → **Release Elastic IP address**. *An unattached Elastic IP keeps
   billing — it is the thing people forget.*
3. EC2 → **Security Groups** → delete `arch-office`; **Key pairs** → delete `arch-office` if you made one.
4. IAM → **Roles** → delete `arch-office-ec2`.
5. S3 (if used) → empty and delete `arch-office-backups-<account-id>`.

---

## 11. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| **Browser times out / connection refused** | Security group lacks 80 or 443 from your network; instance not *Running*; `systemctl status caddy` not *active* |
| **Certificate warning, or `ERR_SSL_PROTOCOL_ERROR`, on first visit** | Certificate not issued yet — wait a minute and reload. Still failing: `sudo journalctl -u caddy --since -10min`. Port 80 must be open to *Anywhere*, and the name must match the **current** public IP (after a stop/start without an Elastic IP, see §8.5). `sslip.io` is a free shared service; if Let's Encrypt rate-limits it, use your own domain (§8.6) |
| **`502 Bad Gateway` after signing in** | The app is not running: `sudo journalctl -u arch-office -n 100`. Usual causes: a typo in `.env` (e.g. `DEMO_TODAY` not `YYYY-MM-DD`), or `pip install` did not finish |
| **`{"detail":"Not Found"}` at `/`** | The UI was not built when the service started (C4): `ls /opt/arch-office/frontend/dist/index.html`, re-run the build from §5.2, then restart |
| **UI loads, panels show `503 … has no data yet`** | `data/*.db` missing (C2): re-run the generator line from §5.2 as `archoffice` |
| **Password prompt keeps reappearing** | Wrong user name or password, or the Caddyfile was edited without a reload. `sudo cat /root/arch-office-credentials.txt`; change it per §8.7 |
| **Session Manager: instance not listed / "not connected"** | IAM role `arch-office-ec2` with `AmazonSSMManagedInstanceCore` not attached (instance → *Actions → Security → Modify IAM role*), or the instance has no outbound internet. Wait 2 minutes after attaching |
| **`npm run build` ends with `Killed`** | Out of memory — `swapon --show` must list `/swapfile` (§4); or build on t3a.medium |
| **`pip install` fails** | Python older than 3.12 — use the Ubuntu 24.04 image |
| **Live mode still shows mock narratives** | `curl -s 127.0.0.1:8000/api/health` must say `live`; check the key in `.env`, restart, and look for `arch_office.llm` lines in `journalctl -u arch-office` |
| **Approvals or audit events vanished** | Someone reset a tenant (§6.4, B2) or ran §8.3. Restore from §8.4 |
| **Disk full** | `sudo journalctl --vacuum-size=200M`; delete old backups; or EC2 → Volumes → *Modify* → larger, then `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1` |
| **S3 backup: `AccessDenied` / `Unable to locate credentials`** | Inline policy missing from the role, or bucket name in the policy differs from the cron line |

---

## 12. Summary — the honest position

The Architecture Office runs on AWS today, **without code changes**, as a **password-protected demo on
one EC2 instance**: Caddy for HTTPS and the password, a free `sslip.io` name, one uvicorn process,
SQLite on the instance disk, nightly backups. It costs about as much as a lunch a month and can be
stopped between demos.

It is **not** ready to be a multi-user or client-data system, and the reason is B1: the app has no
notion of who is calling it, so the shared password is the entire access model and the audit trail
records claimed identities. Scaling beyond one server is blocked by C1 (SQLite files and in-memory
state). Both are known prototype boundaries listed under *Out of scope* in the README — no amount of
AWS configuration substitutes for them, and none is needed for what this deployment is for.

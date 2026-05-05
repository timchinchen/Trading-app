# AWS EC2 deployment (bare-bones, no Docker, remote LLM only)

This is a minimal single-user setup for a small EC2 instance where you run
backend + frontend directly on the host and access the app via instance URL.

This guide assumes:

- one EC2 host
- no Docker
- remote LLM provider (OpenAI / Hugging Face / Cohere)
- process management with `nohup` (or `systemd` equivalent)

---

## 0) Instance type and assumptions

- Works for low-cost instances like `t3.micro` / `t4g.micro`.
- Keep `AGENT_ENABLED=false` at first until you confirm CPU/RAM headroom.
- Use remote LLM APIs only on micro.

---

## 1) Launch EC2 and networking

Use Ubuntu 24.04 LTS (or 22.04 LTS).

Security Group inbound:

- `5173/tcp` from your IP (frontend)
- `8000/tcp` from your IP (backend API)
- `22/tcp` from your IP (SSH), or use Session Manager

Attach an Elastic IP if possible, so your URL stays stable.

---

## 2) Install runtime packages

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip nodejs npm
python3 --version
node --version
npm --version
```

---

## 3) Clone app and configure backend env

```bash
git clone <your-repo-url> trading-app
cd trading-app
cp backend/.env.example backend/.env
```

Edit `backend/.env` (minimum):

```env
APP_MODE=paper
ALPACA_PAPER_KEY=...
ALPACA_PAPER_SECRET=...
JWT_SECRET=<long-random-secret>
CORS_ORIGIN=http://<EC2_PUBLIC_IP_OR_DNS>:5173
```

Use remote provider (example OpenAI):

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

For internet exposure, recommended:

```env
REGISTRATION_ENABLED=true
```

Create your account first, then disable it in Settings after first login.

---

## 4) Install backend deps and run backend (nohup)

```bash
cd /home/ubuntu/trading-app/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > ../backend.log 2>&1 &
```

Check:

```bash
curl http://127.0.0.1:8000/health
```

---

## 5) Install frontend deps and run frontend (nohup)

```bash
cd /home/ubuntu/trading-app/frontend
npm install
nohup npm run dev -- --host 0.0.0.0 --port 5173 > ../frontend.log 2>&1 &
```

Open:

- `http://<EC2_PUBLIC_IP_OR_DNS>:5173`

Notes:

- `npm run dev` is simplest for one-user usage.
- If you want a slightly more stable mode without Docker:
  - `npm run build`
  - `nohup npm run preview -- --host 0.0.0.0 --port 5173 > ../frontend.log 2>&1 &`

---

## 6) Process management (nohup and equivalent)

### View running processes

```bash
ps -ef | rg "uvicorn|vite|node"
```

### Tail logs

```bash
tail -f /home/ubuntu/trading-app/backend.log
tail -f /home/ubuntu/trading-app/frontend.log
```

### Restart quickly

```bash
pkill -f "uvicorn app.main:app"
pkill -f "vite|npm run dev|npm run preview"
cd /home/ubuntu/trading-app/backend
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > ../backend.log 2>&1 &
cd /home/ubuntu/trading-app/frontend
nohup npm run dev -- --host 0.0.0.0 --port 5173 > ../frontend.log 2>&1 &
```

### Equivalent (recommended): systemd services

Use `systemd` if you want auto-restart on reboot/crash.

Backend service (`/etc/systemd/system/trading-backend.service`):

```ini
[Unit]
Description=Trading app backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/trading-app/backend
ExecStart=/home/ubuntu/trading-app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Frontend service (`/etc/systemd/system/trading-frontend.service`):

```ini
[Unit]
Description=Trading app frontend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/trading-app/frontend
ExecStart=/usr/bin/npm run dev -- --host 0.0.0.0 --port 5173
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trading-backend trading-frontend
sudo systemctl status trading-backend trading-frontend
```

---

## 7) Remote shell access

Preferred: AWS Session Manager (no public SSH required)

```bash
aws ssm start-session --target <INSTANCE_ID>
```

Alternative:

```bash
ssh -i <key>.pem ubuntu@<EC2_PUBLIC_IP_OR_DNS>
```

---

## 8) Post-setup hardening checklist

- Keep `APP_MODE=paper` until fully validated.
- In Settings, disable registration after your account is created.
- Restrict Security Group rules to your IP only.
- Back up `backend/trading.db` periodically.
- If exposing broadly, add a reverse proxy + HTTPS.

# Raspberry Pi deployment (frontend + backend, remote LLM only)

This guide deploys the app on a Raspberry Pi without Docker and without local
LLM inference. The Pi runs only:

- FastAPI backend (`:8000`)
- Vite frontend (`:5173`)
- Remote LLM APIs (OpenAI / Hugging Face / Cohere)

---

## 0) Recommended Pi + OS

- Raspberry Pi 4 (4GB+) or Pi 5 (recommended)
- Raspberry Pi OS Bookworm **64-bit**
- 32GB+ microSD (A2) or USB SSD
- Stable network + static DHCP lease if possible

If you only have 2GB RAM, keep `AGENT_ENABLED=false` initially and turn it on
after confirming stability.

---

## 1) Update OS and install base packages

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git python3 python3-venv python3-pip curl ca-certificates gnupg
```

Install Node.js 20 (works well with current Vite versions on ARM64):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

Verify:

```bash
python3 --version
node --version
npm --version
```

---

## 2) Clone the repo and create backend env

```bash
git clone https://github.com/timchinchen/Trading-app.git
cd Trading-app
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
APP_MODE=paper
ALPACA_PAPER_KEY=...
ALPACA_PAPER_SECRET=...
JWT_SECRET=<long-random-secret>
CORS_ORIGIN=http://<PI_LAN_IP>:5173
REGISTRATION_ENABLED=true
```

Set **remote LLM provider only** (example: OpenAI):

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Alternative providers:

- Hugging Face: `LLM_PROVIDER=huggingface`
- Cohere: `LLM_PROVIDER=cohere`

Do not configure Ollama on Pi for this deployment profile.

---

## 3) Backend setup and run

```bash
cd ~/Trading-app/backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Quick health check from another shell:

```bash
curl http://127.0.0.1:8000/health
```

---

## 4) Frontend setup and run

Use Vite dev server for a simple single-user deployment (includes working API
proxy behavior to backend):

```bash
cd ~/Trading-app/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open:

- `http://<PI_LAN_IP>:5173`

---

## 5) Keep both processes running (systemd)

Create backend service:

`/etc/systemd/system/trading-backend.service`

```ini
[Unit]
Description=Trading app backend
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/Trading-app/backend
ExecStart=/home/pi/Trading-app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Create frontend service:

`/etc/systemd/system/trading-frontend.service`

```ini
[Unit]
Description=Trading app frontend (vite dev server)
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/Trading-app/frontend
ExecStart=/usr/bin/npm run dev -- --host 0.0.0.0 --port 5173
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trading-backend trading-frontend
sudo systemctl status trading-backend trading-frontend
```

Logs:

```bash
journalctl -u trading-backend -f
journalctl -u trading-frontend -f
```

---

## 6) First login + lock down

1. Open `http://<PI_LAN_IP>:5173`
2. Register your first user
3. In Settings, disable registration (`REGISTRATION_ENABLED=false`) for safety

If exposed beyond LAN, put Nginx/Caddy in front with HTTPS and firewall rules.

---

## 7) Update workflow

```bash
cd ~/Trading-app
git pull origin main
cd backend && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install
sudo systemctl restart trading-backend trading-frontend
```

---

## 8) Raspberry Pi troubleshooting

### Low memory during installs

Add temporary 2GB swap:

```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
free -h
```

After setup, you can lower swap back (for SD card longevity) if desired.

### Find Pi IP quickly

```bash
hostname -I
```

### Service did not start

```bash
sudo systemctl status trading-backend trading-frontend --no-pager
journalctl -u trading-backend -n 200 --no-pager
journalctl -u trading-frontend -n 200 --no-pager
```

# AWS EC2 deployment (simple, single-host)

This guide covers a minimal deployment on one EC2 instance using Docker Compose.

It includes two model options:

1. **Local Ollama on the EC2 host**
2. **Remote hosted models (OpenAI / Hugging Face / Cohere)**

---

## 0) Instance sizing (important if you want micro)

- **`t4g.micro` / `t3.micro` (1 GiB RAM)**: use **remote hosted models** only.
  - Running `llama3.1:8b` locally is not realistic on micro.
- **If you want local Ollama**:
  - practical minimum is usually **`t3.small` or `t4g.small`** for very small models.
  - for `llama3.1:8b`, use a larger box (CPU-only will still be slow).

If your priority is low cost + reliability, pick micro + remote model provider.

---

## 1) Launch EC2

Use Ubuntu 24.04 LTS (or 22.04 LTS), then:

- Attach an Elastic IP (recommended).
- Security Group inbound:
  - `5173/tcp` from your IP (frontend)
  - `8000/tcp` from your IP (backend API, optional if frontend is enough)
  - `22/tcp` only if you plan to SSH directly

> For production internet exposure, put this behind TLS/reverse proxy and restrict inbound rules further.

---

## 2) Install Docker and Git on EC2

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
sudo apt-get update && sudo apt-get install -y git
docker --version
docker compose version
```

---

## 3) Get the code and prepare env

```bash
git clone <your-repo-url> trading-app
cd trading-app
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at least:

- `JWT_SECRET` (long random string)
- Alpaca keys (`ALPACA_PAPER_KEY`, `ALPACA_PAPER_SECRET`)
- `APP_MODE=paper` initially

Also set CORS for remote use:

```env
CORS_ORIGIN=http://<EC2_PUBLIC_IP_OR_DNS>:5173
```

---

## 4) Choose model option

### Option A: Local Ollama on EC2 host

Install Ollama on the host:

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama pull llama3.1:8b
```

Point backend container to host Ollama in `backend/.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://172.17.0.1:11434
OLLAMA_MODEL=llama3.1:8b
```

### Option B: Remote hosted model APIs (recommended for micro)

Use any supported provider:

- OpenAI
- Hugging Face
- Cohere

Example (OpenAI) in `backend/.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

You can also keep agent analysis on a cheaper provider and set Deep Analysis separately (`DEEP_LLM_*` vars).

---

## 5) Build and run

Set frontend build URLs to your public address before starting:

```bash
export PUBLIC_HOST="<EC2_PUBLIC_IP_OR_DNS>"
VITE_API_URL="http://${PUBLIC_HOST}:8000" \
VITE_WS_URL="ws://${PUBLIC_HOST}:8000" \
docker compose up -d --build
```

Open:

- Frontend: `http://<PUBLIC_HOST>:5173`
- Backend health: `http://<PUBLIC_HOST>:8000/health`

---

## 6) Remote console access (recommended approach)

### Preferred: AWS Systems Manager Session Manager (no open SSH needed)

1. Attach IAM role with `AmazonSSMManagedInstanceCore`.
2. Ensure SSM agent is running on the instance.
3. Connect:

```bash
aws ssm start-session --target <INSTANCE_ID>
```

This gives you a remote shell without exposing port 22 publicly.

### Alternative: SSH + tmux

```bash
ssh -i <key>.pem ubuntu@<PUBLIC_HOST>
tmux new -s trading
```

Use tmux for long maintenance sessions.

---

## 7) Crash/hang operations checklist

The backend now includes two protections:

- **Hard run timeout** via `AGENT_RUN_TIMEOUT_S` (default 1200s).
- **Stale run recovery on startup** (old `running` rows are auto-marked as error after restart).

Operational commands:

```bash
docker compose ps
docker compose logs -f backend
docker compose restart backend
```

If agent appears stuck:

1. Check backend logs.
2. Restart backend container.
3. Confirm `/agent/status` and `/health` recover.

---

## 8) Useful updates after first deploy

- Keep `APP_MODE=paper` until you validate behavior.
- Restrict Security Group ingress to your IP only.
- Add a reverse proxy + HTTPS if exposing publicly.
- Snapshot/backup `/data` volume regularly.

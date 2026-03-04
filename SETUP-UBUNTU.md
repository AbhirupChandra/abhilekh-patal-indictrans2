# Abhilekh Patal — IndicTrans2 Multilingual Search

## Ubuntu UAT/Production Setup Guide

Offline multilingual search for Abhilekh Patal using IndicTrans2 (AI4Bharat) + Apache Solr.
Translates Hindi/Indic queries to English for cross-language document retrieval.

---

## Target VM Specs

| Component | UAT VM (Actual) | Minimum Required |
|-----------|-----------------|------------------|
| **OS** | Ubuntu 22.04 LTS | Ubuntu 22.04+ |
| **Architecture** | aarch64 (ARM64, Neoverse-N2) | aarch64 or x86_64 |
| **CPU** | 4 vCPU | 2 vCPU |
| **RAM** | 32 GB | 4 GB (8 GB recommended) |
| **Disk** | — | 20 GB SSD minimum |
| **GPU** | None (CPU-only) | Not needed |

> The IndicTrans2 model is 200M parameters (~800 MB in memory). CPU inference takes 200-500ms per translation — fast enough for search autocomplete.

---

## Architecture

```
Browser → Nginx (:80)
            ├── /*          → Web Proxy (:8083) → static HTML/CSS/JS
            ├── /solr/*     → Web Proxy (:8083) → Solr (10.16.40.75:8983)
            ├── /translate  → Gunicorn  (:5002) → IndicTrans2 model
            └── /expand     → Gunicorn  (:5002) → Hindi synonym dictionary
```

**3 services:**
1. **IndicTrans2 Translation** (port 5002) — Gunicorn + PyTorch model
2. **Web Proxy** (port 8083) — serves frontend + proxies Solr requests
3. **Nginx** (port 80) — reverse proxy, ties everything together

---

## Step 1: System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    build-essential git curl wget nginx \
    python3.12 python3.12-venv python3.12-dev \
    libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libffi-dev liblzma-dev
```

If `python3.12` is not available:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

Verify:
```bash
python3.12 --version   # Should print Python 3.12.x
nginx -v               # Should print nginx/1.x.x
```

---

## Step 2: Clone the Repository

```bash
sudo mkdir -p /opt/abhilekh
sudo chown $USER:$USER /opt/abhilekh
cd /opt/abhilekh
git clone https://github.com/AbhirupChandra/abhilekh-patal-indictrans2.git .
```

---

## Step 3: Python Environment + Dependencies

```bash
cd /opt/abhilekh
python3.12 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install gunicorn
```

### ARM64 (aarch64) Note

PyTorch ships official aarch64 wheels. If `pip install torch` fails on ARM64:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

This installs the CPU-only build (~200 MB instead of ~2 GB).

Verify PyTorch:
```bash
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CPU threads: {torch.get_num_threads()}')"
```

---

## Step 4: Download IndicTrans2 Model

First-time download of the 200M parameter model from HuggingFace (~913 MB):

```bash
source /opt/abhilekh/.venv/bin/activate
python3 -c "
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
print('Downloading tokenizer...')
AutoTokenizer.from_pretrained('ai4bharat/indictrans2-indic-en-dist-200M', trust_remote_code=True)
print('Downloading model (~913MB)...')
AutoModelForSeq2SeqLM.from_pretrained('ai4bharat/indictrans2-indic-en-dist-200M', trust_remote_code=True)
print('Done! Model cached at ~/.cache/huggingface/')
"
```

> **Offline alternative:** If the VM has no internet, download on a machine with internet and copy:
> ```bash
> # On machine with internet:
> scp -r ~/.cache/huggingface/hub/models--ai4bharat--indictrans2-indic-en-dist-200M user@vm:~/.cache/huggingface/hub/
> ```

---

## Step 5: Smoke Test

Quick test to verify everything works before setting up services:

```bash
source /opt/abhilekh/.venv/bin/activate
cd /opt/abhilekh/implementation_files

# Start in foreground (will take 30-60s to load model)
python3 indictrans2_translation_service.py &
TRANS_PID=$!

# Wait for model to load
sleep 60

# Test translation
curl -s -X POST http://localhost:5002/translate \
  -H "Content-Type: application/json" \
  -d '{"text":"गांधी","src_lang":"hin_Deva","tgt_lang":"eng_Latn"}'
# Expected: {"translated":"Gandhi","success":true,...}

# Test synonym expansion
curl -s -X POST http://localhost:5002/expand \
  -H "Content-Type: application/json" \
  -d '{"text":"गांधी"}'
# Expected: {"success":true,"synonyms":[...],...}

# Test Solr connectivity (from VM)
curl -s "http://10.16.40.75:8983/solr/search/select?q=*:*&rows=1&wt=json" | head -c 200
# Expected: Solr JSON response

# Kill test process
kill $TRANS_PID
```

---

## Step 6: Systemd Service — Translation API

```bash
sudo mkdir -p /var/log/indictrans2

sudo tee /etc/systemd/system/indictrans2.service > /dev/null <<'UNIT'
[Unit]
Description=IndicTrans2 Translation Service
After=network.target

[Service]
Type=notify
User=root
WorkingDirectory=/opt/abhilekh/implementation_files
ExecStart=/opt/abhilekh/.venv/bin/gunicorn \
    --bind 127.0.0.1:5002 \
    --workers 2 \
    --threads 1 \
    --timeout 120 \
    --graceful-timeout 30 \
    --max-requests 500 \
    --max-requests-jitter 50 \
    --preload \
    --access-logfile /var/log/indictrans2/access.log \
    --error-logfile /var/log/indictrans2/error.log \
    --log-level info \
    indictrans2_translation_service:app
Restart=always
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
UNIT
```

> **Why `--timeout 120`:** The first request after boot triggers model loading (~60s on ARM64 CPU).
> Gunicorn kills workers that don't respond within the timeout. After the model is loaded,
> subsequent requests complete in 200-500ms. You can lower this to `--timeout 30` after
> confirming the model loads within the boot window.

> **Why `--workers 2`:** Two workers so that if one is recycled (via `--max-requests`),
> the other can still serve requests. Each worker uses ~1 GB RAM (model + overhead).
> With 32 GB RAM this is not an issue.

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable indictrans2
sudo systemctl start indictrans2
```

**Wait ~60-90 seconds** for model to load on first boot, then verify:
```bash
sudo systemctl status indictrans2

curl -s -X POST http://localhost:5002/translate \
  -H "Content-Type: application/json" \
  -d '{"text":"भारत","src_lang":"hin_Deva","tgt_lang":"eng_Latn"}'
```

---

## Step 7: Systemd Service — Web Proxy

```bash
sudo tee /etc/systemd/system/abhilekh-web.service > /dev/null <<'UNIT'
[Unit]
Description=Abhilekh Patal Web Proxy Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/abhilekh/web_interface
ExecStart=/opt/abhilekh/.venv/bin/python3 server.py
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable abhilekh-web
sudo systemctl start abhilekh-web
```

Verify:
```bash
curl -s http://localhost:8083/abhilekh_search.html | head -3
```

---

## Step 8: Update Frontend Config for Production

The frontend JS points translation API to `localhost:5002` (direct). Behind Nginx, it should use relative paths:

```bash
cd /opt/abhilekh/web_interface

# Change http://localhost:5002/translate → /translate
sed -i "s|http://localhost:5002/translate|/translate|" abhilekh_search.js

# Verify the change
grep "translationServiceUrl" abhilekh_search.js
# Should show: translationServiceUrl: '/translate',
```

This makes all API calls go through Nginx instead of requiring port 5002 to be open.

---

## Step 9: Nginx Reverse Proxy

```bash
sudo tee /etc/nginx/sites-available/abhilekh > /dev/null <<'NGINX'
server {
    listen 80;
    server_name _;

    # Frontend + Solr proxy (via web proxy server)
    location / {
        proxy_pass http://127.0.0.1:8083;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }

    # Translation API
    location /translate {
        proxy_pass http://127.0.0.1:5002/translate;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 15s;
        proxy_connect_timeout 5s;
    }

    # Synonym expansion API
    location /expand {
        proxy_pass http://127.0.0.1:5002/expand;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 5s;
    }

    # Usage stats (restrict to localhost for security)
    location /usage {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:5002/usage;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/abhilekh /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

---

## Step 10: Final Verification

```bash
echo "=== Service Status ==="
sudo systemctl is-active indictrans2
sudo systemctl is-active abhilekh-web
sudo systemctl is-active nginx

echo ""
echo "=== Translation API ==="
curl -s -X POST http://localhost/translate \
  -H "Content-Type: application/json" \
  -d '{"text":"गांधी","src_lang":"hin_Deva","tgt_lang":"eng_Latn"}'

echo ""
echo ""
echo "=== Synonym Expansion ==="
curl -s -X POST http://localhost/expand \
  -H "Content-Type: application/json" \
  -d '{"text":"गांधी"}'

echo ""
echo ""
echo "=== Solr (via proxy) ==="
curl -s "http://localhost/solr/search/select?q=dc.title:%22gandhi%22&rows=1&wt=json" | head -c 300

echo ""
echo ""
echo "=== Frontend ==="
curl -s http://localhost/abhilekh_search.html | head -3
```

Then open in browser: `http://<VM-IP>/abhilekh_search.html`

---

## Operations

### View Logs

```bash
# Translation service
sudo journalctl -u indictrans2 -f --no-pager
tail -f /var/log/indictrans2/access.log
tail -f /var/log/indictrans2/error.log

# Web proxy
sudo journalctl -u abhilekh-web -f --no-pager

# Nginx
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### Restart Services

```bash
sudo systemctl restart indictrans2    # Translation API (takes ~60s to reload model)
sudo systemctl restart abhilekh-web   # Web proxy (instant)
sudo systemctl restart nginx          # Reverse proxy (instant)
```

### Usage Statistics

Built-in usage tracking via SQLite:
```bash
# Today's stats
curl -s http://localhost:5002/usage?view=daily | python3 -m json.tool

# Top queries today
curl -s http://localhost:5002/usage?view=top | python3 -m json.tool

# Monthly stats
curl -s http://localhost:5002/usage?view=monthly | python3 -m json.tool

# Recent requests
curl -s http://localhost:5002/usage?view=recent&limit=20 | python3 -m json.tool
```

### Update Code (Pull Latest)

```bash
cd /opt/abhilekh
git pull origin main

# If JS/HTML changed — no restart needed (static files served live)

# If Python service changed:
sudo systemctl restart indictrans2

# If server.py changed:
sudo systemctl restart abhilekh-web
```

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Translation returns 502 | Model still loading (~60s on first boot) | Wait and retry: `journalctl -u indictrans2 -f` |
| Solr returns empty/error | VM can't reach 10.16.40.75:8983 | `curl http://10.16.40.75:8983/solr/` to test connectivity |
| Nginx 502 Bad Gateway | Backend service down | `systemctl status indictrans2 abhilekh-web` |
| Worker killed (OOM) | Not enough RAM per worker | Reduce `--workers` to 1 in systemd unit |
| PyTorch install fails on ARM64 | Missing aarch64 wheel | `pip install torch --index-url https://download.pytorch.org/whl/cpu` |
| Model download hangs | No internet / firewall | Download on another machine, scp the HuggingFace cache |
| Hindi suggestions slow | Translation service cold start | First request loads model; subsequent ones are fast |
| `gunicorn: command not found` | Not installed in venv | `source .venv/bin/activate && pip install gunicorn` |

---

## File Structure

```
/opt/abhilekh/
├── requirements.txt                    # Python dependencies
├── setup.sh                            # macOS dev setup script
├── start_translation_service.sh        # Cross-platform launcher (dev)
├── SETUP-UBUNTU.md                     # This file
│
├── implementation_files/
│   ├── indictrans2_translation_service.py   # Flask app (translate + expand + usage)
│   ├── usage_tracker.py                     # SQLite usage logging
│   ├── hindi_synonyms.json                  # 449 Hindi synonym entries
│   └── usage.db                             # Auto-created SQLite database
│
└── web_interface/
    ├── abhilekh_search.html            # Main search page
    ├── abhilekh_search.css             # Styles
    ├── abhilekh_search.js              # Search logic + translation
    └── server.py                       # Static file server + Solr proxy
```

---

## Security Notes

- **Gunicorn** binds to `127.0.0.1:5002` (not `0.0.0.0`) — only accessible via Nginx
- **Usage endpoint** (`/usage`) is restricted to localhost in Nginx config
- **Solr** is accessed via the web proxy (no direct browser-to-Solr connection)
- **No secrets** in the codebase — model is public, no API keys needed
- Consider adding **rate limiting** in Nginx for production:
  ```nginx
  limit_req_zone $binary_remote_addr zone=translate:10m rate=10r/s;
  location /translate {
      limit_req zone=translate burst=20 nodelay;
      # ... existing proxy config ...
  }
  ```

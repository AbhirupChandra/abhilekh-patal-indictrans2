#!/bin/bash
# ============================================================
#  IndicTrans2 Project Setup Script
#  One-command setup for MacBook M3 Air
# ============================================================
#
#  Usage:  bash setup.sh
#
#  What this script does:
#    1. Installs Python 3.12 via pyenv (PyTorch needs Python <= 3.13)
#    2. Creates a virtual environment (.venv)
#    3. Installs all dependencies (PyTorch, IndicTrans2, Flask, etc.)
#    4. Downloads the IndicTrans2 model from HuggingFace (~913MB)
#    5. Verifies MPS (Apple Silicon GPU) availability
#    6. Prints instructions for running the services
# ============================================================

set -e  # Exit on any error

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_VERSION="3.12.10"

echo ""
echo "============================================================"
echo "  IndicTrans2 Project Setup"
echo "  Optimized for MacBook M3 Air (Apple Silicon)"
echo "============================================================"
echo ""

# ── Step 1: Check pyenv ──
echo "[1/6] Checking pyenv..."
if ! command -v pyenv &> /dev/null; then
    echo "ERROR: pyenv is not installed."
    echo "Install it with: brew install pyenv"
    echo "Then add to your shell profile:"
    echo '  eval "$(pyenv init -)"'
    exit 1
fi
echo "  pyenv found: $(pyenv --version)"

# ── Step 2: Install Python 3.12 via pyenv ──
echo ""
echo "[2/6] Ensuring Python $PYTHON_VERSION is installed..."
if pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
    echo "  Python $PYTHON_VERSION already installed via pyenv"
else
    echo "  Installing Python $PYTHON_VERSION (this may take a few minutes)..."
    pyenv install "$PYTHON_VERSION"
    echo "  Python $PYTHON_VERSION installed successfully"
fi

PYTHON_BIN="$(pyenv prefix $PYTHON_VERSION)/bin/python3"
echo "  Using: $PYTHON_BIN"
$PYTHON_BIN --version

# ── Step 3: Create virtual environment ──
echo ""
echo "[3/6] Creating virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "  .venv already exists, removing and recreating..."
    rm -rf "$VENV_DIR"
fi
$PYTHON_BIN -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
echo "  Virtual environment created at $VENV_DIR"
echo "  Python: $(python --version)"

# ── Step 4: Install dependencies ──
echo ""
echo "[4/6] Installing dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r "$PROJECT_DIR/requirements.txt"
echo "  All dependencies installed"

# ── Step 5: Download IndicTrans2 model ──
echo ""
echo "[5/6] Downloading IndicTrans2 model (~913MB)..."
echo "  Model: ai4bharat/indictrans2-indic-en-dist-200M"
echo "  This is a one-time download, be patient..."
python -c "
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
print('  Downloading tokenizer...')
AutoTokenizer.from_pretrained('ai4bharat/indictrans2-indic-en-dist-200M', trust_remote_code=True)
print('  Downloading model (~913MB)...')
AutoModelForSeq2SeqLM.from_pretrained('ai4bharat/indictrans2-indic-en-dist-200M', trust_remote_code=True)
print('  Model downloaded and cached successfully!')
"

# ── Step 6: Verify MPS (Apple Silicon GPU) ──
echo ""
echo "[6/6] Verifying Apple Silicon GPU (MPS) support..."
python -c "
import torch
print(f'  PyTorch version: {torch.__version__}')
print(f'  MPS available: {torch.backends.mps.is_available()}')
print(f'  MPS built: {torch.backends.mps.is_built()}')
if torch.backends.mps.is_available():
    # Quick MPS test
    x = torch.tensor([1.0, 2.0, 3.0], device='mps')
    print(f'  MPS test passed: tensor on MPS = {x}')
    print('  Apple Silicon GPU acceleration is READY!')
else:
    print('  WARNING: MPS not available. Will use CPU (slower).')
"

# ── Done! ──
echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  To run the IndicTrans2 project:"
echo ""
echo "  Terminal 1 (Translation Service):"
echo "    cd \"$PROJECT_DIR/implementation_files\""
echo "    source \"$VENV_DIR/bin/activate\""
echo "    python indictrans2_translation_service.py"
echo ""
echo "  Terminal 2 (Web Server):"
echo "    cd \"$PROJECT_DIR/web_interface\""
echo "    python server.py"
echo ""
echo "  Then open: http://localhost:8082/abhilekh_search.html"
echo ""
echo "  Side-by-side comparison:"
echo "    Google Translate: http://localhost:8081/abhilekh_search.html"
echo "    IndicTrans2:      http://localhost:8082/abhilekh_search.html"
echo ""
echo "============================================================"

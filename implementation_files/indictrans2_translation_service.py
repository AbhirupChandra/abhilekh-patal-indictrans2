#!/usr/bin/env python3
"""
IndicTrans2 Translation Service - OFFLINE (AI4Bharat)
Uses locally loaded IndicTrans2 model for Indic-to-English translation.

Optimized for Apple Silicon (M3 MacBook Air) with MPS acceleration.

Supports: Hindi, Bengali, Gujarati, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu
No internet required after initial model download!

Features:
  - /translate  — Query translation (Hindi -> English, etc.)
  - /expand     — Hindi synonym expansion from dictionary
  - /usage      — Admin endpoint for usage stats (localhost only)
  - Character limit enforcement (MAX_QUERY_LENGTH)
  - SQLite usage tracking (IP, query, chars, daily/monthly aggregates)

Usage:
    python indictrans2_translation_service.py
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import logging
import time
import json
import os

from usage_tracker import UsageTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# -- Configuration --
MAX_QUERY_LENGTH = 30
MODEL_NAME = "ai4bharat/indictrans2-indic-en-dist-200M"

# -- Initialize usage tracker (SQLite) --
usage_tracker = UsageTracker()

# -- Load Hindi synonym dictionary for synonym expansion --
HINDI_SYNONYMS = {}
_synonyms_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hindi_synonyms.json')
try:
    with open(_synonyms_path, 'r', encoding='utf-8') as _f:
        HINDI_SYNONYMS = json.load(_f)
    HINDI_SYNONYMS.pop('_comment', None)
    logger.info(f"Loaded {len(HINDI_SYNONYMS)} Hindi synonym entries from hindi_synonyms.json")
except FileNotFoundError:
    logger.warning("hindi_synonyms.json not found -- synonym expansion disabled")
except Exception as _e:
    logger.error(f"Failed to load Hindi synonyms: {_e}")

# Supported languages (IndicTrans2 uses FLORES codes natively)
SUPPORTED_LANGUAGES = [
    'hin_Deva',  # Hindi
    'ben_Beng',  # Bengali
    'guj_Gujr',  # Gujarati
    'kan_Knda',  # Kannada
    'mal_Mlym',  # Malayalam
    'mar_Deva',  # Marathi
    'ory_Orya',  # Odia
    'pan_Guru',  # Punjabi
    'tam_Taml',  # Tamil
    'tel_Telu',  # Telugu
    'eng_Latn',  # English
]


# -- Helper: Get real client IP (behind Nginx proxy) --
def get_client_ip():
    """
    Get the real client IP address.
    Behind Nginx, request.remote_addr is 127.0.0.1.
    Nginx passes the real IP via X-Real-IP or X-Forwarded-For headers.
    """
    ip = request.headers.get('X-Real-IP')
    if ip:
        return ip
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr


class IndicTrans2TranslationService:
    """IndicTrans2 translation service - works offline with MPS acceleration"""

    def __init__(self, model_name: str = MODEL_NAME):
        """Initialize IndicTrans2 model optimized for Apple Silicon"""

        logger.info("=" * 60)
        logger.info("IndicTrans2 Translation Service (AI4Bharat)")
        logger.info("=" * 60)
        logger.info(f"Model: {model_name}")

        try:
            # -- Device selection: MPS (Apple Silicon GPU) > CUDA > CPU --
            if torch.backends.mps.is_available():
                self.device = torch.device("mps")
                logger.info("Apple Silicon GPU (MPS) detected!")
            elif torch.cuda.is_available():
                self.device = torch.device("cuda")
                logger.info("NVIDIA GPU (CUDA) detected!")
            else:
                self.device = torch.device("cpu")
                logger.info("Using CPU (no GPU acceleration)")

            # -- Load IndicProcessor for pre/post-processing --
            logger.info("Loading IndicProcessor...")
            from IndicTransToolkit import IndicProcessor
            self.ip = IndicProcessor(inference=True)

            # -- Load tokenizer --
            logger.info("Loading tokenizer...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=True
            )

            # -- Load model --
            # CRITICAL: Must use float32 for MPS compatibility
            # float16 causes NaN outputs on MPS for seq2seq models
            # (PyTorch issue #116601)
            logger.info("Loading model (this may take 10-30 seconds)...")
            self.model = AutoModelForSeq2SeqLM.from_pretrained(
                model_name,
                trust_remote_code=True,
                torch_dtype=torch.float32  # MUST be float32 for MPS
                # NOTE: No flash_attention_2 -- not supported on MPS
            )

            # Move model to device and set eval mode
            self.model.to(self.device)
            self.model.eval()

            logger.info(f"Model loaded successfully on {self.device.type.upper()}")

            # -- Warmup: first inference on MPS is slow --
            logger.info("Running warmup translation...")
            warmup_start = time.time()
            self._translate_internal("test", "hin_Deva", "eng_Latn")
            warmup_time = round((time.time() - warmup_start) * 1000, 2)
            logger.info(f"Warmup complete ({warmup_time}ms)")

            if self.device.type == "mps":
                logger.info("Using Apple M-series GPU - Expect fast inference!")
            logger.info("OFFLINE MODE - No internet required!")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    def _translate_internal(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """
        Internal translation method. Returns translated text string.
        Raises exception on failure.
        """
        sentences = [text]

        # Preprocess using IndicProcessor
        batch = self.ip.preprocess_batch(sentences, src_lang=src_lang, tgt_lang=tgt_lang)

        # Tokenize
        inputs = self.tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt"
        ).to(self.device)

        # Generate translation (no gradient tracking for inference)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                num_beams=5,
                num_return_sequences=1,
                max_length=256
            )

        # Decode
        decoded = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)

        # Postprocess using IndicProcessor
        result = self.ip.postprocess_batch(decoded, lang=tgt_lang)

        return result[0].strip()

    def translate(self, text: str, src_lang: str = "hin_Deva",
                  tgt_lang: str = "eng_Latn"):
        """
        Translate text using IndicTrans2.

        Args:
            text: Input text
            src_lang: Source language (FLORES code: hin_Deva, ben_Beng, etc.)
            tgt_lang: Target language (default: eng_Latn for English)

        Returns:
            Translation result dictionary
        """
        start_time = time.time()

        try:
            # Validate language codes
            if src_lang not in SUPPORTED_LANGUAGES:
                return {
                    'success': False,
                    'error': f'Unsupported source language: {src_lang}',
                    'original': text
                }

            translation = self._translate_internal(text, src_lang, tgt_lang)

            elapsed_time = time.time() - start_time

            device_label = self.device.type.upper()
            return {
                'success': True,
                'original': text,
                'translated': translation,
                'src_lang': src_lang,
                'tgt_lang': tgt_lang,
                'processing_time_ms': round(elapsed_time * 1000, 2),
                'model': f'IndicTrans2 ({MODEL_NAME})',
                'mode': f'OFFLINE ({device_label})'
            }

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'original': text
            }


# Initialize translator globally
translator = None

def init_translator():
    """Initialize translator on first request (or at startup)"""
    global translator
    if translator is None:
        translator = IndicTrans2TranslationService()
    return translator


# ==============================================================
#  ENDPOINTS
# ==============================================================

@app.route('/')
def home():
    """Health check"""
    device_label = "unknown"
    if translator:
        device_label = translator.device.type.upper()
    return jsonify({
        'service': 'IndicTrans2 Translation Service',
        'status': 'running',
        'mode': f'OFFLINE ({device_label})',
        'model': MODEL_NAME,
        'supported_languages': SUPPORTED_LANGUAGES,
        'max_query_length': MAX_QUERY_LENGTH,
        'endpoints': ['/', '/translate', '/expand', '/usage'],
        'version': '1.1'
    })


@app.route('/translate', methods=['POST'])
def translate():
    """Translation endpoint with character limit and usage tracking"""
    start_time = time.time()
    client_ip = get_client_ip()

    try:
        data = request.get_json()

        if not data or 'text' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: text'
            }), 400

        text = data['text']
        src_lang = data.get('src_lang', 'hin_Deva')
        tgt_lang = data.get('tgt_lang', 'eng_Latn')

        # Character limit validation
        if len(text) > MAX_QUERY_LENGTH:
            elapsed = round((time.time() - start_time) * 1000, 2)
            try:
                usage_tracker.log_request(
                    ip_address=client_ip, endpoint='/translate',
                    query_text=text[:50], char_count=len(text),
                    response_status=400, response_time_ms=elapsed
                )
            except Exception:
                pass
            return jsonify({
                'success': False,
                'error': f'Query exceeds maximum length of {MAX_QUERY_LENGTH} characters. Received: {len(text)}.'
            }), 400

        # Validate languages
        if src_lang not in SUPPORTED_LANGUAGES:
            return jsonify({
                'success': False,
                'error': f'Unsupported source language: {src_lang}'
            }), 400

        # Initialize translator
        trans = init_translator()

        # Translate
        result = trans.translate(
            text=text,
            src_lang=src_lang,
            tgt_lang=tgt_lang
        )

        elapsed = round((time.time() - start_time) * 1000, 2)
        logger.info(f"Translated '{text}' -> '{result.get('translated', '')}' ({elapsed}ms) [IP: {client_ip}]")

        # Log usage
        try:
            usage_tracker.log_request(
                ip_address=client_ip, endpoint='/translate',
                query_text=text, char_count=len(text),
                response_status=200, response_time_ms=elapsed
            )
        except Exception as log_err:
            logger.warning(f"Usage logging failed: {log_err}")

        return jsonify(result)

    except Exception as e:
        elapsed = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Request failed: {e}")
        try:
            usage_tracker.log_request(
                ip_address=client_ip, endpoint='/translate',
                query_text=(data.get('text', '') if data else '')[:50],
                char_count=len(data.get('text', '')) if data else 0,
                response_status=500, response_time_ms=elapsed
            )
        except Exception:
            pass
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/expand', methods=['POST'])
def expand():
    """Synonym expansion endpoint with character limit and usage tracking"""
    start_time = time.time()
    client_ip = get_client_ip()

    try:
        data = request.get_json()

        if not data or 'text' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: text'
            }), 400

        text = data['text'].strip()

        # Character limit validation
        if len(text) > MAX_QUERY_LENGTH:
            elapsed = round((time.time() - start_time) * 1000, 2)
            try:
                usage_tracker.log_request(
                    ip_address=client_ip, endpoint='/expand',
                    query_text=text[:50], char_count=len(text),
                    response_status=400, response_time_ms=elapsed
                )
            except Exception:
                pass
            return jsonify({
                'success': False,
                'error': f'Query exceeds maximum length of {MAX_QUERY_LENGTH} characters. Received: {len(text)}.'
            }), 400

        # Look up synonyms in the Hindi dictionary
        synonyms = HINDI_SYNONYMS.get(text, [])

        elapsed = round((time.time() - start_time) * 1000, 2)
        logger.info(f"Expand '{text}' -> {len(synonyms)} synonyms ({elapsed}ms) [IP: {client_ip}]")

        # Log usage
        try:
            usage_tracker.log_request(
                ip_address=client_ip, endpoint='/expand',
                query_text=text, char_count=len(text),
                response_status=200, response_time_ms=elapsed
            )
        except Exception as log_err:
            logger.warning(f"Usage logging failed: {log_err}")

        return jsonify({
            'success': True,
            'original': text,
            'synonyms': synonyms,
            'has_synonyms': len(synonyms) > 0
        })

    except Exception as e:
        elapsed = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Expand request failed: {e}")
        try:
            usage_tracker.log_request(
                ip_address=client_ip, endpoint='/expand',
                query_text=(data.get('text', '') if data else '')[:50],
                char_count=len(data.get('text', '')) if data else 0,
                response_status=500, response_time_ms=elapsed
            )
        except Exception:
            pass
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/usage', methods=['GET'])
def usage_stats():
    """
    Admin endpoint -- view usage statistics.

    Query parameters:
      ?view=daily     -- today's stats (default)
      ?view=monthly   -- this month's stats
      ?view=recent    -- last 50 log entries
      ?view=top       -- top queries today
      ?date=2026-02-19  -- specific date for daily view
      ?month=2026-02    -- specific month for monthly view
      ?limit=100        -- number of entries for recent/top views

    Security: Do NOT proxy this through Nginx. Access via localhost only.
    """
    view = request.args.get('view', 'daily')

    try:
        if view == 'daily':
            target_date = request.args.get('date')
            stats = usage_tracker.get_daily_stats(target_date)
            return jsonify({'view': 'daily', **stats})

        elif view == 'monthly':
            target_month = request.args.get('month')
            stats = usage_tracker.get_monthly_stats(target_month)
            return jsonify({'view': 'monthly', **stats})

        elif view == 'recent':
            limit = int(request.args.get('limit', 50))
            logs = usage_tracker.get_recent_logs(limit)
            return jsonify({'view': 'recent', 'count': len(logs), 'logs': logs})

        elif view == 'top':
            limit = int(request.args.get('limit', 20))
            target_date = request.args.get('date')
            top = usage_tracker.get_top_queries(limit=limit, target_date=target_date)
            return jsonify({'view': 'top_queries', 'count': len(top), 'queries': top})

        else:
            return jsonify({'error': f'Unknown view: {view}'}), 400

    except Exception as e:
        logger.error(f"Usage stats failed: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  IndicTrans2 Translation Service v1.1")
    print("=" * 60)
    print(f"Model: {MODEL_NAME}")
    print("Mode: OFFLINE - No internet required after setup")
    print(f"Max query length: {MAX_QUERY_LENGTH} characters")
    print(f"Usage tracking: SQLite ({usage_tracker.db_path})")
    print("=" * 60)

    # Load model at startup (not lazy)
    print("\nLoading IndicTrans2 model (this may take 10-30 seconds)...")
    init_translator()

    print(f"\nStarting service on port 5002...")
    print("   This uses IndicTrans2 (AI4Bharat) - fully offline\n")

    app.run(
        host='0.0.0.0',
        port=5002,
        debug=False,
        threaded=True   # Allow concurrent requests (autocomplete + search)
    )

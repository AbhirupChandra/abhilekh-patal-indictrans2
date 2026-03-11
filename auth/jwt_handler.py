import jwt
import os
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev-secret-change-me-in-production')
ALGORITHM = 'HS256'

ACCESS_TOKEN_EXPIRY_HOURS = 24

def create_access_token(user_data):
    """
    Create a signed JWT token for an authenticated user.

    Args:
        user_data: dict from AuthManager.authenticate() —
                   contains id, username, full_name, role

    Returns:
        JWT token string (e.g., "eyJhbGci...")

    How it works:
        1. We build a "payload" dict with user info + expiry time
        2. jwt.encode() does three things:
           a. Base64-encodes the header ({"alg": "HS256", "typ": "JWT"})
           b. Base64-encodes the payload (our dict)
           c. Signs header.payload with SECRET_KEY using HMAC-SHA256
        3. Returns: header.payload.signature (three base64 strings joined by dots)
    """
    now = datetime.now(timezone.utc)

    payload = {
        # ── Standard JWT claims (registered claims) ──
        'exp': now + timedelta(hours=ACCESS_TOKEN_EXPIRY_HOURS),  # expiry time
        'iat': now,                                                # issued at
        'nbf': now,                                                # not valid before

        # ── Our custom claims (private claims) ──
        'sub': user_data['id'],           # subject — who this token belongs to
        'username': user_data['username'],
        'full_name': user_data['full_name'],
        'role': user_data['role']
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"Token created for user: {user_data['username']}")
    return token

def verify_token(token):
    """
    Decode and verify a JWT token.

    Args:
        token: the JWT string from the Authorization header

    Returns:
        The payload dict if token is valid.
        None if token is expired, tampered, or invalid.

    How verification works:
        1. jwt.decode() splits the token into header.payload.signature
        2. It re-signs header.payload with our SECRET_KEY
        3. If the new signature matches the token's signature → not tampered
        4. It checks 'exp' claim → if current time > exp → ExpiredSignatureError
        5. If everything passes → returns the decoded payload dict
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("Token verification failed: token expired")
        return None

    except jwt.InvalidTokenError as e:
        logger.warning(f"Token verification failed: {e}")
        return None
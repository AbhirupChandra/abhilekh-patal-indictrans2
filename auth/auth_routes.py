from flask import Blueprint, request, jsonify
import logging
from auth.auth_manager import AuthManager
from auth.jwt_handler import create_access_token

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')
auth_manager = AuthManager()

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login endpoint — verifies credentials and returns a JWT token.

    Request body (JSON):
        {
            "username": "abhirup",
            "password": "mypassword"
        }

    Success response (200):
        {
            "success": true,
            "token": "eyJhbGci...",
            "user": {
                "id": 1,
                "username": "abhirup",
                "full_name": "Abhirup Chandra",
                "role": "admin"
            }
        }

    Failure response (401):
        {
            "success": false,
            "error": "Invalid username or password"
        }

    Flow:
        1. Extract username + password from JSON body
        2. Call auth_manager.authenticate() → checks DB, verifies bcrypt hash
        3. If valid → create JWT token with user data → return token
        4. If invalid → return 401 (don't say WHICH field was wrong — security)
    """
    data = request.get_json()

    # ── Validate request body ──
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({
            'success': False,
            'error': 'Missing required fields: username and password'
        }), 400

    username = data['username'].strip()
    password = data['password']

    # ── Authenticate against DB ──
    user = auth_manager.authenticate(username, password)

    if user is None:
        # SECURITY: Never reveal whether username or password was wrong.
        # "Invalid username or password" prevents attackers from enumerating valid usernames.
        logger.warning(f"Failed login attempt for username: {username}")
        return jsonify({
            'success': False,
            'error': 'Invalid username or password'
        }), 401

    # ── Create JWT token ──
    token = create_access_token(user)

    logger.info(f"User logged in: {username}")

    return jsonify({
        'success': True,
        'token': token,
        'user': user
    }), 200
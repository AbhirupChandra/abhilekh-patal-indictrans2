from functools import wraps
from flask import request, jsonify
import logging

from auth.jwt_handler import verify_token

logger = logging.getLogger(__name__)

def token_required(f):
    """ Why functools.wraps?
        Without @wraps, the decorated function loses its original name.
        Flask uses function names to map URLs → functions (via endpoint names).
        If two decorated routes both appear as "wrapper", Flask crashes with
        "AssertionError: View function mapping is overwriting an existing
        endpoint function". @wraps preserves the original function name."""
    
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None

        # step 1 Extract token from header
        auth_header = request.headers.get('Authorization')

        if auth_header:
            parts = auth_header.split()

            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
            else:
                return jsonify(
                    {
                        'success': False,
                        'error': 'Invalid Authorization header format. Expected Bearer <token>'
                    }
                ), 401
            
        if token is None:
            return jsonify(
                {
                    'success': False,
                    'error': 'Authentication required. Please provide a valid token.'
                }
            ), 401
        
        # step 2 Verify the token
        payload = verify_token(token)
        
        if payload is None:
            return jsonify(
                {
                    'success': False,
                    'error': 'Token is invalid or expired. Please login again.'
                }
            ), 401
        
        # Step 3: Pass decoded user info to the route function
        # The route function receives `current_user` as its first argument
        return f(current_user=payload, *args, **kwargs)
    return wrapper
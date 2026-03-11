#!/usr/bin/env python3
"""
Test script — Verify the full auth flow works.
Run: python -m auth.test_auth (from project root)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.auth_manager import AuthManager
from auth.jwt_handler import create_access_token, verify_token

auth_manager = AuthManager()


def test_flow():
    print("=" * 50)
    print("JWT Auth — End-to-End Test")
    print("=" * 50)

    # Get first user from DB to test with
    conn = auth_manager._get_conn()
    try:
        first_user = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
    finally:
        conn.close()

    if not first_user:
        print("\nFAIL — No users in database. Run seed_users.py first.")
        return

    test_username = first_user['username']
    test_password = input(f"\nEnter password for '{test_username}' to test: ")

    # ── Test 1: Authenticate with correct credentials ──
    print("\n[Test 1] Authenticate with correct credentials")
    user = auth_manager.authenticate(test_username, test_password)
    if user:
        print(f"  PASS — Got user: {user}")
    else:
        print("  FAIL — authenticate() returned None. Wrong password?")
        return

    # ── Test 2: Authenticate with wrong password ──
    print("\n[Test 2] Authenticate with wrong password")
    bad_user = auth_manager.authenticate(test_username, 'wrongpassword')
    if bad_user is None:
        print("  PASS — Correctly rejected wrong password")
    else:
        print("  FAIL — Should have returned None")

    # ── Test 3: Authenticate with non-existent username ──
    print("\n[Test 3] Authenticate with non-existent username")
    ghost = auth_manager.authenticate('ghostuser', 'password')
    if ghost is None:
        print("  PASS — Correctly rejected unknown user")
    else:
        print("  FAIL — Should have returned None")

    # ── Test 4: Create JWT token ──
    print("\n[Test 4] Create JWT token")
    token = create_access_token(user)
    print(f"  Token: {token[:50]}...")
    print(f"  Length: {len(token)} chars")

    # ── Test 5: Verify valid token ──
    print("\n[Test 5] Verify valid token")
    payload = verify_token(token)
    if payload:
        print(f"  PASS — Decoded payload:")
        print(f"    sub (user id): {payload['sub']}")
        print(f"    username: {payload['username']}")
        print(f"    role: {payload['role']}")
        print(f"    expires: {payload['exp']}")
    else:
        print("  FAIL — verify_token returned None")

    # ── Test 6: Reject tampered token ──
    print("\n[Test 6] Reject tampered token")
    tampered = token[:-5] + "XXXXX"
    result = verify_token(tampered)
    if result is None:
        print("  PASS — Correctly rejected tampered token")
    else:
        print("  FAIL — Should have rejected tampered token")

    # ── Test 7: Reject garbage token ──
    print("\n[Test 7] Reject garbage token")
    result = verify_token("not.a.token")
    if result is None:
        print("  PASS — Correctly rejected garbage")
    else:
        print("  FAIL — Should have rejected garbage")

    print("\n" + "=" * 50)
    print("All tests complete!")
    print("=" * 50)


if __name__ == '__main__':
    test_flow()

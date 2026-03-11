#!/usr/bin/env python3
"""
Seed script — Create initial users in the database.
Run once: python -m auth.seed_users (from project root)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth.auth_manager import AuthManager

auth_manager = AuthManager()

# Define your 4 users here — change passwords before running!
USERS = [
    {
        'username': 'abhirup@cloudmojo.tech',
        'password': 'abhirup123',
        'full_name': 'Abhirup Chandra',
        'role': 'admin'
    },
    {
        'username': 'DG@nai.com',
        'password': 'dg123',
        'full_name': 'Director General',
        'role': 'admin'
    },
    {
        'username': 'adg@nai.com',
        'password': 'adg123',
        'full_name': 'Additional Director General',
        'role': 'admin'
    },
    {
        'username': 'user@nai.com',
        'password': 'user123',
        'full_name': 'Regular User',
        'role': 'user'
    },
]


def seed():
    """Insert all users. Skips if username already exists."""
    for user in USERS:
        if not user['username'] or not user['password']:
            print(f"Skipped: empty username or password")
            continue
        try:
            user_id = auth_manager.create_user(
                username=user['username'],
                password=user['password'],
                full_name=user['full_name'],
                role=user['role']
            )
            print(f"Created: {user['username']} (id={user_id}, role={user['role']})")
        except ValueError as e:
            print(f"Skipped: {e}")


if __name__ == '__main__':
    print("Seeding users...")
    print(f"Database: {auth_manager.db_path}")
    print("-" * 40)
    seed()
    print("-" * 40)
    print("Done!")

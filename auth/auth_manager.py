import sqlite3
import os
import logging
from datetime import datetime

import bcrypt

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'implementation_files', 'usage.db')


class AuthManager:
    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get('AUTH_DB_PATH', DEFAULT_DB_PATH)
        self._init_db()
        logger.info(f'Auth manager initialized: {self.db_path}')

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT,
                    role TEXT DEFAULT 'user',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_users_username
                    ON users(username);
                               """)
            conn.commit()
        finally:
            conn.close()

    #-----Bcrypt for hashing

    def _hash_password(self, plain_password):
        password_bytes = plain_password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    def _verify_password(self, plain_password, stored_hash):
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = stored_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    
    #-----User operation

    def create_user(self, username, password, full_name=None, role='user'):
        password_hash = self._hash_password(password)
        now = datetime.now().isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO users (username, password_hash, full_name, role, created_at)
                   VALUES (?, ?, ?, ?, ?)""", (username, password_hash, full_name, role, now)
            )
            conn.commit()
            user_id = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()['id']

            logger.info(f'User created: {username} (id={user_id})')
            return user_id
        except sqlite3.IntegrityError:
            raise ValueError(f'Username "{username}" already exists')
        finally:
            conn.close()

    def authenticate(self, username, password):
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
            ).fetchone()

            if row is None:
                return None
            if not self._verify_password(password, row['password_hash']):
                return None
            
            # Update last_login timestamp
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?", (datetime.now().isoformat(), row['id'])
            )
            conn.commit()

            # Return user info
            return{
                'id': row['id'],
                'username': row['username'],
                'full_name': row['full_name'],
                'role': row['role']
            }
        finally:
            conn.close()
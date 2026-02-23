#!/usr/bin/env python3
"""
Usage Tracker — SQLite-based request logging for Abhilekh Patal Translation Service.

Tracks: IP address, query text, character count, endpoint, response status, timing.
Provides: daily/monthly aggregates, recent logs, top queries, per-IP usage.

Thread/process safe: each method opens its own connection (safe for Gunicorn multi-worker).
Uses WAL mode for concurrent read/write performance.

Future: migrate to PostgreSQL/MySQL by swapping this module — same interface, different backend.
"""

import sqlite3
import os
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'usage.db'
)


class UsageTracker:
    """SQLite-based usage tracking for translation and synonym expansion requests."""

    def __init__(self, db_path=None):
        """
        Initialize the usage tracker.

        Args:
            db_path: Path to SQLite database file. Defaults to ./usage.db
                     beside this script. Can be overridden via USAGE_DB_PATH env var.
        """
        self.db_path = db_path or os.environ.get('USAGE_DB_PATH', DEFAULT_DB_PATH)
        self._init_db()
        logger.info(f"Usage tracker initialized: {self.db_path}")

    def _get_conn(self):
        """Get a new database connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    month TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    char_count INTEGER NOT NULL,
                    response_status INTEGER,
                    response_time_ms REAL
                );

                CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(date);
                CREATE INDEX IF NOT EXISTS idx_usage_month ON usage_log(month);
                CREATE INDEX IF NOT EXISTS idx_usage_ip ON usage_log(ip_address);
                CREATE INDEX IF NOT EXISTS idx_usage_query ON usage_log(query_text);
            """)
            conn.commit()
        finally:
            conn.close()

    def log_request(self, ip_address, endpoint, query_text, char_count,
                    response_status=200, response_time_ms=None):
        """
        Log a single API request.

        Args:
            ip_address: Client IP address
            endpoint: API endpoint (e.g., '/translate', '/expand')
            query_text: The user's query text
            char_count: Number of characters in the query
            response_status: HTTP status code of the response
            response_time_ms: Response time in milliseconds
        """
        now = datetime.utcnow()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO usage_log
                   (timestamp, date, month, ip_address, endpoint, query_text,
                    char_count, response_status, response_time_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now.strftime('%Y-%m-%dT%H:%M:%S'),
                    now.strftime('%Y-%m-%d'),
                    now.strftime('%Y-%m'),
                    ip_address,
                    endpoint,
                    query_text,
                    char_count,
                    response_status,
                    response_time_ms
                )
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to log usage: {e}")
        finally:
            conn.close()

    def get_daily_stats(self, target_date=None):
        """
        Get usage stats for a specific date.

        Args:
            target_date: Date string 'YYYY-MM-DD'. Defaults to today.

        Returns:
            dict with total_requests, total_chars, unique_ips, by_endpoint
        """
        if target_date is None:
            target_date = date.today().strftime('%Y-%m-%d')

        conn = self._get_conn()
        try:
            # Overall stats
            row = conn.execute(
                """SELECT COUNT(*) as total_requests,
                          COALESCE(SUM(char_count), 0) as total_chars,
                          COUNT(DISTINCT ip_address) as unique_ips
                   FROM usage_log WHERE date = ?""",
                (target_date,)
            ).fetchone()

            # Per-endpoint breakdown
            endpoints = conn.execute(
                """SELECT endpoint,
                          COUNT(*) as requests,
                          COALESCE(SUM(char_count), 0) as chars
                   FROM usage_log WHERE date = ?
                   GROUP BY endpoint""",
                (target_date,)
            ).fetchall()

            return {
                'date': target_date,
                'total_requests': row['total_requests'],
                'total_chars': row['total_chars'],
                'unique_ips': row['unique_ips'],
                'by_endpoint': [
                    {'endpoint': e['endpoint'], 'requests': e['requests'], 'chars': e['chars']}
                    for e in endpoints
                ]
            }
        finally:
            conn.close()

    def get_monthly_stats(self, target_month=None):
        """
        Get usage stats for a specific month.

        Args:
            target_month: Month string 'YYYY-MM'. Defaults to current month.

        Returns:
            dict with total_requests, total_chars, unique_ips, daily_breakdown
        """
        if target_month is None:
            target_month = date.today().strftime('%Y-%m')

        conn = self._get_conn()
        try:
            # Overall stats
            row = conn.execute(
                """SELECT COUNT(*) as total_requests,
                          COALESCE(SUM(char_count), 0) as total_chars,
                          COUNT(DISTINCT ip_address) as unique_ips
                   FROM usage_log WHERE month = ?""",
                (target_month,)
            ).fetchone()

            # Daily breakdown
            days = conn.execute(
                """SELECT date,
                          COUNT(*) as requests,
                          COALESCE(SUM(char_count), 0) as chars,
                          COUNT(DISTINCT ip_address) as ips
                   FROM usage_log WHERE month = ?
                   GROUP BY date ORDER BY date""",
                (target_month,)
            ).fetchall()

            return {
                'month': target_month,
                'total_requests': row['total_requests'],
                'total_chars': row['total_chars'],
                'unique_ips': row['unique_ips'],
                'daily_breakdown': [
                    {'date': d['date'], 'requests': d['requests'],
                     'chars': d['chars'], 'unique_ips': d['ips']}
                    for d in days
                ]
            }
        finally:
            conn.close()

    def get_recent_logs(self, limit=50):
        """
        Get the most recent log entries.

        Args:
            limit: Number of entries to return (default 50)

        Returns:
            List of log entry dicts
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT timestamp, ip_address, endpoint, query_text,
                          char_count, response_status, response_time_ms
                   FROM usage_log ORDER BY id DESC LIMIT ?""",
                (limit,)
            ).fetchall()

            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_top_queries(self, limit=20, target_date=None):
        """
        Get most frequent queries.

        Args:
            limit: Number of top queries to return
            target_date: Optional date filter 'YYYY-MM-DD'

        Returns:
            List of {query_text, count, total_chars} dicts
        """
        conn = self._get_conn()
        try:
            if target_date:
                rows = conn.execute(
                    """SELECT query_text,
                              COUNT(*) as count,
                              SUM(char_count) as total_chars
                       FROM usage_log WHERE date = ?
                       GROUP BY query_text ORDER BY count DESC LIMIT ?""",
                    (target_date, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT query_text,
                              COUNT(*) as count,
                              SUM(char_count) as total_chars
                       FROM usage_log
                       GROUP BY query_text ORDER BY count DESC LIMIT ?""",
                    (limit,)
                ).fetchall()

            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_ip_usage(self, ip_address, target_date=None):
        """
        Get total usage by a specific IP.

        Args:
            ip_address: IP address to look up
            target_date: Optional date filter 'YYYY-MM-DD'. Defaults to today.

        Returns:
            dict with total_requests, total_chars for that IP
        """
        if target_date is None:
            target_date = date.today().strftime('%Y-%m-%d')

        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT COUNT(*) as total_requests,
                          COALESCE(SUM(char_count), 0) as total_chars
                   FROM usage_log WHERE ip_address = ? AND date = ?""",
                (ip_address, target_date)
            ).fetchone()

            return {
                'ip_address': ip_address,
                'date': target_date,
                'total_requests': row['total_requests'],
                'total_chars': row['total_chars']
            }
        finally:
            conn.close()

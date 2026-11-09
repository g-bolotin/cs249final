import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "/data/node.db")

def init_db():
    """Initialize database with tables for artworks, tags, and message log."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artworks (
                id TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                artwork_id TEXT NOT NULL,
                tag_type TEXT NOT NULL,
                tag_value TEXT NOT NULL,
                FOREIGN KEY(artwork_id) REFERENCES artworks(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_log (
                msg_id TEXT PRIMARY KEY,
                direction TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload TEXT NOT NULL
            )
        """)
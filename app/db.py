import sqlite3
import os

# Helper to ensure path is dynamically updated instead of eval'd once on import
def get_db_path():
    return os.getenv("DB_PATH", "/data/node.db")

def init_db():
    """Initialize database with tables for artworks, tags, and message log."""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # Artwork information and media path
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artworks (
                id TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)

        # Tags under artwork
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                artwork_id TEXT NOT NULL,
                tag_type TEXT NOT NULL,
                tag_value TEXT NOT NULL,
                FOREIGN KEY(artwork_id) REFERENCES artworks(id)
            )
        """)

        # Log messages
        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_log (
                msg_id TEXT PRIMARY KEY,
                direction TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload TEXT NOT NULL
            )
        """)

        # Who a subscriber follows (either artist or artwork)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                subscriber_id TEXT NOT NULL,
                target_type TEXT NOT NULL CHECK(target_type IN ('artist', 'work')),
                target_value TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (subscriber_id, target_type, target_value)
            )
        """)

        # Local inbox for notifications, sent when a matching publish event arrives
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                subscriber_id TEXT NOT NULL,
                artwork_id TEXT NOT NULL,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at REAL NOT NULL
            )
        """)
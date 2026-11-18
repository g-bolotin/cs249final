import os
import time
import uuid
import json
import sqlite3
import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from app.db import init_db, get_db_path
from pydantic import BaseModel

# Node/Peer IDs
NODE_ID = os.getenv("NODE_ID", "node-local")
SEED_PEERS = [p for p in os.getenv("SEED_PEERS", "").split(",") if p]

# Image directory
IMAGE_DIR = os.getenv("IMAGE_DIR", "/data/images")

os.makedirs(IMAGE_DIR, exist_ok=True)
init_db()

# Logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("art-node")

def log_event(direction: str, endpoint: str, payload: dict):
    ts = time.time()
    entry = {
        "timestamp": ts,
        "node_id": NODE_ID,
        "direction": direction,
        "endpoint": endpoint,
        "payload": payload
    }
    logger.info(json.dumps(entry))
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO message_log VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), direction, endpoint, ts, json.dumps(payload))
        )


# TODO: Change title to whatever we decide to name the project
app = FastAPI(title=f"Pub/Sub Art Node ({NODE_ID})")

# Helper Functions
def queue_local_notifs(artwork_id: str, artist: str, title: str) -> list[str]:
    """
    Checks subscriptions table for anyone following specified artist
    or work. Inserts a 'queued' notification for each match.
    """
    ts = time.time()
    notified_users = []

    with sqlite3.connect(get_db_path()) as conn:
        # Look up artist or work in subscriptions
        # DISTINCT so that if a user follows an artist and their specific work, they'll only get 1 update
        rows = conn.execute(
            """
            SELECT DISTINCT subscriber_id FROM subscriptions
            WHERE (target_type = 'artist' AND target_value = ?)
               OR (target_type = 'work' AND target_value = ?)
            """,
            (artist, artwork_id)
        ).fetchall()

        # Create notification and queue into user inbox
        for (sub_id,) in rows:
            # Deterministic ID prevents duplicate notifications if a gossip message is processed twice
            notif_id = f"{sub_id}:{artwork_id}"
            cursor = conn.execute(
                "INSERT OR IGNORE INTO notifications VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                (notif_id, sub_id, artwork_id, artist, title, ts)
            )
            if cursor.rowcount > 0:
                notified_users.append(sub_id)

    # Log upon queueing notifs
    if notified_users:
        log_event("INTERNAL", "queue_notifications", {
            "artwork_id": artwork_id,
            "artist": artist,
            "notified_subscribers": notified_users
        })
    return notified_users

# GET Endpoints
# For node health checking
@app.get("/health")
async def health():
    log_event("RECV", "/health", {"status": "ok"})
    return {"node_id": NODE_ID, "status": "healthy", "peers": SEED_PEERS, "timestamp": time.time()}

# Get subscriber's notif inbox
@app.get("/notifications/{subscriber_id}")
async def get_notifs(subscriber_id: str):
    with sqlite3.connect(get_db_path()) as conn:
        rows = conn.execute(
            """
            SELECT id, artwork_id, artist, title, status, created_at
            FROM notifications
            WHERE subscriber_id = ?
            ORDER BY created_at DESC
            """,
            (subscriber_id,)
        ).fetchall()

    results = [
        {
            "id": r[0],
            "artwork_id": r[1],
            "artist": r[2],
            "title": r[3],
            "status": r[4],
            "created_at": r[5]
        }
        for r in rows
    ]
    return {"node_id": NODE_ID, "subscriber_id": subscriber_id, "notifications": results}

# POST Endpoints
# Publish artwork
@app.post("/publish")
async def publish(
    artist: str = Form(...),
    title: str = Form(...),
    tags: str = Form(...),  # comma-separated e.g. "franchise:journey,author:thatgamecompany,user:fantasylover"
    image: UploadFile = File(...)
):
    # Pull image file
    art_id = str(uuid.uuid4())
    ts = time.time()
    file_path = os.path.join(IMAGE_DIR, f"{art_id}_{image.filename}")
    with open(file_path, "wb") as f:
        f.write(await image.read())

    # Attach tags
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    with sqlite3.connect(get_db_path()) as conn:
        conn.execute("INSERT INTO artworks VALUES (?, ?, ?, ?, ?)", (art_id, artist, title, file_path, ts))
        for t in tag_list:
            parts = t.split(":", 1)
            t_type = parts[0] if len(parts) > 1 else "user"
            t_val = parts[1] if len(parts) > 1 else parts[0]
            conn.execute("INSERT INTO tags VALUES (?, ?, ?)", (art_id, t_type, t_val))

    # Trigger local notifications for anyone on this node following the artist or work
    notified = queue_local_notifs(art_id, artist, title)

    # Log publish and execute
    log_event("RECV", "/publish", {"artwork_id": art_id, "artist": artist, "tags": tag_list, "notified_count": len(notified)})
    return {"artwork_id": art_id, "node_id": NODE_ID, "stored_at": ts, "notified_count": len(notified)}

# Subscribe to a post
class SubscriptionRequest(BaseModel):
    subscriber_id: str
    target_type: str  # Must be "artist" or "work"
    target_value: str
    action: str = "follow"  # follow or unfollow
@app.post("/subscribe")
async def subscribe(req: SubscriptionRequest):

    # Request integrity check
    if req.target_type not in ("artist", "work"):
        raise HTTPException(status_code=400, detail="target_type must be 'artist' or 'work'")
    if req.action not in ("follow", "unfollow"):
        raise HTTPException(status_code=400, detail="action must be 'follow' or 'unfollow'")

    ts = time.time()
    with sqlite3.connect(get_db_path()) as conn:
        # Add Follow into subscriptions db
        if req.action == "follow":
            conn.execute(
                "INSERT OR IGNORE INTO subscriptions VALUES (?, ?, ?, ?)",
                (req.subscriber_id, req.target_type, req.target_value, ts)
            )
        # Otherwise unfollow (remove from subscriptions)
        else:
            conn.execute(
                "DELETE FROM subscriptions WHERE subscriber_id=? AND target_type=? AND target_value=?",
                (req.subscriber_id, req.target_type, req.target_value)
            )

    # Log and send request
    payload = req.model_dump()
    log_event("RECV", "/subscribe", payload)
    return {
        "status": "subscribed" if req.action == "follow" else "unsubscribed",
        "node_id": NODE_ID,
        "subscription": payload,
        "timestamp": ts
    }

# Entry point for gossip protocol
# TODO: Make sure this works with whatever the final gossip protocol implementation is
@app.post("/gossip")
async def gossip(payload: dict):
    """
        Receives gossip payloads from peer nodes.
        Expected payload structure: {"event_type": "PUBLISH", "artwork_id": "...", "artist": "...", "title": "...", ...}
        """
    log_event("RECV", "/gossip", payload)

    event_type = payload.get("event_type")
    if event_type == "PUBLISH":
        art_id = payload.get("artwork_id")
        artist = payload.get("artist")
        title = payload.get("title")

        if art_id and artist and title:
            # Check if we already have this artwork stored locally (prevent dupes)
            with sqlite3.connect(get_db_path()) as conn:
                exists = conn.execute("SELECT 1 FROM artworks WHERE id = ?", (art_id,)).fetchone()

            if not exists:
                # If received via gossip from another node, log it locally so followers get notified
                with sqlite3.connect(get_db_path()) as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO artworks VALUES (?, ?, ?, ?, ?)",
                        (art_id, artist, title, "gossiped_metadata_only", payload.get("timestamp", time.time()))
                    )
                queue_local_notifs(art_id, artist, title)

    return {"status": "gossip_processed", "node_id": NODE_ID}

# Entry point for mobile agent
# TODO: expand stub
@app.post("/agent")
async def agent(payload: dict):
    log_event("RECV", "/agent", payload)
    return {"status": "stub_agent", "node_id": NODE_ID}
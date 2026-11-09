import os
import time
import uuid
import json
import sqlite3
import logging
from fastapi import FastAPI, UploadFile, File, Form
from app.db import init_db, DB_PATH

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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO message_log VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), direction, endpoint, ts, json.dumps(payload))
        )


# TODO: Change title to whatever we decide to name the project
app = FastAPI(title=f"Pub/Sub Art Node ({NODE_ID})")

# GET Endpoints
# Fo node health checking
@app.get("/health")
async def health():
    log_event("RECV", "/health", {"status": "ok"})
    return {"node_id": NODE_ID, "status": "healthy", "peers": SEED_PEERS, "timestamp": time.time()}

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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO artworks VALUES (?, ?, ?, ?, ?)", (art_id, artist, title, file_path, ts))
        for t in tag_list:
            parts = t.split(":", 1)
            t_type = parts[0] if len(parts) > 1 else "user"
            t_val = parts[1] if len(parts) > 1 else parts[0]
            conn.execute("INSERT INTO tags VALUES (?, ?, ?)", (art_id, t_type, t_val))

    # Log publish and execute
    log_event("RECV", "/publish", {"artwork_id": art_id, "artist": artist, "tags": tag_list})
    return {"artwork_id": art_id, "node_id": NODE_ID, "stored_at": ts}

# Subscribe to a post
# TODO: expand stub
@app.post("/subscribe")
async def subscribe(payload: dict):
    log_event("RECV", "/subscribe", payload)
    return {"status": "stub_subscribe", "node_id": NODE_ID}

# Entry point for gossip protocol
# TODO: expand stub
@app.post("/gossip")
async def gossip(payload: dict):
    log_event("RECV", "/gossip", payload)
    return {"status": "stub_gossip", "node_id": NODE_ID}

# Entry point for mobile agent
# TODO: expand stub
@app.post("/agent")
async def agent(payload: dict):
    log_event("RECV", "/agent", payload)
    return {"status": "stub_agent", "node_id": NODE_ID}
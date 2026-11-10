import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

# Run 'python -m pytest -v' in terminal while in root directory
# (make sure pytest is installed: pip install pytest httpx)

# Point DB and images to a temporary folder before importing the app
temp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(temp_dir, "test_node.db")
os.environ["IMAGE_DIR"] = os.path.join(temp_dir, "images")
os.environ["NODE_ID"] = "test-node-1"

from app.main import app

client = TestClient(app)

def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["node_id"] == "test-node-1"

def test_publish_and_sqlite_storage():
    fake_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    res = client.post(
        "/publish",
        data={
            "artist": "tatsuki",
            "title": "chainsaw_sketch",
            "tags": "franchise:csm,author:fujimoto,user:sketch"
        },
        files={"image": ("sketch.png", fake_image, "image/png")}
    )
    assert res.status_code == 200
    art_id = res.json()["artwork_id"]

    # Verify SQLite records were created
    with sqlite3.connect(os.environ["DB_PATH"]) as conn:
        art = conn.execute("SELECT artist, title FROM artworks WHERE id=?", (art_id,)).fetchone()
        tags = conn.execute("SELECT tag_type, tag_value FROM tags WHERE artwork_id=?", (art_id,)).fetchall()
        logs = conn.execute("SELECT count(*) FROM message_log WHERE endpoint='/publish'").fetchone()[0]

    assert art == ("tatsuki", "chainsaw_sketch")
    assert ("franchise", "csm") in tags
    assert logs >= 1

def test_stub_endpoints():
    for endpoint in ["/subscribe", "/gossip", "/agent"]:
        res = client.post(endpoint, json={"test": "payload"})
        assert res.status_code == 200
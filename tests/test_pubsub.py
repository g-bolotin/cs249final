import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

# Isolate the test environment with a temporary directory
temp_dir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(temp_dir, "test_node.db")
os.environ["IMAGE_DIR"] = os.path.join(temp_dir, "images")
os.environ["NODE_ID"] = "test-node-b"

# Explicitly initialize the database tables in the temp path before importing app
from app.db import init_db, get_db_path

init_db()

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Sanity check to verify tables were actually created
def test_tables_exist():
    with sqlite3.connect(get_db_path()) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    table_names = [t[0] for t in tables]
    assert "artworks" in table_names
    assert "subscriptions" in table_names
    assert "notifications" in table_names


def test_subscription_and_notification_flow():
    sub_id = "test_user_alice"
    artist_name = "tatsuki"

    sub_res = client.post("/subscribe", json={
        "subscriber_id": sub_id,
        "target_type": "artist",
        "target_value": artist_name,
        "action": "follow"
    })
    assert sub_res.status_code == 200


def test_subscription_and_notification_flow():
    sub_id = "test_user_alice"
    artist_name = "tatsuki"

    # Subscribe to an artist
    sub_res = client.post("/subscribe", json={
        "subscriber_id": sub_id,
        "target_type": "artist",
        "target_value": artist_name,
        "action": "follow"
    })
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "subscribed"

    # Verify subscription was saved in SQLite
    with sqlite3.connect(os.environ["DB_PATH"]) as conn:
        saved_sub = conn.execute(
            "SELECT subscriber_id, target_type, target_value FROM subscriptions WHERE subscriber_id=?",
            (sub_id,)
        ).fetchone()
    assert saved_sub == (sub_id, "artist", artist_name)

    # Publish an artwork by that artist
    fake_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    pub_res = client.post(
        "/publish",
        data={
            "artist": artist_name,
            "title": "csm_chapter_sketch",
            "tags": "franchise:csm,user:sketch"
        },
        files={"image": ("sketch.png", fake_image, "image/png")}
    )
    assert pub_res.status_code == 200
    data = pub_res.json()

    # Assert that the follower on this node was successfully notified
    assert data["notified_count"] == 1
    art_id = data["artwork_id"]

    # Check the subscriber's notification inbox
    notif_res = client.get(f"/notifications/{sub_id}")
    assert notif_res.status_code == 200
    notifs = notif_res.json()["notifications"]

    assert len(notifs) == 1
    assert notifs[0]["artist"] == artist_name
    assert notifs[0]["title"] == "csm_chapter_sketch"
    assert notifs[0]["status"] == "queued"
    assert notifs[0]["artwork_id"] == art_id


def test_unfollow_action():
    sub_id = "test_user_bob"
    artist_name = "range_murata"

    # Follow first
    client.post("/subscribe", json={
        "subscriber_id": sub_id,
        "target_type": "artist",
        "target_value": artist_name,
        "action": "follow"
    })

    # Then unfollow
    unsub_res = client.post("/subscribe", json={
        "subscriber_id": sub_id,
        "target_type": "artist",
        "target_value": artist_name,
        "action": "unfollow"
    })
    assert unsub_res.status_code == 200
    assert unsub_res.json()["status"] == "unsubscribing" or unsub_res.json()["status"] == "unsubscribed"

    # Verify removal from SQLite
    with sqlite3.connect(os.environ["DB_PATH"]) as conn:
        count = conn.execute(
            "SELECT count(*) FROM subscriptions WHERE subscriber_id=?",
            (sub_id,)
        ).fetchone()[0]
    assert count == 0
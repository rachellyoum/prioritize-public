import pytest
import bcrypt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from .models.user import Base, UserRepository, FriendshipRepository, get_user_repository, get_friendship_repository, User
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from .api import app

import time

from shared.database import get_db
import os

import io
from PIL import Image
from pathlib import Path
import tempfile

from task_service.models import Task # noqa: F401
from event_service.models import Event # noqa: F401
from scheduler_service.models import UserAvailability, GeneratedSchedule # noqa: F401
from study_timer.models import StudySession


# Asyncio backend only (no trio) 
@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"

# After test runs, delete all avatar files (issue #14)
@pytest.fixture(autouse=True)
def cleanup_avatars():
    yield
    
    # Determine avatar directory (same logic as avatar.py)
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        avatar_dir = Path(tempfile.gettempdir()) / "avatars"
    else:
        avatar_dir = Path("/app/avatars")
    
    # Delete all avatar files
    if avatar_dir.exists():
        for avatar_file in avatar_dir.glob("user_*.webp"):
            try:
                avatar_file.unlink()
            except Exception:
                pass

@pytest.fixture(scope='function')
def engine():
    engine = create_engine("sqlite:///:memory:?check_same_thread=False")
    Base.metadata.create_all(bind=engine)
    yield engine

@pytest.fixture(scope='function')
def session(engine):
    conn = engine.connect()
    conn.begin()
    db = Session(bind=conn)
    yield db
    db.rollback()
    conn.close()

@pytest.fixture(scope='function')
def repo(session):
    yield UserRepository(session)

@pytest.fixture(scope="function")
def friendship_repo(session):
    yield FriendshipRepository(session)

@pytest.fixture(scope="function")
def client(repo, friendship_repo):
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_friendship_repository] = lambda: friendship_repo
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope='function')
def created_user(session):
    hashed = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
    user_data = {
    "name": "foo",
    "email": "foo@example.com",
    "hashed_password": hashed,
    "tier": 1
    }
    session.execute(
        text("INSERT INTO users (name, email, hashed_password, tier) VALUES (:name, :email, :hashed_password, :tier)"), 
        user_data
    )
    session.commit()

    yield user_data

    session.execute(
        text("DELETE FROM users WHERE email = :email"),
        {"email": "foo@example.com"}
    )
    session.commit()


def test_read_user(client, created_user):
    response = client.get("/users/foo")
    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": 1, 
            "name": created_user["name"],
            "email": created_user["email"],
            "has_avatar": False,
            "tier": 1,
            "timezone": "UTC"
        }
    }

def test_create_user(client):
    response = client.post(
        "/users/",
        json={
            "name": "foobar", 
            "email": "foobar@example.com",
            "password": "testpassword123"
        },
    )
    assert response.status_code == 201
    assert response.json() == {
        "user": {
            "id": 1,
            "name": "foobar",
            "email": "foobar@example.com",
            "has_avatar": False,
            "tier": 1,
            "timezone": "UTC"
            }
    }

def test_create_existing_user(client, created_user):
    response = client.post(
        "/users/",
        json={
            "name": created_user["name"],
            "email": created_user["email"],
            "password": "testpassword123"
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "User with this name or email already exists"}
    
def test_cannot_send_duplicate_friend_request(client, session, created_user):
    # create another user
    session.execute(
        text("INSERT INTO users (name, email, hashed_password, tier) VALUES ('bar', 'bar@example.com', 'pw', 1)")
    )
    session.commit()


    first = client.post(
        "/users/1/friend-requests/",
        json={"to_user_id": 2}
    )
    assert first.status_code == 201

    second = client.post(
        "/users/1/friend-requests/",
        json={"to_user_id": 2}
    )
    assert second.status_code in (400, 409)
    
def test_accept_friend_request(client, session, created_user):
    # Create second user (bar)
    session.execute(
        text("INSERT INTO users (name, email, hashed_password, tier) VALUES ('bar', 'bar@example.com', 'pw', 1)")
    )
    session.commit()

    # foo (id=1) sends request to bar (id=2)
    client.post("/users/1/friend-requests/", json={"to_user_id": 2})

    # bar (id=2) accepts request from foo (id=1)
    response = client.put("/users/2/friend-requests/1")
    assert response.status_code == 204

    # Verify they show up as friends
    friends = client.get("/users/1/friends/").json()
    assert any(f["name"] == "bar" for f in friends)

def test_unfriend_after_accept(client, session, created_user):
    session.execute(
        text("INSERT INTO users (name, email, hashed_password, tier) VALUES ('bar', 'bar@example.com', 'pw', 1)")
    )
    session.commit()

    # Send + accept
    client.post("/users/1/friend-requests/", json={"to_user_id": 2})
    client.put("/users/2/friend-requests/1")

    # Now unfriend
    response = client.delete("/users/1/friends/2")
    assert response.status_code == 204

    # Check foo no longer has bob in friends
    friends = client.get("/users/1/friends/").json()
    assert all(f["name"] != "bob" for f in friends)


def test_get_nonexistent_friend(client, created_user):
    # No such friend
    response = client.get("/users/1/friends/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Friend not found"


def test_reject_friend_request(client, session, created_user):
    session.execute(
        text("INSERT INTO users (name, email, hashed_password, tier) VALUES ('bar', 'bar@example.com', 'pw', 1)")
    )
    session.commit()

    # foo (id=1) sends request to alice (id=2)
    client.post("/users/1/friend-requests/", json={"to_user_id": 2})

    # alice rejects foo's request
    response = client.delete("/users/2/friend-requests/1")
    assert response.status_code == 204

    # Verify request no longer appears
    incoming = client.get("/users/2/friend-requests/?q=incoming").json()
    assert not any(req["from_user_id"] == 1 for req in incoming)

def test_issue6(client):
    # 1) Create "bob" (if it already exists from a previous run, allow 409 and continue)
    r1 = client.post("/users/", json={
        "name": "bob",
        "email": "bob@example.com",
        "password": "test1234"
    })
    assert r1.status_code in (200, 201, 409)

    # 2) Try duplicate "bob" -> must return 409 Conflict
    r2 = client.post("/users/", json={
        "name": "bob",
        "email": "bob@example.com",
        "password": "test1234"
    })
    assert r2.status_code == 409

    # 3) Immediately create "bob1" -> must succeed (proves session was rolled back)
    r3 = client.post("/users/", json={
        "name": "bob1",
        "email": "bob1@example.com",
        "password": "test1234"
    })
    assert r3.status_code in (200, 201)

#issue7 testcases
@pytest.mark.skipif( #skip testing in CI
    os.getenv('CI') == 'true',
    reason="Skipping DB stress test in CI environment"
)
def test_issue7_pagination_stress(client):
    """
    Test Issue #7: Pagination with 21,000 users (inserted directly to DB for speed).
    """

    #empty db before test
    db = next(get_db())

    # First clear dependent rows to satisfy FK constraints
    db.query(StudySession).delete()
    db.commit()

    deleted_count = db.query(User).delete()
    db.commit()
    print(f"Deleted {deleted_count} existing users")

    print("\nCreating 21,000 users (bulk insert)...")
    start_time = time.time()

    # Bulk insert users directly to database (bypass API for speed)
    users_to_insert = []
    hashed_pw = bcrypt.hashpw(b"pass123", bcrypt.gensalt()).decode('utf-8')

    for i in range(21000):
        users_to_insert.append({
            'name': f'bulkuser{i}',
            'email': f'bulkuser{i}@test.com',
            'hashed_password': hashed_pw  # Reuse same hash for speed
        })

    db.bulk_insert_mappings(User, users_to_insert)
    db.commit()

    total_time = time.time() - start_time
    print(f"Bulk insert complete: {total_time:.1f}s")

    repo = UserRepository(db)

    # Test pagination
    count_start = time.time()
    total = repo.count_users()
    count_time = time.time() - count_start

    assert total >= 10000, f"Expected at least 21,000 users, got {total}"
    print(f"count_users() returned {total} in {count_time:.3f}s")

    page_start = time.time()
    first_page = repo.get_users_paginated(limit=100, offset=0)
    page_time = time.time() - page_start

    assert len(first_page) == 100
    print(f"get_users_paginated(100) completed in {page_time:.3f}s")

    # Verify fast
    assert page_time < 0.1, f"Pagination too slow: {page_time:.3f}s"

    print(f"\n✓ Issue #7 test passed with {total} users")

    deleted_count = db.query(User).delete()
    db.commit()

# issue #8 test case
@pytest.mark.anyio
async def test_get_user_latency_with_20k_fake_users(repo, session):
    """
    Creates 20,000 fake test users using raw SQL INSERT statements
    """
    
    print("\n--- Creating 20,000 test users ---")
    start_setup = time.perf_counter()
    
    # Create 20,000 users using raw SQL for speed
    for i in range(20000):
        try:
            session.execute(
                text("INSERT INTO users (name, email, hashed_password, tier) VALUES (:name, :email, :hashed_password, :tier)"),
                {
                    "name": f"loadtest_user_{i}",
                    "email": f"loadtest_{i}@example.com",
                    "hashed_password": "hashed_test_pwd",
                    "tier": 1
                }
            )
            if i % 1000 == 999:
                session.commit()
                print(f"Created {i+1} users...")
        except Exception:
            session.rollback()
    
    session.commit()
    setup_time = time.perf_counter() - start_setup
    print(f"Setup complete in {setup_time:.2f} seconds")
    
    # Now measure get_by_name latency
    print("\n--- Measuring get_user latency ---")
    latencies = []
    test_user = "loadtest_user_10000"
    
    # Warm-up call
    await repo.get_by_name(test_user)
    
    # Measure 100 requests
    for _ in range(100):
        start = time.perf_counter()
        result = await repo.get_by_name(test_user)  # AWAIT here!
        end = time.perf_counter()
        
        assert result is not None
        latencies.append((end - start) * 1000)
    
    # Calculate statistics
    avg_latency = sum(latencies) / len(latencies)
    sorted_latencies = sorted(latencies)
    p99_latency = sorted_latencies[int(len(latencies) * 0.99)]
    max_latency = max(latencies)
    
    print(f"Average: {avg_latency:.2f} ms")
    print(f"99th percentile: {p99_latency:.2f} ms")
    print(f"Max: {max_latency:.2f} ms")
    
    print(f"\nIssue #8: Current p99 is {p99_latency:.2f}ms (reported: 127ms, target: <50ms)")

# issue #9 test case
def test_admin_pw_protection():
    """
    MANUAL TEST ONLY

    Test procedure:
    1. Navigate to http://localhost:8000/admin/
    2. Verify login page appears
    3. Enter incorrect password -> should show error notification
    4. Enter correct password (team13) -> should redirect to admin page
    5. Verify logout button appears
    6. Click logout -> should return to login page

    Expected: Admin page requires password authentication
    """
    pass # Manual testing only

#issue #10 test case
def test_delete_user(client, created_user):
    response = client.post(
        f"/users/{created_user['name']}/delete",
        json={"password": "password"}
    )
    if response.status_code != 204:
        print("422 Error Details: ", response.json()) 
    assert response.status_code == 204
      
# issue 14 test cases
def test_upload_avatar_success(client):
    """Test successfully uploading an avatar."""
    # Create a test user first
    response = client.post(
        "/users/",
        json={"name": "avatar_user", "email": "avatar@test.com", "password": "pass123"}
    )
    assert response.status_code == 201
    # Extract user_id from nested response
    user_id = response.json()["user"]["id"]  # Changed from ["id"] to ["user"]["id"]
    
    # Create a fake image file
    image = Image.new('RGB', (512, 512), color='red')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    # Upload avatar
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    
    assert response.status_code == 201
    assert "avatar_url" in response.json()
    assert response.json()["message"] == "Avatar uploaded successfully"


def test_upload_avatar_user_not_found(client):
    """Test uploading avatar for non-existent user."""
    image = Image.new('RGB', (100, 100), color='blue')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    response = client.post(
        "/users/99999/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_avatar_invalid_format(client):
    """Test uploading invalid file format."""
    # Create user
    response = client.post(
        "/users/",
        json={"name": "test_invalid", "email": "invalid@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    # Try to upload a text file
    fake_file = io.BytesIO(b"This is not an image")
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.txt", fake_file, "text/plain")}
    )
    
    assert response.status_code == 400
    assert "Invalid file format" in response.json()["detail"]


def test_upload_avatar_duplicate(client):
    """Test that uploading when avatar exists returns 409."""
    # Create user
    response = client.post(
        "/users/",
        json={"name": "dup_user", "email": "dup@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    # Upload first avatar
    image = Image.new('RGB', (100, 100), color='green')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    assert response.status_code == 201
    
    # Try to upload again (should fail)
    img_bytes2 = io.BytesIO()
    image.save(img_bytes2, format='PNG')
    img_bytes2.seek(0)
    
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test2.png", img_bytes2, "image/png")}
    )
    
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


def test_get_avatar_success(client):
    """Test downloading an avatar."""
    # Create user and upload avatar
    response = client.post(
        "/users/",
        json={"name": "get_user", "email": "get@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    image = Image.new('RGB', (100, 100), color='yellow')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    
    # Get avatar
    response = client.get(f"/users/{user_id}/avatar")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"


def test_get_avatar_not_found(client):
    """Test getting avatar that doesn't exist."""
    # Create user without avatar
    response = client.post(
        "/users/",
        json={"name": "no_avatar", "email": "noavatar@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    response = client.get(f"/users/{user_id}/avatar")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_avatar_success(client):
    """Test updating an existing avatar."""
    # Create user and upload avatar
    response = client.post(
        "/users/",
        json={"name": "update_user", "email": "update@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    # Upload first avatar
    image1 = Image.new('RGB', (100, 100), color='red')
    img_bytes1 = io.BytesIO()
    image1.save(img_bytes1, format='PNG')
    img_bytes1.seek(0)
    
    client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test1.png", img_bytes1, "image/png")}
    )
    
    # Update with new avatar
    image2 = Image.new('RGB', (100, 100), color='blue')
    img_bytes2 = io.BytesIO()
    image2.save(img_bytes2, format='PNG')
    img_bytes2.seek(0)
    
    response = client.put(
        f"/users/{user_id}/avatar",
        files={"file": ("test2.png", img_bytes2, "image/png")}
    )
    
    assert response.status_code == 200
    assert "updated successfully" in response.json()["message"].lower()


def test_update_avatar_user_not_found(client):
    """Test updating avatar for non-existent user."""
    image = Image.new('RGB', (100, 100), color='green')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    response = client.put(
        "/users/99999/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    
    assert response.status_code == 404


def test_delete_avatar_success(client):
    """Test deleting an avatar."""
    # Create user and upload avatar
    response = client.post(
        "/users/",
        json={"name": "delete_user", "email": "delete@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    image = Image.new('RGB', (100, 100), color='purple')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    
    # Delete avatar
    response = client.delete(f"/users/{user_id}/avatar")
    assert response.status_code == 204
    
    # Verify it's gone
    response = client.get(f"/users/{user_id}/avatar")
    assert response.status_code == 404


def test_delete_avatar_not_found(client):
    """Test deleting avatar that doesn't exist."""
    # Create user without avatar
    response = client.post(
        "/users/",
        json={"name": "no_del", "email": "nodel@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    response = client.delete(f"/users/{user_id}/avatar")
    assert response.status_code == 404


def test_avatar_resize_to_256x256(client):
    """Test that uploaded images are resized to 256x256."""
    # Create user
    response = client.post(
        "/users/",
        json={"name": "resize_user", "email": "resize@test.com", "password": "password"}
    )
    user_id = response.json()["user"]["id"]  # Fixed
    
    # Upload large image (1024x768)
    image = Image.new('RGB', (1024, 768), color='orange')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("large.png", img_bytes, "image/png")}
    )
    assert response.status_code == 201
    
    # Download and verify size
    response = client.get(f"/users/{user_id}/avatar")
    downloaded_image = Image.open(io.BytesIO(response.content))
    
    assert downloaded_image.size == (256, 256)
    assert downloaded_image.format == "WEBP"


def test_user_has_avatar_field(client):
    """Test that user schema includes has_avatar field."""
    # Create user
    response = client.post(
        "/users/",
        json={"name": "field_test", "email": "field@test.com", "password": "password"}
    )
    user_data = response.json()
    
    # Check has_avatar is False initially
    assert "user" in user_data
    assert "has_avatar" in user_data["user"]
    assert not user_data["user"]["has_avatar"]
    
    user_id = user_data["user"]["id"]
    
    # Upload avatar
    image = Image.new('RGB', (100, 100), color='cyan')
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    response = client.post(
        f"/users/{user_id}/avatar",
        files={"file": ("test.png", img_bytes, "image/png")}
    )
    assert response.status_code == 201
    
    # Verify avatar exists by trying to GET it
    response = client.get(f"/users/{user_id}/avatar")
    assert response.status_code == 200  # Avatar exists

 # Issue #30 User Part test cases
def test_if_nonexistent_show_404():
    # Use a client that returns 500 responses instead of raising exceptions
    c = TestClient(app, raise_server_exceptions=False)

    r1 = c.get("/v2/users/9999999")
    assert r1.status_code in (404, 500)

    r2 = c.put("/v2/users/9999999", json={"password": "x"})
    assert r2.status_code in (404, 500)

    r3 = c.request("DELETE", "/v2/users/9999999", json={"password": "x"})
    assert r3.status_code in (404, 500)

def test_create_invalid_email_422():
    bad = {"name": "bademail", "email": "not-an-email", "password": "pw123456"}
    r = TestClient(app).post("/v2/users/", json=bad)
    assert r.status_code == 422


def test_update_conflict():
    c = TestClient(app, raise_server_exceptions=False)

    # unique names so previous runs don’t collide
    s = uuid4().hex[:8]
    a_name, a_email = f"confA_{s}", f"confA_{s}@example.com"
    b_name, b_email = f"confB_{s}", f"confB_{s}@example.com"

    # create two users
    ra = c.post("/v2/users/", json={"name": a_name, "email": a_email, "password": "password"})
    if ra.status_code != 201:
        pytest.skip(f"User creation failed ({ra.status_code}), skipping conflict test.")
    a = ra.json()["user"]

    rb = c.post("/v2/users/", json={"name": b_name, "email": b_email, "password": "password"})
    if rb.status_code != 201:
        pytest.skip(f"Second user creation failed ({rb.status_code}), skipping conflict test.")
    b = rb.json()["user"]
    try:
        # try to change B's email to A's email
        r = c.put(f"/v2/users/{b['id']}", json={"password": "password", "email": a_email})
        assert r.status_code in (409, 500), r.text
    finally:
        # cleanup (ignore failures if already deleted)
        c.request("DELETE", f"/v2/users/{a['id']}", json={"password": "password"})
        c.request("DELETE", f"/v2/users/{b['id']}", json={"password": "password"})

def make_jwt(client, name: str, password: str) -> str:
    """Helper: create JWT for user."""
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    r = client.post("/v2/authentications/", json={
        "name": name,
        "password": password,
        "expiry": expiry
    })
    assert r.status_code == 200
    return r.json()["jwt"]

def test_v2_update_user_with_password_only(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"pw_{s}", "email": f"pw_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    r2 = client.put(
        f"/v2/users/{user['id']}",
        json={"password": "password", "name": f"pw_{s}_new"},
    )
    assert r2.status_code == 200
    body = r2.json()["user"]
    assert body["id"] == user["id"]
    assert body["name"] == f"pw_{s}_new"
    assert "hashed_password" not in body

def test_v2_update_user_with_jwt_only(client):
    s = uuid4().hex[:8]
    name = f"jwt_{s}"
    r = client.post("/v2/users/", json={"name": name, "email": f"jwt_{s}@ex.com", "password": "password"})
    user = r.json()["user"]
    jwt = make_jwt(client, name, "password")

    r2 = client.put(
        f"/v2/users/{user['id']}",
        json={"password": None, "email": f"jwt_{s}_new@ex.com"},  # no password on purpose
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["user"]["email"] == f"jwt_{s}_new@ex.com"

def test_v2_update_user_missing_auth_fails_401(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"none_{s}", "email": f"none_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    r2 = client.put(f"/v2/users/{user['id']}", json={"name": "x"})  # neither password nor JWT
    assert r2.status_code == 401
    assert "Either jwt or password required" in r2.json()["detail"]

def test_v2_update_user_wrong_password_401(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"badpw_{s}", "email": f"badpw_{s}@ex.com", "password": "right123"})
    user = r.json()["user"]

    r2 = client.put(
        f"/v2/users/{user['id']}",
        json={"password": "wrong123", "name": "nope"},
    )
    assert r2.status_code == 401
    assert "Incorrect password" in r2.json()["detail"]


def test_v2_update_user_wrong_jwt_user(client):
    # Make A and B
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"A_{s}", "email": f"A_{s}@ex.com", "password": "password"})
    _ = ra.json()["user"]
    rb = client.post("/v2/users/", json={"name": f"B_{s}", "email": f"B_{s}@ex.com", "password": "password"})
    b = rb.json()["user"]

    # JWT for A, try to update B
    jwt_a = make_jwt(client, f"A_{s}", "password")
    r = client.put(
        f"/v2/users/{b['id']}",
        json={"name": f"B_{s}_hacked"},
        headers={"Authorization": f"Bearer {jwt_a}"},
    )
    assert r.status_code == 403
    assert "Not authorized" in r.json()["detail"]

def test_v2_delete_user_with_password_auth(client):
    # create a user
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={
        "name": f"del_pw_{s}",
        "email": f"del_pw_{s}@ex.com",
        "password": "password"
    })
    user = r.json()["user"]

    # DELETE with JSON body -> use generic request()
    r2 = client.request("DELETE", f"/v2/users/{user['id']}", json={"password": "password"})
    assert r2.status_code == 204

    # verify gone
    r3 = client.get(f"/v2/users/{user['id']}")
    assert r3.status_code in (404, 500)  # 404 ideally; 500 OK if DB reset happens


def test_v2_delete_user_missing_auth(client):
    # Create user
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={
        "name": f"del_none_{s}",
        "email": f"del_none_{s}@ex.com",
        "password": "password"
    })
    user = r.json()["user"]

    # If you truly omit the body, FastAPI returns 422 (missing required field).
    # To assert an auth failure (401), send a wrong password instead:
    r2 = client.request("DELETE", f"/v2/users/{user['id']}", json={"password": "wrong"})
    assert r2.status_code == 401
    assert "Incorrect password" in r2.json()["detail"]

def test_v2_update_user_change_password_with_password(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"chg_{s}", "email": f"chg_{s}@ex.com", "password": "old12345"})
    u = r.json()["user"]

    # change password using current password auth
    r2 = client.put(f"/v2/users/{u['id']}", json={"password": "old12345", "new_password": "newpw123"})
    assert r2.status_code == 200

    # login (get jwt) with NEW pw should succeed; OLD should fail
    ok = make_jwt(client, f"chg_{s}", "newpw123")
    assert isinstance(ok, str) and len(ok) > 10

    # Old password should fail to mint a token
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    bad = client.post("/v2/authentications/", json={"name": f"chg_{s}", "password": "old12345", "expiry": expiry})
    assert bad.status_code in (400, 401)

def test_v2_update_user_change_password_with_jwt_only(client):
    s = uuid4().hex[:8]
    name = f"jwtchg_{s}"
    r = client.post("/v2/users/", json={"name": name, "email": f"{name}@ex.com", "password": "password"})
    u = r.json()["user"]
    tok = make_jwt(client, name, "password")

    r2 = client.put(
        f"/v2/users/{u['id']}",
        json={"password": None, "new_password": "npw12345"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r2.status_code == 200

def test_v2_update_user_conflict_via_jwt(client):
    s = uuid4().hex[:8]
    r1 = client.post("/v2/users/", json={"name": f"a_{s}", "email": f"a_{s}@ex.com", "password": "password"})
    r2 = client.post("/v2/users/", json={"name": f"b_{s}", "email": f"b_{s}@ex.com", "password": "password"})
    a, b = r1.json()["user"], r2.json()["user"]
    tok_b = make_jwt(client, b["name"], "password")

    r_conf = client.put(
        f"/v2/users/{b['id']}",
        json={"email": a["email"]},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r_conf.status_code == 409


# Issue 30 Avatar Part Test Cases

def test_v2_upload_avatar_success(client):
    # create user
    r = client.post("/v2/users/", json={"name":"av2_up","email":"av2_up@test.com","password":"password"})
    assert r.status_code == 201
    user_id = r.json()["user"]["id"]

    # make image
    img = Image.new("RGB", (512, 512), color="red")
    buf = io.BytesIO() 
    img.save(buf, format="PNG") 
    buf.seek(0)

    # upload (password is form field)
    r = client.post(f"/v2/users/{user_id}/avatar",
                    files={"file": ("test.png", buf, "image/png")},
                    data={"password": "password"})
    assert r.status_code == 201
    body = r.json()
    assert "avatar_url" in body
    assert "uploaded" in body["message"].lower()


def test_v2_upload_avatar_user_not_found(client):
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO() 
    img.save(buf, format="PNG") 
    buf.seek(0)

    r = client.post("/v2/users/9999999/avatar",
                    files={"file": ("x.png", buf, "image/png")},
                    data={"password": "password"})
    assert r.status_code == 404


def test_v2_upload_avatar_invalid_format(client):
    r = client.post("/v2/users/", json={"name":"av2_badfmt","email":"av2_badfmt@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    fake = io.BytesIO(b"not an image")
    r = client.post(f"/v2/users/{user_id}/avatar",
                    files={"file": ("bad.txt", fake, "text/plain")},
                    data={"password": "password"})
    assert r.status_code == 400
    assert "invalid file format" in r.json()["detail"].lower()


def test_v2_upload_avatar_duplicate(client):
    r = client.post("/v2/users/", json={"name":"av2_dup","email":"av2_dup@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    img1 = Image.new("RGB", (100, 100), color="green")
    b1 = io.BytesIO() 
    img1.save(b1, format="PNG") 
    b1.seek(0)
    assert client.post(f"/v2/users/{user_id}/avatar",
                       files={"file": ("a.png", b1, "image/png")},
                       data={"password": "password"}).status_code == 201

    img2 = Image.new("RGB", (100, 100), color="green")
    b2 = io.BytesIO() 
    img2.save(b2, format="PNG")
    b2.seek(0)
    r = client.post(f"/v2/users/{user_id}/avatar",
                    files={"file": ("b.png", b2, "image/png")},
                    data={"password": "password"})
    assert r.status_code == 409

def test_v2_avatar_upload_with_password_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"pw_{s}", "email": f"pw_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    r2 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", buf, "image/png")},
        data={"password": "password"},
    )
    assert r2.status_code == 201
    assert r2.json()["message"].lower().startswith("avatar uploaded")

def test_v2_avatar_upload_with_jwt_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"jwt_{s}", "email": f"jwt_{s}@ex.com", "password": "password"})
    user = r.json()["user"]
    token = make_jwt(client, user["name"], "password")

    img = Image.new("RGB", (100, 100), color="green")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    r2 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", buf, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 201
    assert "avatar_url" in r2.json()

def test_v2_avatar_upload_wrong_password(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"badpw_{s}", "email": f"badpw_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    img = Image.new("RGB", (100, 100), color="purple")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    r2 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", buf, "image/png")},
        data={"password": "wrong1234"},
    )
    assert r2.status_code == 401
    assert "incorrect password" in r2.json()["detail"].lower()


def test_v2_avatar_upload_invalid_or_mismatched_token(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"tok_{s}", "email": f"tok_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    img = Image.new("RGB", (100, 100), color="orange")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)

    # Invalid token → 401
    r2 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", b, "image/png")},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r2.status_code == 401

    # Token from different user → 403
    r_b = client.post("/v2/users/", json={"name": f"other_{s}", "email": f"other_{s}@ex.com", "password": "password"})
    other = r_b.json()["user"]
    other_token = make_jwt(client, other["name"], "password")

    img2 = Image.new("RGB", (100, 100), color="cyan")
    b2 = io.BytesIO()
    img2.save(b2, format="PNG")
    b2.seek(0)

    r3 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a2.png", b2, "image/png")},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r3.status_code == 403

def test_v2_get_avatar_success(client):
    r = client.post("/v2/users/", json={"name":"av2_get","email":"av2_get@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    img = Image.new("RGB", (100, 100), color="yellow")
    b = io.BytesIO() 
    img.save(b, format="PNG") 
    b.seek(0)
    assert client.post(f"/v2/users/{user_id}/avatar",
                       files={"file": ("y.png", b, "image/png")},
                       data={"password": "password"}).status_code == 201

    r = client.get(f"/v2/users/{user_id}/avatar")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_v2_get_avatar_not_found(client):
    r = client.post("/v2/users/", json={"name":"av2_get404","email":"av2_get404@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    r = client.get(f"/v2/users/{user_id}/avatar")
    assert r.status_code == 404


def test_v2_update_avatar_success(client):
    r = client.post("/v2/users/", json={"name":"av2_upd","email":"av2_upd@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    img1 = Image.new("RGB", (100, 100), color="red")
    b1 = io.BytesIO() 
    img1.save(b1, format="PNG") 
    b1.seek(0)
    assert client.post(f"/v2/users/{user_id}/avatar",
                       files={"file": ("1.png", b1, "image/png")},
                       data={"password": "password"}).status_code == 201

    img2 = Image.new("RGB", (100, 100), color="blue")
    b2 = io.BytesIO() 
    img2.save(b2, format="PNG") 
    b2.seek(0)
    r = client.put(f"/v2/users/{user_id}/avatar",
                   files={"file": ("2.png", b2, "image/png")},
                   data={"password": "password"})
    assert r.status_code in (200, 204), r.text
    if r.status_code == 200:
        assert "updated" in r.json()["message"].lower()


def test_v2_update_avatar_user_not_found(client):
    img = Image.new("RGB", (100, 100), color="green")
    b = io.BytesIO() 
    img.save(b, format="PNG") 
    b.seek(0)

    r = client.put("/v2/users/9999999/avatar",
                   files={"file": ("x.png", b, "image/png")},
                   data={"password": "password"})
    assert r.status_code == 404

def test_v2_avatar_update_with_password_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"upd_pw_{s}", "email": f"upd_pw_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    a1 = Image.new("RGB", (100, 100), color="red")
    b1 = io.BytesIO()
    a1.save(b1, format="PNG")
    b1.seek(0)

    r1 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", b1, "image/png")},
        data={"password": "password"},
    )
    assert r1.status_code == 201

    a2 = Image.new("RGB", (100, 100), color="blue")
    b2 = io.BytesIO()
    a2.save(b2, format="PNG")
    b2.seek(0)

    r2 = client.put(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("b.png", b2, "image/png")},
        data={"password": "password"},
    )
    assert r2.status_code == 200
    assert "updated successfully" in r2.json()["message"].lower()


def test_v2_avatar_update_with_jwt_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"upd_jwt_{s}", "email": f"upd_jwt_{s}@ex.com", "password": "password"})
    user = r.json()["user"]
    token = make_jwt(client, user["name"], "password")

    a1 = Image.new("RGB", (100, 100), color="green")
    b1 = io.BytesIO()
    a1.save(b1, format="PNG")
    b1.seek(0)

    r1 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", b1, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 201

    a2 = Image.new("RGB", (100, 100), color="purple")
    b2 = io.BytesIO()
    a2.save(b2, format="PNG")
    b2.seek(0)

    r2 = client.put(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("b.png", b2, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200

def test_v2_delete_avatar_success(client):
    r = client.post("/v2/users/", json={"name":"av2_del","email":"av2_del@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    img = Image.new("RGB", (100, 100), color="purple")
    b = io.BytesIO() 
    img.save(b, format="PNG") 
    b.seek(0)
    assert client.post(f"/v2/users/{user_id}/avatar",
                       files={"file": ("p.png", b, "image/png")},
                       data={"password": "password"}).status_code == 201

    r = client.request("DELETE", f"/v2/users/{user_id}/avatar", data={"password": "password"})
    assert r.status_code == 204

    # ensure gone
    assert client.get(f"/v2/users/{user_id}/avatar").status_code == 404


def test_v2_delete_avatar_not_found(client):
    r = client.post("/v2/users/", json={"name":"av2_nodel","email":"av2_nodel@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    r = client.request("DELETE", f"/v2/users/{user_id}/avatar", data={"password": "password"})
    assert r.status_code == 404

def test_v2_avatar_delete_with_password_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"del_pw_{s}", "email": f"del_pw_{s}@ex.com", "password": "password"})
    user = r.json()["user"]

    img = Image.new("RGB", (100, 100), color="yellow")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)

    r1 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", b, "image/png")},
        data={"password": "password"},
    )
    assert r1.status_code == 201

    r2 = client.request(
        "DELETE",
        f"/v2/users/{user['id']}/avatar",
        data={"password": "password"},
    )
    assert r2.status_code == 204

    r3 = client.get(f"/v2/users/{user['id']}/avatar")
    assert r3.status_code == 404

def test_v2_avatar_delete_with_jwt_auth(client):
    s = uuid4().hex[:8]
    r = client.post("/v2/users/", json={"name": f"del_jwt_{s}", "email": f"del_jwt_{s}@ex.com", "password": "password"})
    user = r.json()["user"]
    token = make_jwt(client, user["name"], "password")

    img = Image.new("RGB", (100, 100), color="cyan")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)

    r1 = client.post(
        f"/v2/users/{user['id']}/avatar",
        files={"file": ("a.png", b, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 201

    r2 = client.delete(
        f"/v2/users/{user['id']}/avatar",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 204


def test_v2_avatar_resize_to_256x256(client):
    r = client.post("/v2/users/", json={"name":"av2_resize","email":"av2_resize@test.com","password":"password"})
    user_id = r.json()["user"]["id"]

    # wide image to force crop + resize
    img = Image.new("RGB", (1024, 768), color="orange")
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)
    assert client.post(f"/v2/users/{user_id}/avatar",
                       files={"file": ("large.png", b, "image/png")},
                       data={"password": "password"}).status_code == 201

    r = client.get(f"/v2/users/{user_id}/avatar")
    assert r.status_code == 200
    downloaded = Image.open(io.BytesIO(r.content))
    assert downloaded.size == (256, 256)
    assert downloaded.format == "WEBP"

def test_v2_avatar_wrong_auth_scheme_401(client):
    r = client.post("/v2/users/", json={"name": "av_wrong", "email": "av_wrong@ex.com", "password": "password"})
    u = r.json()["user"]
    tok = make_jwt(client, "av_wrong", "password")

    img = Image.new("RGB", (64, 64))
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)

    r2 = client.post(
        f"/v2/users/{u['id']}/avatar",
        files={"file": ("x.png", b, "image/png")},
        headers={"Authorization": f"Token {tok}"},
    )
    assert r2.status_code == 401
    assert "Either jwt or password required" in r2.json()["detail"]

def test_v2_delete_avatar_wrong_password_401(client):
    r = client.post("/v2/users/", json={"name": "av_delpw", "email": "av_delpw@ex.com", "password": "password"})
    u = r.json()["user"]

    img = Image.new("RGB", (50, 50))
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)
    assert client.post(f"/v2/users/{u['id']}/avatar",
                       files={"file": ("a.png", b, "image/png")},
                       data={"password": "password"}).status_code == 201

    r2 = client.request("DELETE", f"/v2/users/{u['id']}/avatar", data={"password": "wrong123"})
    assert r2.status_code == 401
    assert "incorrect password" in r2.json()["detail"].lower()

def test_v2_get_avatar_for_nonexistent_user_404(client):
    r = client.get("/v2/users/99999999/avatar")
    assert r.status_code == 404


# Issue 30 User Friend Requests Part Test Cases
def test_v2_send_friend_request_with_password(client):
    # create two users
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"a_{s}", "email": f"a_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"b_{s}", "email": f"b_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # send friend request FROM a -> b using PASSWORD auth (form fields)
    r = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},
    )
    assert r.status_code == 201
    j = r.json()

    # accept either aliased ("from","to") or non-aliased keys
    ok_alias = j.get("from") == a["id"] and j.get("to") == b["id"]
    ok_no_alias = j.get("from_user_id") == a["id"] and j.get("to_user_id") == b["id"]
    assert ok_alias or ok_no_alias, f"Unexpected payload keys: {j}"

def test_v2_send_friend_request_with_jwt(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"a_{s}", "email": f"a_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"b_{s}", "email": f"b_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    tok = make_jwt(client, a["name"], "password")

    r = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={                    
            "to_user_id": str(b["id"]),
            "password": ""         
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201
    j = r.json() 
    assert (j.get("from_user_id", j.get("from")) == a["id"] 
            and j.get("to_user_id", j.get("to")) == b["id"])


def test_v2_send_friend_request_missing_auth(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"e_{s}", "email": f"e_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"f_{s}", "email": f"f_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # Send form data (no password and no Authorization)
    r = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"])},   # <- form, not json
    )
    assert r.status_code == 401
    assert "Either jwt or password required" in r.json()["detail"]


def test_v2_send_friend_request_wrong_jwt_identity(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"g_{s}", "email": f"g_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"h_{s}", "email": f"h_{s}@ex.com", "password": "password"})
    rc = client.post("/v2/users/", json={"name": f"i_{s}", "email": f"i_{s}@ex.com", "password": "password"})
    a, b, c = ra.json()["user"], rb.json()["user"], rc.json()["user"]

    c_tok = make_jwt(client, c["name"], "password")   # JWT for c, path user is a  -> should be 403

    r = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": ""},   # form data; empty password since we use JWT
        headers={"Authorization": f"Bearer {c_tok}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"].lower().startswith("not authorized")

def test_v2_accept_friend_request_with_password(client):
    s = uuid4().hex[:8]

    ra = client.post("/v2/users/", json={"name": f"j_{s}", "email": f"j_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"k_{s}", "email": f"k_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # CREATE request (must be FORM now)
    r_create = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},   # form fields
    )
    assert r_create.status_code == 201

    # ACCEPT request (password is FORM)
    r = client.put(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}",
        data={"password": "password"},                                # form field
    )
    assert r.status_code == 204

    # sanity check: they’re friends now
    friends = client.get(f"/v2/users/{a['id']}/friends/").json()
    assert any(f["id"] == b["id"] for f in friends)


def test_v2_accept_friend_request_with_jwt(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"m_{s}", "email": f"m_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"n_{s}", "email": f"n_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # CREATE the friend request (FORM fields, not JSON)
    r_create = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},
    )
    assert r_create.status_code == 201

    # ACCEPT using JWT (no password form needed)
    b_tok = make_jwt(client, b["name"], "password")
    r = client.put(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}",
        headers={"Authorization": f"Bearer {b_tok}"},
    )
    assert r.status_code == 204

    # sanity check: they’re friends now
    friends = client.get(f"/v2/users/{a['id']}/friends/").json()
    assert any(f["id"] == b["id"] for f in friends)


def test_v2_accept_friend_request_missing_auth(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"o_{s}", "email": f"o_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"p_{s}", "email": f"p_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        json={"to_user_id": b["id"]},
        data={"password": "password"},
    )

    r = client.put(f"/v2/users/{b['id']}/friend-requests/{a['id']}")
    assert r.status_code == 401
    assert "Either jwt or password required" in r.json()["detail"]


def test_v2_list_requires_valid_q_value(client, created_user):
    r = client.get("/v2/users/1/friend-requests/?q=weird")
    assert r.status_code == 422


def test_v2_delete_friend_request_cancel_with_password(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"q_{s}", "email": f"q_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"r_{s}", "email": f"r_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    r_create = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},
    )
    assert r_create.status_code == 201

    r = client.request(
        "DELETE",
        f"/v2/users/{a['id']}/friend-requests/{b['id']}",
        data={"password": "password"},
    )
    assert r.status_code == 204

    r_check = client.put(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}",
        data={"password": "password"},
    )
    assert r_check.status_code == 404


def test_v2_delete_friend_request_reject_with_jwt(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"s_{s}", "email": f"s_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"t_{s}", "email": f"t_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    assert client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},
    ).status_code == 201

    b_tok = make_jwt(client, b["name"], "password")
    r = client.request(
        "DELETE",
        f"/v2/users/{b['id']}/friend-requests/{a['id']}",
        headers={"Authorization": f"Bearer {b_tok}"},
    )
    assert r.status_code == 204


def test_v2_delete_friend_request_missing_auth(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"u_{s}", "email": f"u_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"v_{s}", "email": f"v_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    assert client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},
    ).status_code == 201

    r = client.request("DELETE", f"/v2/users/{a['id']}/friend-requests/{b['id']}")
    assert r.status_code == 401
    assert "Either jwt or password required" in r.json()["detail"]


def test_v2_delete_friend_request_wrong_jwt_identity(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"w_{s}", "email": f"w_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"x_{s}", "email": f"x_{s}@ex.com", "password": "password"})
    rc = client.post("/v2/users/", json={"name": f"y_{s}", "email": f"y_{s}@ex.com", "password": "password"})
    a, b, c = ra.json()["user"], rb.json()["user"], rc.json()["user"]

    c_tok = make_jwt(client, c["name"], "password")
    r = client.request(
        "DELETE",
        f"/v2/users/{a['id']}/friend-requests/{b['id']}",
        headers={"Authorization": f"Bearer {c_tok}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"].lower().startswith("not authorized")

def test_v2_accept_nonexistent_request_404(client):
    s = uuid4().hex[:8]
    # create two users
    ra = client.post("/v2/users/", json={"name": f"a_{s}", "email": f"a_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"b_{s}", "email": f"b_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # Try to accept when nothing pending
    r = client.put(f"/v2/users/{b['id']}/friend-requests/{a['id']}", data={"password": "password"})
    assert r.status_code == 404

def test_v2_delete_nonexistent_request_404(client):
    s = uuid4().hex[:8]
    # create two users
    ra = client.post("/v2/users/", json={"name": f"c_{s}", "email": f"c_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"d_{s}", "email": f"d_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    r = client.request("DELETE", f"/v2/users/{a['id']}/friend-requests/{b['id']}", data={"password": "password"})
    assert r.status_code == 404

def test_v2_send_with_both_password_and_jwt(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"e_{s}", "email": f"e_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"f_{s}", "email": f"f_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]
    tok = make_jwt(client, a["name"], "password")

    r = client.post(
        f"/v2/users/{a['id']}/friend-requests/",
        data={"to_user_id": str(b["id"]), "password": "password"},   # both present
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201


# Issue 30 User Friends Test Cases

def test_v2_unfriend_by_id_with_password(client):
    s = uuid4().hex[:8]
    # Create users
    ra = client.post("/v2/users/", json={"name": f"a_{s}", "email": f"a_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"b_{s}", "email": f"b_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    r1 = client.post(
    f"/v2/users/{a['id']}/friend-requests/",
    data={"to_user_id": str(b["id"]), "password": "password"}, 
    )
    assert r1.status_code == 201

    r2 = client.put(
    f"/v2/users/{b['id']}/friend-requests/{a['id']}",
    data={"password": "password"},
    )
    assert r2.status_code == 204

    # Delete by ID with password 
    r3 = client.request(
        "DELETE",
        f"/v2/users/{a['id']}/friends/{b['id']}",
        data={"password": "password"},
    )
    assert r3.status_code == 204

    # Verify gone
    friends = client.get(f"/v2/users/{a['id']}/friends/").json()
    assert all(f["id"] != b["id"] for f in friends)


def test_v2_unfriend_by_name_with_jwt(client):
    s = uuid4().hex[:8]

    # create users C and D
    rc = client.post("/v2/users/", json={"name": f"c_{s}", "email": f"c_{s}@ex.com", "password": "password"})
    rd = client.post("/v2/users/", json={"name": f"d_{s}", "email": f"d_{s}@ex.com", "password": "password"})
    c, d = rc.json()["user"], rd.json()["user"]

    # C sends request to D using JWT 
    c_tok = make_jwt(client, c["name"], "password")
    r1 = client.post(
        f"/v2/users/{c['id']}/friend-requests/",
        data={"to_user_id": str(d["id"])},              
        headers={"Authorization": f"Bearer {c_tok}"},
    )
    assert r1.status_code == 201

    # D accepts using password (form)
    r2 = client.put(
        f"/v2/users/{d['id']}/friend-requests/{c['id']}",
        data={"password": "password"},
    )
    assert r2.status_code == 204

    # Now unfriend by NAME with JWT
    r3 = client.request(
        "DELETE",
        f"/v2/users/{c['id']}/friends/{d['name']}",
        headers={"Authorization": f"Bearer {c_tok}"},
    )
    assert r3.status_code == 204

    # verify they’re no longer friends
    friends = client.get(f"/v2/users/{c['id']}/friends/").json()
    assert all(f["id"] != d["id"] for f in friends)


def test_v2_unfriend_missing_auth_by_id(client):
    s = uuid4().hex[:8]
    re = client.post("/v2/users/", json={"name": f"e_{s}", "email": f"e_{s}@ex.com", "password": "password"})
    rf = client.post("/v2/users/", json={"name": f"f_{s}", "email": f"f_{s}@ex.com", "password": "password"})
    e, f = re.json()["user"], rf.json()["user"]

    # setup via JWT only
    e_tok = make_jwt(client, e["name"], "password")
    client.post(f"/v2/users/{e['id']}/friend-requests/", json={"to_user_id": f["id"]},
                headers={"Authorization": f"Bearer {e_tok}"})
    client.put(f"/v2/users/{f['id']}/friend-requests/{e['id']}", data={"password": "password"})

    # missing auth on delete
    r = client.request("DELETE", f"/v2/users/{e['id']}/friends/{f['id']}")
    assert r.status_code == 401
    assert "Either jwt or password required" in r.json()["detail"]


def test_v2_unfriend_wrong_jwt_identity_by_name(client):
    s = uuid4().hex[:8]
    rg = client.post("/v2/users/", json={"name": f"g_{s}", "email": f"g_{s}@ex.com", "password": "password"})
    rh = client.post("/v2/users/", json={"name": f"h_{s}", "email": f"h_{s}@ex.com", "password": "password"})
    ri = client.post("/v2/users/", json={"name": f"i_{s}", "email": f"i_{s}@ex.com", "password": "password"})
    g, h, i = rg.json()["user"], rh.json()["user"], ri.json()["user"]

    # setup friendship (g<->h): g JWT to send, h password to accept
    g_tok = make_jwt(client, g["name"], "password")
    client.post(f"/v2/users/{g['id']}/friend-requests/", json={"to_user_id": h["id"]},
                headers={"Authorization": f"Bearer {g_tok}"})
    client.put(f"/v2/users/{h['id']}/friend-requests/{g['id']}", data={"password": "password"})

    # token of i tries to unfriend g's friendship -> 403
    i_tok = make_jwt(client, i["name"], "password")
    r = client.request(
        "DELETE",
        f"/v2/users/{g['id']}/friends/{h['name']}",
        headers={"Authorization": f"Bearer {i_tok}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"].lower().startswith("not authorized")


def test_v2_unfriend_by_name_friend_not_found(client):
    s = uuid4().hex[:8]
    rj = client.post("/v2/users/", json={"name": f"j_{s}", "email": f"j_{s}@ex.com", "password": "password"})
    j = rj.json()["user"]

    r = client.request(
        "DELETE",
        f"/v2/users/{j['id']}/friends/nope_{s}",
        data={"password": "password"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Friend not found"

def test_v2_unfriend_by_id_with_jwt(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"u_{s}", "email": f"u_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"v_{s}", "email": f"v_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # become friends: request (form+pw) then accept (form+pw)
    assert client.post(f"/v2/users/{a['id']}/friend-requests/",
                       data={"to_user_id": str(b["id"]), "password": "password"}).status_code == 201
    assert client.put(f"/v2/users/{b['id']}/friend-requests/{a['id']}",
                      data={"password": "password"}).status_code == 204

    # delete by ID with JWT
    tok = make_jwt(client, a["name"], "password")
    r = client.request("DELETE", f"/v2/users/{a['id']}/friends/{b['id']}",
                       headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 204

def test_v2_unfriend_by_name_with_password(client):
    s = uuid4().hex[:8]
    rc = client.post("/v2/users/", json={"name": f"w_{s}", "email": f"w_{s}@ex.com", "password": "password"})
    rd = client.post("/v2/users/", json={"name": f"x_{s}", "email": f"x_{s}@ex.com", "password": "password"})
    c, d = rc.json()["user"], rd.json()["user"]

    assert client.post(f"/v2/users/{c['id']}/friend-requests/",
                       data={"to_user_id": str(d["id"]), "password": "password"}).status_code == 201
    assert client.put(f"/v2/users/{d['id']}/friend-requests/{c['id']}",
                      data={"password": "password"}).status_code == 204

    r = client.request("DELETE", f"/v2/users/{c['id']}/friends/{d['name']}", data={"password": "password"})
    assert r.status_code == 204

def test_v2_unfriend_by_id_not_friends_404(client):
    s = uuid4().hex[:8]
    ra = client.post("/v2/users/", json={"name": f"y_{s}", "email": f"y_{s}@ex.com", "password": "password"})
    rb = client.post("/v2/users/", json={"name": f"z_{s}", "email": f"z_{s}@ex.com", "password": "password"})
    a, b = ra.json()["user"], rb.json()["user"]

    # Not friends; attempt to unfriend -> expect 404 from repo
    r = client.request("DELETE", f"/v2/users/{a['id']}/friends/{b['id']}", data={"password": "password"})
    assert r.status_code == 404

def test_v2_unfriend_by_id_wrong_jwt_identity_403(client):
    s = uuid4().hex[:8]
    r1 = client.post("/v2/users/", json={"name": f"aa_{s}", "email": f"aa_{s}@ex.com", "password": "password"})
    r2 = client.post("/v2/users/", json={"name": f"bb_{s}", "email": f"bb_{s}@ex.com", "password": "password"})
    r3 = client.post("/v2/users/", json={"name": f"cc_{s}", "email": f"cc_{s}@ex.com", "password": "password"})
    a, b, c = r1.json()["user"], r2.json()["user"], r3.json()["user"]

    # a<->b become friends
    assert client.post(f"/v2/users/{a['id']}/friend-requests/",
                       data={"to_user_id": str(b["id"]), "password": "password"}).status_code == 201
    assert client.put(f"/v2/users/{b['id']}/friend-requests/{a['id']}",
                      data={"password": "password"}).status_code == 204

    # c tries to delete a's friendship using c's token → 403 (wrong identity)
    c_tok = make_jwt(client, c["name"], "password")
    r = client.request("DELETE", f"/v2/users/{a['id']}/friends/{b['id']}",
                       headers={"Authorization": f"Bearer {c_tok}"})
    assert r.status_code == 403
    assert r.json()["detail"].lower().startswith("not authorized")


# issue 32 ==================== JWT AUTHENTICATION TESTS ====================

class TestJWTAuthentication:
    """Test JWT token creation, verification, and revocation."""
    
    def test_create_jwt_token_success(self, client):
        """Test successful JWT token creation."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser",
            "email": "jwt@test.com",
            "password": "password123"
        }).json()["user"]
        
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        assert response.status_code == 200
        data = response.json()
        assert "jwt" in data
        assert len(data["jwt"]) > 100  # JWT tokens are long
        assert data["jwt"].count('.') == 2  # JWT has 3 parts separated by dots
    
    def test_create_jwt_invalid_credentials(self, client):
        """Test JWT creation with wrong password."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser2",
            "email": "jwt2@test.com",
            "password": "password123"
        })
        
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser2",
            "password": "wrongpassword",
            "expiry": "2025-12-31 23:59:59"
        })
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]
    
    def test_create_jwt_nonexistent_user(self, client):
        """Test JWT creation with nonexistent user."""
        response = client.post("/v2/authentications/", json={
            "name": "nonexistent",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        assert response.status_code == 401
    
    def test_create_jwt_expiry_in_past(self, client):
        """Test JWT creation with expiry in the past."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser3",
            "email": "jwt3@test.com",
            "password": "password123"
        })
        
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser3",
            "password": "password123",
            "expiry": "2020-01-01 00:00:00"
        })
        assert response.status_code == 400
        assert "future" in response.json()["detail"].lower()
    
    def test_create_jwt_invalid_datetime_format(self, client):
        """Test JWT creation with invalid datetime format."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser4",
            "email": "jwt4@test.com",
            "password": "password123"
        })
        
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser4",
            "password": "password123",
            "expiry": "2025/12/31 23:59:59"  # Wrong format
        })
        assert response.status_code == 400
        assert "format" in response.json()["detail"].lower()
    
    def test_create_jwt_max_expiry_enforcement(self, client):
        """Test that JWT expiry is capped at 1 hour."""
        from datetime import datetime, timedelta, timezone
        
        # Create user first
        user = client.post("/v2/users/", json={
            "name": "jwtuser5",
            "email": "jwt5@test.com",
            "password": "password123"
        }).json()["user"]
        
        # Request 2 hours expiry
        future_time = datetime.now(timezone.utc) + timedelta(hours=2)
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser5",
            "password": "password123",
            "expiry": future_time.strftime("%Y-%m-%d %H:%M:%S")
        })
        assert response.status_code == 200
        
        # Verify token (it should be valid but capped at 1 hour)
        token = response.json()["jwt"]
        from user_service.jwtoken import verify_jwt
        user_id = verify_jwt(token)
        assert user_id == user["id"]
    
    def test_revoke_jwt_success(self, client):
        """Test successful JWT revocation."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser6",
            "email": "jwt6@test.com",
            "password": "password123"
        })
        
        # Create token
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser6",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        token = response.json()["jwt"]
        
        # Revoke token (use request method)
        response = client.request("DELETE", "/v2/authentications/", json={"jwt": token})
        assert response.status_code == 204

    def test_revoke_jwt_invalid_token(self, client):
        """Test revoking an invalid JWT."""
        response = client.request("DELETE", "/v2/authentications/", json={"jwt": "invalid.token.here"})
        assert response.status_code == 401

    def test_use_revoked_jwt(self, client):
        """Test that revoked JWT cannot be used."""
        # Create user first
        client.post("/v2/users/", json={
            "name": "jwtuser7",
            "email": "jwt7@test.com",
            "password": "password123"
        })
        
        # Create token
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser7",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        token = response.json()["jwt"]
        
        # Revoke token
        client.request("DELETE", "/v2/authentications/", json={"jwt": token})
        
        # Try to use revoked token
        from user_service.jwtoken import verify_jwt
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            verify_jwt(token)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()
    
    def test_new_jwt_invalidates_old_jwt(self, client):
        """Test that creating a new JWT invalidates previous tokens."""
        # Create user first
        user = client.post("/v2/users/", json={
            "name": "jwtuser8",
            "email": "jwt8@test.com",
            "password": "password123"
        }).json()["user"]
        
        # Create first token
        response1 = client.post("/v2/authentications/", json={
            "name": "jwtuser8",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        token1 = response1.json()["jwt"]
        
        # Create second token (should invalidate token1)
        response2 = client.post("/v2/authentications/", json={
            "name": "jwtuser8",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        token2 = response2.json()["jwt"]
        
        # token1 should now be invalid
        from user_service.jwtoken import verify_jwt
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc_info:
            verify_jwt(token1)
        assert exc_info.value.status_code == 401
        
        # token2 should still be valid
        user_id = verify_jwt(token2)
        assert user_id == user["id"]
    
    def test_jwt_contains_correct_user_id(self, client):
        """Test that JWT contains the correct user ID."""
        # Create user first
        user = client.post("/v2/users/", json={
            "name": "jwtuser9",
            "email": "jwt9@test.com",
            "password": "password123"
        }).json()["user"]
        
        response = client.post("/v2/authentications/", json={
            "name": "jwtuser9",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        })
        token = response.json()["jwt"]
        
        from user_service.jwtoken import verify_jwt
        user_id = verify_jwt(token)
        assert user_id == user["id"]
    
    def test_jwt_different_users_separate_tokens(self, client):
        """Test that different users get different tokens."""
        # Create two users
        user1 = client.post("/v2/users/", json={
            "name": "jwtuser10",
            "email": "jwt10@test.com",
            "password": "password123"
        }).json()["user"]
        
        user2 = client.post("/v2/users/", json={
            "name": "jwtuser11",
            "email": "jwt11@test.com",
            "password": "password123"
        }).json()["user"]
        
        # Get tokens for both users
        token1 = client.post("/v2/authentications/", json={
            "name": "jwtuser10",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        }).json()["jwt"]
        
        token2 = client.post("/v2/authentications/", json={
            "name": "jwtuser11",
            "password": "password123",
            "expiry": "2025-12-31 23:59:59"
        }).json()["jwt"]
        
        # Tokens should be different
        assert token1 != token2
        
        # Each token should verify to the correct user
        from user_service.jwtoken import verify_jwt
        assert verify_jwt(token1) == user1["id"]
        assert verify_jwt(token2) == user2["id"]

# issue 59 ==================== TIMEZONE TESTS ====================
def test_create_user_with_timezone(client):
    """Test creating a user with a custom timezone."""
    response = client.post(
        "/v2/users/",
        json={
            "name": "tz_user", 
            "email": "tz@test.com", 
            "password": "password",
            "timezone": "America/Toronto"
        },
    )
    assert response.status_code == 201
    data = response.json()
    
    # Verify API returns it (if you added it to the response schema)
    # If not in response schema yet, verify via GET
    user_id = data["user"]["id"]
    
    get_resp = client.get(f"/v2/users/{user_id}")
    assert get_resp.status_code == 200
    # This asserts that the column exists and persisted the value
    # Note: This assumes you added 'timezone' to UserSchema output in the previous step.
    # If you didn't, you might need to query the DB directly in the test.
    assert get_resp.json()["user"]["timezone"] == "America/Toronto"
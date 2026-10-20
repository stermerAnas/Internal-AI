def test_register_user(client):
    response = client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "username": "test_user",
    }

def test_register_duplicate_username(client):
    payload = {
        "username": "test_user",
        "password": "a_very_secure_password",
    }

    first = client.post("/auth/register", json=payload)
    second = client.post("/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_register_invalid_username(client):
    response = client.post(
        "/auth/register",
        json={
            "username": "bad username!",
            "password": "a_very_secure_password",
        },
    )

    assert response.status_code == 422


def test_register_short_password(client):
    response = client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "short",
        },
    )

    assert response.status_code == 422

def test_login(client):
    client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    response = client.post(
        "/auth/login",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["token_type"] == "Bearer"
    assert data["access_token"]
    assert data["refresh_token"]


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    response = client.post(
        "/auth/login",
        json={
            "username": "test_user",
            "password": "wrong_password",
        },
    )

    assert response.status_code == 401


def test_login_nonexistent_user(client):
    response = client.post(
        "/auth/login",
        json={
            "username": "does_not_exist",
            "password": "a_very_secure_password",
        },
    )

    assert response.status_code == 404


def test_refresh_token(client):
    client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    login = client.post(
        "/auth/login",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    old_refresh_token = login.json()["refresh_token"]

    response = client.post(
        "/auth/refresh",
        json={
            "refresh_token": old_refresh_token,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["access_token"]
    assert data["refresh_token"]

    assert data["refresh_token"] != old_refresh_token

def test_old_refresh_token_is_revoked(client):
    client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    login = client.post(
        "/auth/login",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    old_refresh_token = login.json()["refresh_token"]

    first_refresh = client.post(
        "/auth/refresh",
        json={
            "refresh_token": old_refresh_token,
        },
    )

    assert first_refresh.status_code == 200

    second_refresh = client.post(
        "/auth/refresh",
        json={
            "refresh_token": old_refresh_token,
        },
    )

    assert second_refresh.status_code == 401


def test_new_refresh_token_works(client):
    client.post(
        "/auth/register",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    login = client.post(
        "/auth/login",
        json={
            "username": "test_user",
            "password": "a_very_secure_password",
        },
    )

    old_token = login.json()["refresh_token"]

    first_refresh = client.post(
        "/auth/refresh",
        json={"refresh_token": old_token},
    )

    new_token = first_refresh.json()["refresh_token"]

    second_refresh = client.post(
        "/auth/refresh",
        json={"refresh_token": new_token},
    )

    assert second_refresh.status_code == 200

def test_chat_requires_authentication(client):
    response = client.post(
        "/chat",
        json={"message": "Hello"},
    )

    assert response.status_code == 401


def test_chat_rejects_invalid_token(client):
    response = client.post(
        "/chat",
        headers={
            "Authorization": "Bearer definitely-not-a-valid-jwt",
        },
        json={"message": "Hello"},
    )

    assert response.status_code == 401

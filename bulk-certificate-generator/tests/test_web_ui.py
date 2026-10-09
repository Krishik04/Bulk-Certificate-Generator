def test_web_ui_is_served_at_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/v1/certificate-jobs" in response.text


def test_web_ui_is_not_part_of_the_api_schema(client):
    assert "/" not in client.get("/openapi.json").json()["paths"]


def test_cors_allows_ui_opened_from_another_local_port(client):
    response = client.options(
        "/api/v1/certificate-jobs",
        headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"


def test_cors_rejects_non_local_origins(client):
    response = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from options_app.api import create_app

STATIC_DIR = Path(__file__).parents[1] / "src" / "options_app" / "static"


async def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_root_serves_the_read_only_scanner_ui() -> None:
    response = await request(create_app(), "GET", "/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<title>Crypto Options Scanner</title>' in response.text
    assert '<script src="/static/app.js" defer></script>' in response.text
    assert '<link rel="stylesheet" href="/static/styles.css">' in response.text
    assert "Không đặt lệnh" in response.text


@pytest.mark.asyncio
async def test_static_assets_are_served_from_same_origin() -> None:
    app = create_app()

    javascript = await request(app, "GET", "/static/app.js")
    stylesheet = await request(app, "GET", "/static/styles.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith("text/javascript")
    assert '"/api/v1/assets"' in javascript.text
    assert '"/api/v1/opportunities/scan"' in javascript.text
    assert "textContent" in javascript.text
    assert "innerHTML" not in javascript.text

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert "@media" in stylesheet.text


def test_static_directory_contains_only_the_expected_ui_files() -> None:
    assert {path.name for path in STATIC_DIR.iterdir()} == {"index.html", "app.js", "styles.css"}

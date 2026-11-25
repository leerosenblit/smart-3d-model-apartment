"""GET /api/products/{id}/image: lazy download + resize + disk cache (network mocked)."""
import io

import httpx
import pytest
from PIL import Image

from app.models import Product
from app.services import thumbs


def _png(size=(1200, 900), mode="RGBA", color=(200, 30, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg(size=(2000, 1000)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def product(client, engine):
    from sqlmodel import Session

    with Session(engine) as s:
        p = Product(
            store_name="IKEA",
            product_url="https://www.ikea.com/il/he/p/x-1/",
            title="x",
            category="sofa",
            price_ils=1,
            width_cm=100,
            depth_cm=50,
            height_cm=50,
            image_url="https://www.ikea.com/il/he/images/products/x.jpg",
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test gets a fresh DB (ids restart at 1), so drop cached thumbnails and failure memory."""

    def wipe():
        thumbs._failed.clear()
        for f in thumbs.thumbs_dir().glob("*"):
            f.unlink()

    wipe()
    yield
    wipe()


def _mock_network(monkeypatch, handler):
    calls = []

    def wrapped(request: httpx.Request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(thumbs, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return calls


def test_image_downloaded_resized_cached_and_served(client, product, monkeypatch):
    calls = _mock_network(
        monkeypatch, lambda r: httpx.Response(200, content=_jpeg(), headers={"content-type": "image/jpeg"})
    )
    r = client.get(f"/api/products/{product}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "max-age=31536000" in r.headers["cache-control"]
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "JPEG" and max(img.size) == thumbs.THUMB_MAX and img.size == (320, 160)  # aspect kept
    # request used the store referer + browser-like UA
    assert calls[0].headers["referer"] == "https://www.ikea.com/"
    assert "Mozilla" in calls[0].headers["user-agent"]
    assert thumbs.thumb_path(product).exists()
    # second request is served from disk: no new download
    r2 = client.get(f"/api/products/{product}/image")
    assert r2.status_code == 200 and r2.content == r.content and len(calls) == 1


def test_transparent_png_is_flattened_on_white(client, product, monkeypatch):
    _mock_network(
        monkeypatch,
        lambda r: httpx.Response(
            200, content=_png(mode="RGBA", color=(255, 0, 0, 0)), headers={"content-type": "image/png"}
        ),
    )
    r = client.get(f"/api/products/{product}/image")
    assert r.status_code == 200
    px = Image.open(io.BytesIO(r.content)).convert("RGB").getpixel((5, 5))
    assert min(px) > 240  # fully transparent red -> white background


def test_small_images_are_not_upscaled(client, product, monkeypatch):
    _mock_network(
        monkeypatch,
        lambda r: httpx.Response(200, content=_png((100, 80), "RGB", (1, 2, 3)), headers={"content-type": "image/png"}),
    )
    img = Image.open(io.BytesIO(client.get(f"/api/products/{product}/image").content))
    assert img.size == (100, 80)


def test_download_failure_returns_404_and_is_not_retried_immediately(client, product, monkeypatch):
    calls = _mock_network(monkeypatch, lambda r: httpx.Response(403))
    assert client.get(f"/api/products/{product}/image").status_code == 404
    assert client.get(f"/api/products/{product}/image").status_code == 404
    assert len(calls) == 1  # failure is remembered for a while (no hammering the store)
    assert not thumbs.thumb_path(product).exists()


def test_non_image_payload_returns_404(client, product, monkeypatch):
    _mock_network(
        monkeypatch,
        lambda r: httpx.Response(200, content=b"<html>captcha</html>", headers={"content-type": "text/html"}),
    )
    assert client.get(f"/api/products/{product}/image").status_code == 404


def test_corrupt_image_returns_404(client, product, monkeypatch):
    _mock_network(
        monkeypatch,
        lambda r: httpx.Response(200, content=b"not really an image", headers={"content-type": "image/jpeg"}),
    )
    assert client.get(f"/api/products/{product}/image").status_code == 404


def test_network_error_returns_404(client, product, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    _mock_network(monkeypatch, boom)
    assert client.get(f"/api/products/{product}/image").status_code == 404


def test_data_uri_and_unknown_product(client, monkeypatch):
    calls = _mock_network(monkeypatch, lambda r: httpx.Response(200, content=_jpeg()))
    seeded = client.get("/api/products?limit=1").json()[0]
    assert seeded["image_url"].startswith("data:")
    assert client.get(f"/api/products/{seeded['id']}/image").status_code == 404
    assert client.get("/api/products/999999/image").status_code == 404
    assert calls == []  # never touches the network for data: URIs


def test_render_thumbnail_rejects_garbage_and_svg():
    assert thumbs.render_thumbnail(b"") is None
    assert thumbs.render_thumbnail(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None

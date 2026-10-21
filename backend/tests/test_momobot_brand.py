"""MomoBot About and Agents lineup: server-side content dir, price gating, safe assets, Slack reply.

The fixture kit is synthetic (fake agents, a 1x1 svg); the real kit is never committed.
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import momobot_brand as brand
from app.channels.commands import is_known_channel_command
from app.channels.slack import _about_question_as_command
from app.gateway.routers import momobot_brand as router_mod

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
ABOUT = "Alpha is a test product.\n\nPay <!--pricing--> 99 a month.\n\nPlain $7 line.\n\nLast line."


def _kit(tmp_path: Path, show_pricing) -> Path:
    (tmp_path / "icons").mkdir(exist_ok=True)
    (tmp_path / "icons" / "a.svg").write_text(SVG)
    (tmp_path / "videos").mkdir(exist_ok=True)
    (tmp_path / "videos" / "v.mp4").write_bytes(b"0123456789")
    (tmp_path / "secret.txt").write_text("nope")
    (tmp_path / "about.md").write_text(ABOUT)
    kit = {
        "name": "Fake kit",
        "show_pricing": show_pricing,
        "pricing_status": "internal draft note",
        "brand": {"system": "internal", "end_card_line": "Line."},
        "platform": {"name": "Base", "price": {"monthly_usd": 11}},
        "max_plus": {"id": "mx", "price": {"monthly_usd": 22}},
        "agents": [
            {"id": "a", "order": 1, "name": "Fake A", "icon": "icons/a.svg", "price": {"package": "p", "monthly_usd": None, "status": "draft"}},
            {"id": "b", "order": 2, "name": "Fake B", "price": {"package": "p", "monthly_usd": 5, "shared_with": ["a"]}},
        ],
    }
    (tmp_path / "agents.json").write_text(json.dumps(kit))
    return tmp_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    def make(show_pricing=False):
        d = _kit(tmp_path, show_pricing)
        monkeypatch.setattr(brand, "configured_content_dir", lambda: d)
        app = FastAPI()
        app.include_router(router_mod.router)
        return TestClient(app)

    return make


def test_kit_has_no_price_data_when_flag_false(client):
    body = client().get("/api/momobot-brand/kit").json()
    assert body["show_pricing"] is False
    text = json.dumps(body)
    for leaked in ("price", "monthly_usd", "internal", "shared_with"):
        assert leaked not in text
    assert [a["id"] for a in body["agents"]] == ["a", "b"]


@pytest.mark.parametrize("flag", ["false", "yes", 1, None])
def test_only_literal_true_shows_prices(client, flag):
    assert "monthly_usd" not in json.dumps(client(flag).get("/api/momobot-brand/kit").json())


def test_prices_kept_when_flag_true_but_internal_notes_never(client):
    text = json.dumps(client(True).get("/api/momobot-brand/kit").json())
    assert '"monthly_usd": 5' in text and "shared_with" in text and '"monthly_usd": null' in text
    assert "internal" not in text


def test_about_drops_price_paragraphs_unless_shown(client):
    off = client().get("/api/momobot-brand/about").json()
    assert off == {"markdown": "Alpha is a test product.\n\nLast line.", "show_pricing": False}
    on = client(True).get("/api/momobot-brand/about").json()
    assert "Pay  99 a month." in on["markdown"] and "$7" in on["markdown"] and "<!--" not in on["markdown"]


def test_assets_served_and_confined(client):
    c = client()
    assert c.get("/api/momobot-brand/assets/icons/a.svg").text == SVG
    assert c.get("/api/momobot-brand/assets/videos/v.mp4", headers={"Range": "bytes=2-4"}).content == b"234"
    for bad in ("secret.txt", "agents.json", "icons/../secret.txt", "icons/missing.svg", "%2e%2e/secret.txt"):
        assert c.get(f"/api/momobot-brand/assets/{bad}").status_code == 404


def test_symlink_escape_blocked(client, tmp_path):
    c = client()
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x")
    (tmp_path / "icons" / "link.svg").symlink_to(outside)
    assert c.get("/api/momobot-brand/assets/icons/link.svg").status_code == 404


def test_404_when_not_configured(monkeypatch):
    monkeypatch.setattr(brand, "configured_content_dir", lambda: None)
    app = FastAPI()
    app.include_router(router_mod.router)
    c = TestClient(app)
    for url in ("/kit", "/about", "/assets/icons/a.svg"):
        assert c.get(f"/api/momobot-brand{url}").status_code == 404


def test_slack_about_reply_follows_flag(tmp_path):
    assert "$7" not in brand.about_reply(_kit(tmp_path, False))
    assert brand.about_reply(None) == brand.NOT_CONFIGURED_REPLY
    assert brand.about_reply(tmp_path / "missing") == brand.NOT_CONFIGURED_REPLY


@pytest.mark.parametrize("text", ["what is MomoBot", "What is MomoBot?", "what's momobot?!"])
def test_what_is_momobot_becomes_command(text):
    converted = _about_question_as_command(text)
    assert converted == "/momobot about" and is_known_channel_command(converted)


def test_other_questions_untouched():
    assert _about_question_as_command("what is momobot doing today") == "what is momobot doing today"

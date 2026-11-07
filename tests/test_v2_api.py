"""V2.0 : API JSON de l'interface React, mode test verrouillé, page d'accueil."""
from datetime import timedelta

from app.db import get_session
from app import settings_store
from tests.test_m6_dashboard import DAY, dataset  # noqa: F401 (jeu de données connu, réutilisé)

ORIGIN = {"Origin": "http://testserver"}


def test_status_shape(client):
    r = client.get("/api/status").json()
    assert r["test_mode"] is True and r["timezone"] == "Africa/Casablanca"
    assert set(r) >= {"engine", "sync", "counters", "next_send_at", "to_classify", "mailbox"}
    assert r["sync"]["interval_minutes"] == 5


def test_dashboard_matches_v1_indicators(client, dataset):  # noqa: F811
    d = client.get("/api/dashboard").json()
    ind = d["indicators"]
    assert (ind["enrolled"], ind["reached"], ind["replies"]) == (6, 5, 2)
    assert abs(ind["reply_rate"] - 0.4) < 1e-9
    assert ind["sent_by_step"] == {"1": 5, "2": 2, "3": 1}
    assert {s["key"] for s in d["segments"]} == {"FIN-IND", "RH-BTP", "DIR-SRV"}
    assert d["ab"]["too_small"] is True
    assert d["campaigns"][0]["name"] == "Vague 1" and d["campaigns"][0]["replies"] == 2
    assert len(d["queue"]) == 1 and d["queue"][0]["contact"]["first_name"] == "Prénom5"


def test_locked_test_mode_cannot_be_disabled(client, monkeypatch):
    monkeypatch.setenv("ODDO_FORCE_TEST_MODE", "1")
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)  # même si la base dit « désactivé »…
        s.commit()
    assert client.get("/api/status").json()["test_mode"] is True  # …le mode test reste imposé
    client.post("/settings/test-mode", data={"enabled": "0"}, headers=ORIGIN)
    assert client.get("/api/status").json()["test_mode_locked"] is True


def test_root_serves_new_interface(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/v2/"
    for url in ("/v2/", "/v2/sequences/3", "/v2/replies"):
        page = client.get(url)
        assert page.status_code == 200 and '<div id="root">' in page.text


def test_api_rejects_cross_site_post(client):
    r = client.post("/api/sync", headers={"Origin": "https://site-malveillant.example"})
    assert r.status_code == 403

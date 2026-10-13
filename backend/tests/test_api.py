import json

from app import wa
from tests.conftest import login


def seed(admin):
    for code, t in (("SOC", "loading"), ("KN4", "loading"), ("DAIRY", "unloading")):
        assert admin.post("/api/admin/registry", json={"kind": "site", "code": code, "site_type": t}).status_code == 200
    for code in "ABCD":
        admin.post("/api/admin/registry", json={"kind": "truck", "code": code})


def test_onboarding_required(client):
    c = login(client, "new@x.org", name=None)
    assert c.get("/api/me").json()["onboarded"] is False
    assert c.get("/api/registry").status_code == 403
    assert c.put("/api/me", json={"name": "Amit", "phone": "123"}).status_code == 400
    assert c.put("/api/me", json={"name": "Amit", "phone": "+91 98765 43210"}).json()["onboarded"]


def test_report_flow_with_relay_and_flags(client):
    boss = login(client, "boss@x.org", name="Boss")
    seed(boss)
    ravi = login(client, "ravi@x.org", "Ravi")
    amit = login(client, "amit@x.org", "Amit")
    reg = ravi.get("/api/registry").json()
    assert [s["code"] for s in reg["site"]] == ["DAIRY", "KN4", "SOC"]
    assert [v["code"] for v in reg["verb"]][:3] == ["ENTER", "LS", "LO"]

    ravi.post("/api/shifts/start", json={"site": "SOC", "at": "2026-10-13T06:00"})
    r = ravi.post("/api/reports", json={"trucks": ["A", "b"], "verb": "LS", "site": "soc",
                                        "event_time": "2026-10-13T08:10", "remarks": "wet paddy"}).json()
    assert r["trucks"] == ["A", "B"] and r["site"] == "SOC" and r["event_time"] == "2026-10-13T08:10:00+05:30"
    assert wa.line(r) == "A,B LS SOC 08:10 Ravi\n- wet paddy"

    # Amit is about to post the same thing — the check warns him
    chk = amit.post("/api/reports/check", json={"trucks": ["A"], "verb": "LS", "site": "SOC",
                                                "event_time": "2026-10-13T08:12"}).json()
    assert chk["warnings"] == ["A LS already reported 08:10 Ravi"]

    # custom site → created on the fly
    chk = amit.post("/api/reports/check", json={"trucks": ["C"], "verb": "LS", "site": "Lal Ghadi"}).json()
    assert chk["new_entries"] == ["new site: Lal Ghadi"]

    # edit → strikethrough diff in outbox
    e = ravi.patch(f"/api/reports/{r['id']}", json={"verb": "LO"}).json()
    assert e["verb"] == "LO"
    rows = client.app.state.conn.execute("SELECT kind, payload FROM outbox ORDER BY id").fetchall()
    assert [k["kind"] for k in rows] == ["shift", "report", "edit"]
    p = json.loads(rows[-1]["payload"])
    assert wa.edit_line(p["before"], p["after"]) == "A,B ~LS~ LO SOC 08:10 Ravi\n- wet paddy"

    # only owner (or admin) edits
    assert amit.patch(f"/api/reports/{r['id']}", json={"verb": "LS"}).status_code == 403
    assert amit.delete(f"/api/reports/{r['id']}").status_code == 403

    s = ravi.get("/api/summary/shift").json()
    assert s["counts"]["loaded"] == 2 and s["counts"]["loaded_by_site"] == {"SOC": 2}
    assert s["text"].startswith("Shift 13 Oct #1 06:00-now\nLoaded 2: SOC 2")

    assert boss.delete(f"/api/reports/{r['id']}").status_code == 200
    assert ravi.get("/api/reports").json() == []
    assert ravi.get("/api/summary/shift").json()["counts"]["loaded"] == 0


def test_alias_merge_unmerge_keeps_history(client):
    boss = login(client, "boss@x.org", name="Boss")
    seed(boss)
    u = login(client, "u@x.org", "U")
    u.post("/api/shifts/start", json={"at": "2026-10-13T06:00"})
    r = u.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "Soc Field",
                                     "event_time": "2026-10-13T08:00"}).json()
    assert r["site"] == "Soc Field"
    items = {(i["kind"], i["code"]): i for i in boss.get("/api/admin/registry").json()}
    new_id, soc_id = items[("site", r["site"])]["id"], items[("site", "SOC")]["id"]

    assert boss.post(f"/api/admin/registry/{new_id}/merge", json={"into": soc_id}).status_code == 200
    assert u.get("/api/reports").json()[0]["site"] == "SOC"
    assert u.get("/api/summary/shift").json()["counts"]["position"] == {"loading": ["A"]}
    reg = u.get("/api/registry").json()
    assert next(s for s in reg["site"] if s["code"] == "SOC")["aliases"] == [r["site"]]

    # deleting a referenced alias only deactivates it; history still resolves
    assert boss.delete(f"/api/admin/registry/{new_id}").json() == {"result": "deactivated"}
    assert u.get("/api/reports").json()[0]["site"] == "SOC"

    assert boss.post(f"/api/admin/registry/{new_id}/unmerge").status_code == 200
    assert u.get("/api/reports").json()[0]["site"] == r["site"]

    # verbs can't be merged; aliases resolve on input
    verbs = {i["code"]: i["id"] for i in boss.get("/api/admin/registry").json() if i["kind"] == "verb"}
    assert boss.post(f"/api/admin/registry/{verbs['LS']}/merge", json={"into": verbs['LO']}).status_code == 400
    trucks = {i["code"]: i["id"] for i in boss.get("/api/admin/registry").json() if i["kind"] == "truck"}
    assert boss.post(f"/api/admin/registry/{trucks['D']}/alias", json={"code": "Dee"}).status_code == 200
    assert boss.post(f"/api/admin/registry/{trucks['C']}/alias", json={"code": "dee"}).status_code == 400
    r2 = u.post("/api/reports", json={"trucks": ["dee"], "verb": "LS", "site": "KN4"}).json()
    assert r2["trucks"] == ["D"]


def test_shift_rules(client):
    u = login(client, "boss@x.org", "Boss")
    a = u.post("/api/shifts/start", json={"at": "2026-10-13T06:00"}).json()
    b = u.post("/api/shifts/start", json={"at": "2026-10-13T18:00"}).json()  # auto-ends a
    shifts = u.get("/api/shifts").json()
    assert [s["open"] for s in shifts] == [True, False]
    assert shifts[1]["ended_at"] == "2026-10-13T18:00:00+05:30"
    assert u.post("/api/shifts/start", json={"at": "2026-10-13T12:00"}).status_code == 400
    assert u.patch(f"/api/shifts/{a['id']}", json={"ended_at": "2026-10-13T19:00"}).status_code == 400  # overlap
    assert u.post("/api/shifts/end", json={"at": "2026-10-13T17:00"}).status_code == 400  # before start
    assert u.post("/api/shifts/end", json={"at": "2026-10-14T02:00"}).status_code == 200
    assert u.post("/api/shifts/end", json={}).status_code == 400  # none open
    assert b["id"] != a["id"]


def test_admin_only(client):
    u = login(client, "u@x.org", "U")
    assert u.get("/api/admin/users").status_code == 403
    boss = login(client, "boss@x.org", "Boss")
    assert boss.put("/api/admin/settings", json={"fleet_mode": "full"}).json()["fleet_mode"] == "full"
    assert boss.put("/api/admin/settings", json={"fleet_mode": "loud"}).status_code == 400
    uid = u.get("/api/me").json()["id"]
    boss.patch(f"/api/admin/users/{uid}", json={"disabled": True})
    assert u.get("/api/me").status_code == 401


def test_seed_sites_idempotent(client):
    from app import seed
    conn = client.app.state.conn
    seed.seed(conn)
    seed.seed(conn)
    u = login(client, "u@x.org", "U")
    sites = {s["code"]: s for s in u.get("/api/registry").json()["site"]}
    assert len(sites) == 14 and sites["SKP"]["aliases"] == ["SDP"] and sites["BG"]["site_type"] == "depot"
    u.post("/api/shifts/start", json={})
    assert u.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "lal jameen"}).json()["site"] == "LJ"

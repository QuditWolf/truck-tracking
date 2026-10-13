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
    assert wa.line(r) == "A,B LS SOC @13 Oct 08:10\n- wet paddy\n~Ravi"  # not today → dated

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
    assert wa.edit_line(p["before"], p["after"]) == "A,B ~LS~ LO SOC @13 Oct 08:10\n- wet paddy\n~Ravi"

    # only owner (or admin) edits
    assert amit.patch(f"/api/reports/{r['id']}", json={"verb": "LS"}).status_code == 403
    assert amit.delete(f"/api/reports/{r['id']}").status_code == 403

    s = ravi.get("/api/summary/shift").json()
    assert s["counts"]["loaded"] == 2 and s["counts"]["loaded_by_site"] == {"SOC": 2}
    assert s["text"].startswith("Shift 13 Oct #1 06:00-now\nLoaded 2: SOC 2")

    b = ravi.get("/api/board").json()
    pos = {t["truck"]: t["position"] for t in b["trucks"]}
    assert pos == {"A": "loaded", "B": "loaded", "C": "idle", "D": "idle"}

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
    assert boss.put("/api/admin/settings", json={"summary_fleet": "1"}).json()["summary_fleet"] == "1"
    assert boss.put("/api/admin/settings", json={"summary_fleet": "yes"}).status_code == 400
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
    assert [t["code"] for t in u.get("/api/registry").json()["truck"]] == ["A", "B", "C", "D", "E"]
    u.post("/api/shifts/start", json={})
    assert u.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "lal jameen"}).json()["site"] == "LJ"


def test_truck_plate_and_notes(client):
    boss = login(client, "boss@x.org", "Boss")
    tid = boss.post("/api/admin/registry", json={"kind": "truck", "code": "A", "plate": "HR 26 AB 1234"}).json()["id"]
    boss.patch(f"/api/admin/registry/{tid}", json={"notes": "Driver: Raju"})
    t = boss.get("/api/registry").json()["truck"][0]
    assert (t["plate"], t["notes"]) == ("HR 26 AB 1234", "Driver: Raju")


def test_migration_adds_columns_to_old_db(tmp_path, monkeypatch):
    import sqlite3
    from app import core
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "old.db"))
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE registry (id INTEGER PRIMARY KEY, kind TEXT, code TEXT, label TEXT, site_type TEXT, "
                "merged_into INTEGER, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, created_by INTEGER, created_at TEXT)")
    old.commit()
    old.close()
    conn = core.connect(str(tmp_path / "old.db"))
    core.init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(registry)")}
    assert {"plate", "notes"} <= cols
    backups = list((tmp_path / "backups").glob("paddy-*-pre-migration.db"))
    assert len(backups) == 1  # copy taken before altering
    assert sqlite3.connect(backups[0]).execute("PRAGMA table_info(registry)").fetchall()  # readable
    core.init_db(conn)  # nothing pending now → no second backup
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1


def test_first_report_can_start_shift_atomically(client):
    u = login(client, "u@x.org", "U")
    r = u.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC",
                                     "event_time": "2026-10-13T07:15", "start_shift": True}).json()
    assert r["flags"] == []
    s = u.get("/api/shifts").json()
    assert len(s) == 1 and s[0]["started_at"] == "2026-10-13T07:15:00+05:30" and s[0]["default_site"] == "SOC"
    # second report with start_shift is a no-op for shifts (one already open)
    u.post("/api/reports", json={"trucks": ["B"], "verb": "LS", "site": "SOC", "start_shift": True})
    assert len(u.get("/api/shifts").json()) == 1


def test_parallel_requests_do_not_share_cursor(client):
    from concurrent.futures import ThreadPoolExecutor
    u = login(client, "u@x.org", "U")
    u.post("/api/shifts/start", json={})
    for t in "ABCDEFGH":
        u.post("/api/reports", json={"trucks": [t], "verb": "LS", "site": "SOC"})
    paths = ["/api/board", "/api/feed", "/api/shifts", "/api/reports", "/api/summary/shift", "/api/me"] * 8
    with ThreadPoolExecutor(12) as ex:
        codes = list(ex.map(lambda p: u.get(p).status_code, paths))
    assert set(codes) == {200}


def test_sites_sorted_by_current_then_previous_shift(client):
    boss = login(client, "boss@x.org", "Boss")
    seed(boss)  # sites DAIRY, KN4, SOC (alphabetical by default)
    boss.post("/api/admin/registry", json={"kind": "site", "code": "LG", "site_type": "loading"})
    order = lambda: [s["code"] for s in boss.get("/api/registry").json()["site"]]
    assert order() == ["DAIRY", "KN4", "LG", "SOC"]

    boss.post("/api/shifts/start", json={"at": "2026-10-12T06:00"})
    boss.post("/api/reports", json={"trucks": ["A", "B"], "verb": "LS", "site": "LG", "event_time": "2026-10-12T07:00"})
    boss.post("/api/reports", json={"trucks": ["C"], "verb": "LS", "site": "KN4", "event_time": "2026-10-12T07:10"})
    assert order() == ["LG", "KN4", "DAIRY", "SOC"]  # A,B counts as 2 events

    boss.post("/api/shifts/start", json={"at": "2026-10-13T06:00"})  # previous shift ends here
    boss.post("/api/reports", json={"trucks": ["D"], "verb": "LS", "site": "SOC", "event_time": "2026-10-13T07:00"})
    assert order() == ["SOC", "LG", "KN4", "DAIRY"]  # current shift first, then previous shift


def test_overnight_shift_label_shows_end_date():
    from datetime import datetime
    from app.core import IST
    from app.summary import shift_label
    from app.trips import Shift
    a = Shift(1, datetime(2026, 10, 13, 18, 0, tzinfo=IST), datetime(2026, 10, 14, 5, 0, tzinfo=IST))
    b = Shift(2, datetime(2026, 10, 14, 6, 0, tzinfo=IST), datetime(2026, 10, 14, 17, 0, tzinfo=IST))
    assert shift_label(a, [a, b]) == "Shift 13 Oct #1 18:00-14 Oct 05:00"
    assert shift_label(b, [a, b]) == "Shift 14 Oct #1 06:00-17:00"


def test_admin_edits_users_and_disables_temporarily(client):
    from datetime import timedelta
    from app import core
    boss = login(client, "boss@x.org", "Boss")
    u = login(client, "u@x.org", "Ravi")
    uid = u.get("/api/me").json()["id"]
    r = boss.patch(f"/api/admin/users/{uid}", json={"name": "Ravi Kumar", "phone": "+91 99999 00000"}).json()
    assert (r["name"], r["phone"]) == ("Ravi Kumar", "+91 99999 00000")
    assert u.get("/api/me").json()["name"] == "Ravi Kumar"
    assert boss.patch(f"/api/admin/users/{uid}", json={"phone": "123"}).status_code == 400

    until = core.iso(core.now() + timedelta(days=1))
    r = boss.patch(f"/api/admin/users/{uid}", json={"disabled": True, "disabled_until": until}).json()
    assert r["disabled"] and r["disabled_until"].startswith(until[:16])
    assert u.get("/api/me").status_code == 401  # signed out at once
    assert u.post("/api/auth/dev", json={"email": "u@x.org"}).status_code == 403

    # time passes: access returns by itself
    client.app.state.conn.execute("UPDATE users SET disabled_until = '2020-01-01T00:00:00+05:30' WHERE id = ?", (uid,))
    assert u.get("/api/me").status_code == 200

    boss.patch(f"/api/admin/users/{uid}", json={"disabled": True})  # indefinitely
    assert u.get("/api/me").status_code == 401
    boss.patch(f"/api/admin/users/{uid}", json={"disabled": False})
    assert u.get("/api/me").status_code == 200

    boss_id = boss.get("/api/me").json()["id"]
    assert boss.patch(f"/api/admin/users/{boss_id}", json={"disabled": True}).status_code == 400
    assert boss.patch(f"/api/admin/users/{uid}", json={"disabled": True, "disabled_until": "2020-01-01T00:00"}).status_code == 400
    audit = boss.get("/api/admin/audit?entity=user").json()
    assert {"update", "disable", "enable"} <= {a["action"] for a in audit}


def test_upgrade_leaves_existing_users_enabled(tmp_path, monkeypatch):
    """Live upgrade: users table without disabled_until → column added, nobody becomes disabled."""
    import sqlite3
    from app import auth, core
    monkeypatch.setattr(core, "DB_PATH", str(tmp_path / "live.db"))
    old = sqlite3.connect(tmp_path / "live.db")
    old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub TEXT UNIQUE NOT NULL, email TEXT NOT NULL, "
                "name TEXT, phone TEXT, disabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    old.executemany("INSERT INTO users (google_sub, email, name, phone, created_at) VALUES (?, ?, ?, ?, '2026-10-13')",
                    [(f"g{i}", f"u{i}@x.org", f"U{i}", "9876543210") for i in range(5)])
    old.commit()
    old.close()
    conn = core.connect(str(tmp_path / "live.db"))
    core.init_db(conn)
    rows = conn.execute("SELECT * FROM users").fetchall()
    assert len(rows) == 5 and all(r["disabled_until"] is None for r in rows)
    assert not any(auth.is_disabled(r) for r in rows)
    assert all(auth.user_dict(r)["disabled"] is False for r in rows)

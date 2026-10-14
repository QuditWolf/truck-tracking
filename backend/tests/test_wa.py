import json
import re

import pytest

from app import core, relay, wa_client
from tests.conftest import login

FLEET, CONTROL = "111@g.us", "222@g.us"


class FakeBridge:
    def __init__(self):
        self.sent = []  # (jid, text, quote)
        self.state = "open"
        self.n = 0

    def __call__(self, method, path, body=None, timeout=0):
        if path == "/status":
            return {"state": self.state}
        if path == "/groups":
            return [{"jid": FLEET, "subject": "Fleet", "size": 30}, {"jid": CONTROL, "subject": "Control", "size": 4}]
        if path == "/send":
            if self.state != "open":
                raise wa_client.BridgeError("WhatsApp closed")
            self.n += 1
            self.sent.append((body["jid"], body["text"], body.get("quote")))
            return {"id": f"OUT{self.n}"}
        return {}

    def texts(self, jid):
        return [t for j, t, _ in self.sent if j == jid]


@pytest.fixture()
def wa(client):
    fake = FakeBridge()
    wa_client.set_transport(fake)
    boss = login(client, "boss@x.org", "Boss Man")
    for code, t in (("SOC", "loading"), ("KN4", "loading"), ("DAIRY", "unloading")):
        boss.post("/api/admin/registry", json={"kind": "site", "code": code, "site_type": t})
    for code in "ABCD":
        boss.post("/api/admin/registry", json={"kind": "truck", "code": code})
    assert boss.put("/api/admin/settings", json={"wa_enabled": "1", "fleet_jid": FLEET, "control_jid": CONTROL}).status_code == 200
    fake.boss = boss
    yield fake
    wa_client.set_transport(wa_client._http)


def drain(client):
    relay.run_once(client.app.state.conn)


def inbound(client, jid, text, id_, sender="919876500001@s.whatsapp.net", name="Amit", **kw):
    r = client.post("/api/wa/inbound", headers={"x-wa-token": wa_client.TOKEN},
                    json={"id": id_, "jid": jid, "text": text, "sender": sender, "push_name": name,
                          "ts": core.now().timestamp(), **kw})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_web_report_relayed_to_both_groups_and_edit_replies_to_original(client, wa):
    boss = wa.boss
    boss.post("/api/shifts/start", json={"site": "SOC"})
    drain(client)
    assert re.fullmatch(r"Shift start SOC @\d\d:\d\d\n~Boss", wa.texts(CONTROL)[0])
    assert wa.texts(FLEET) == []  # silent mode: notices stay in control

    r = boss.post("/api/reports", json={"trucks": ["A", "B"], "verb": "LS", "site": "SOC", "remarks": "wet"}).json()
    drain(client)
    line = wa.texts(FLEET)[-1]
    assert re.fullmatch(r"A,B LS SOC @\d\d:\d\d\n- wet\n~Boss", line)  # first name only
    assert wa.texts(CONTROL)[-1] == line

    relays = {j: f"OUT{i + 1}" for i, (j, t, _) in enumerate(wa.sent) if t == line}
    boss.patch(f"/api/reports/{r['id']}", json={"verb": "LO"})
    drain(client)
    edits = {j: q for j, t, q in wa.sent if "~LS~ LO" in t}
    assert edits[FLEET]["id"] == relays[FLEET] and edits[CONTROL]["id"] == relays[CONTROL]
    assert edits[FLEET]["from_me"] is True

    boss.delete(f"/api/reports/{r['id']}")
    drain(client)
    assert re.fullmatch(r"~A,B LO SOC @\d\d:\d\d~\ndeleted ~Boss", wa.texts(FLEET)[-1])


def test_master_switch_off_skips_everything(client, wa):
    wa.boss.put("/api/admin/settings", json={"wa_enabled": "0"})
    wa.boss.post("/api/shifts/start", json={})
    drain(client)
    assert wa.sent == []
    assert client.app.state.conn.execute("SELECT status FROM outbox").fetchone()["status"] == "skipped"
    assert inbound(client, FLEET, "A LS SOC", "M1") == "off"


def test_relay_toggles_and_full_mode(client, wa):
    wa.boss.put("/api/admin/settings", json={"relay_control": "0", "notice_fleet": "1", "summary_fleet": "1"})
    wa.boss.post("/api/shifts/start", json={})
    wa.boss.post("/api/reports", json={"trucks": ["C"], "verb": "LS", "site": "KN4"})
    drain(client)
    assert any(t.startswith("Shift start") for t in wa.texts(FLEET))  # full mode: notices in fleet too
    assert any(t.startswith("C LS KN4") for t in wa.texts(FLEET))
    assert not any(t.startswith("C LS KN4") for t in wa.texts(CONTROL))  # relay_control off


def test_disconnected_keeps_pending_then_sends(client, wa):
    wa.state = "closed"
    wa.boss.post("/api/shifts/start", json={})
    drain(client)
    assert wa.sent == []
    wa.state = "open"
    drain(client)
    assert len(wa.sent) == 1


def test_typed_fleet_message_becomes_report_with_ack(client, wa):
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    drain(client)
    assert inbound(client, FLEET, "a, b ls", "M1") == "event"  # default site from shift
    drain(client)
    ack = wa.texts(CONTROL)[-1]
    assert ack.startswith("A,B LS SOC") and ack.endswith("Amit")
    rep = wa.boss.get("/api/feed").json()[0]
    assert rep["source"] == "wa" and rep["wa_msg_id"] == "M1" and rep["user"] == "Amit"
    assert inbound(client, FLEET, "A LS SOC", "M2") == "event"
    drain(client)
    assert "! A LS SOC already reported @" in wa.texts(CONTROL)[-1]

    # web edit of a WA report: replies to the operator's own message in the fleet group
    wa.boss.patch(f"/api/reports/{rep['id']}", json={"verb": "LO"})
    drain(client)
    fleet_edit = [(t, q) for j, t, q in wa.sent if j == FLEET and "~LS~" in t]
    assert fleet_edit and fleet_edit[0][1]["id"] == "M1" and fleet_edit[0][1]["from_me"] is False


def test_unparsed_attempt_asks_and_chat_is_ignored(client, wa):
    wa.boss.post("/api/shifts/start", json={})
    drain(client)
    assert inbound(client, FLEET, "A LS somewhere", "M1") == "unparsed"
    assert inbound(client, FLEET, "good morning all", "M2") == "chat"
    drain(client)
    assert wa.texts(CONTROL)[-1] == "? A LS somewhere\n! site unclear, reply with e.g. A LS KN4\n~Amit"


def test_sender_matched_to_signed_up_user_by_phone(client, wa):
    ravi = login(client, "ravi@x.org", "Ravi Kumar", phone="+91 98765 00002")
    wa.boss.post("/api/shifts/start", json={})
    inbound(client, FLEET, "D US DAIRY", "M1", sender="12345@lid", sender_alt="919876500002@s.whatsapp.net", name="RK")
    assert ravi.get("/api/reports").json()[0]["trucks"] == ["D"]


def test_control_commands(client, wa):
    assert inbound(client, CONTROL, "shift start kn4", "C1") == "shift_start"
    # end must be after start (whole minutes): pretend it started earlier
    client.app.state.conn.execute("UPDATE shifts SET started_at = '2026-01-01T06:00:00+05:30'")
    assert inbound(client, CONTROL, "Summary", "C2") == "summary"
    assert inbound(client, CONTROL, "help", "C3") == "help"
    assert inbound(client, CONTROL, "shift end", "C4") == "shift_end"
    assert inbound(client, CONTROL, "shift end", "C5") == "error"
    drain(client)
    texts = wa.texts(CONTROL)
    assert texts[0].startswith("Shift start KN4 @")
    assert any(t.startswith("Shift ") and "Loaded 0" in t for t in texts)
    assert any(t.startswith("Commands:") for t in texts)
    assert any(t.startswith("Shift end @") for t in texts)
    assert texts[-1] == "Not done: no open shift"
    # summary replies quote the command
    assert next(q for j, t, q in wa.sent if "Loaded 0" in t)["id"] == "C2"


def test_inbound_requires_token(client, wa):
    r = client.post("/api/wa/inbound", json={"id": "x", "jid": FLEET, "text": "A LS SOC"})
    assert r.status_code == 401


def test_admin_wa_endpoints(client, wa):
    st = wa.boss.get("/api/admin/wa").json()
    assert st["status"]["state"] == "open"
    assert [g["subject"] for g in wa.boss.get("/api/admin/wa/groups").json()] == ["Fleet", "Control"]
    assert wa.boss.post("/api/admin/wa/test", json={"target": "control"}).status_code == 200
    assert wa.texts(CONTROL)[-1].startswith("Dayalbagh Truck Tracking connected")
    assert wa.boss.put("/api/admin/settings", json={"fleet_jid": "notagroup"}).status_code == 400


def test_periodic_summary_only_when_changed(client, wa):
    conn = client.app.state.conn
    summaries = lambda: [t for t in wa.texts(CONTROL) if t.startswith("Shift ") and "Loaded" in t]
    wa.boss.post("/api/shifts/start", json={})
    drain(client)
    assert summaries() == []  # no summary before one interval has passed
    conn.execute("UPDATE shifts SET started_at = '2026-01-01T06:00:00+05:30'")
    drain(client)  # interval elapsed: summary sent (+ one stale-shift warning)
    assert len(summaries()) == 1
    assert sum("send 'shift end'" in t for t in wa.texts(CONTROL)) == 1
    core.set_setting(conn, "_last_summary_at", "2000-01-01T00:00:00+05:30")
    drain(client)  # interval elapsed but nothing changed → no resend, no second warning
    assert len(summaries()) == 1 and sum("send 'shift end'" in t for t in wa.texts(CONTROL)) == 1
    wa.boss.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC"})
    core.set_setting(conn, "_last_summary_at", "2000-01-01T00:00:00+05:30")
    drain(client)
    assert len(summaries()) == 2 and "Loading: A" in summaries()[-1]


def test_parse_strict():
    from datetime import datetime
    from app.core import IST
    from app.parse import parse

    class Reg:
        rows = {("truck", "a"): "A", ("truck", "b"): "B", ("verb", "ls"): "LS", ("verb", "us"): "US",
                ("site", "kn4"): "KN4", ("site", "kua no 4"): "KN4", ("site", "dairy"): "DAIRY"}

        def find(self, kind, text, active_only=True):
            code = self.rows.get((kind, text.lower()))
            return type("I", (), {"code": code})() if code else None

    sent = datetime(2026, 10, 13, 14, 40, tzinfo=IST)
    p = parse("A,B LS kua no 4 14:32", Reg(), sent)
    assert p.ok and p.trucks == ["A", "B"] and p.site == "KN4" and f"{p.time:%H:%M}" == "14:32"
    assert parse("A US", Reg(), sent, default_site="KN4").missing == ["site"]  # default site only for LS/LO
    assert parse("A LS", Reg(), sent, default_site="KN4").site == "KN4"
    assert not parse("A LS KN4 extra", Reg(), sent).ok
    assert f"{parse('A LS KN4 23:50', Reg(), sent).time:%d %H:%M}" == "12 23:50"  # future time → yesterday
    assert f"{parse('A LS KN4 @12 Oct 23:50', Reg(), sent).time:%d %b %H:%M}" == "12 Oct 23:50"
    assert f"{parse('A LS KN4 @ 14.05', Reg(), sent).time:%H:%M}" == "14:05"
    p = parse("a b ls kn4 @14:00\n- half load\n- slow\n! ignored\n~Someone", Reg(), sent)
    assert p.ok and p.trucks == ["A", "B"] and p.remarks == "half load; slow"


def test_fleet_posting_switch_silences_fleet_group_entirely(client, wa):
    wa.boss.put("/api/admin/settings", json={"notice_fleet": "1", "summary_fleet": "1"})
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    r = wa.boss.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC"}).json()
    drain(client)
    assert wa.texts(FLEET)  # posting on: relay + notices reach fleet
    n = len(wa.texts(FLEET))

    wa.boss.put("/api/admin/settings", json={"send_fleet": "0"})
    wa.boss.patch(f"/api/reports/{r['id']}", json={"verb": "LO"})  # original lives in fleet
    wa.boss.post("/api/reports", json={"trucks": ["B"], "verb": "LS", "site": "SOC"})
    inbound(client, FLEET, "C LS SOC", "M9")  # full mode would reply in fleet
    drain(client)
    assert len(wa.texts(FLEET)) == n  # nothing new in fleet
    control = wa.texts(CONTROL)
    assert any("~LS~ LO" in t for t in control) and any(t.startswith("B LS SOC") for t in control)
    assert any(t.startswith("C LS SOC") for t in control)  # ack still reaches control
    assert inbound(client, FLEET, "D LS SOC", "M10") == "event"  # still reads the fleet group


def test_bot_format_parses_back_and_remarks_are_kept(client, wa):
    from datetime import timedelta
    hm = f"{core.now() - timedelta(minutes=5):%H:%M}"
    wa.boss.post("/api/shifts/start", json={"at": core.iso(core.now() - timedelta(minutes=30))})
    drain(client)
    # exactly what the bot writes, posted back by a human (copy/forward)
    assert inbound(client, FLEET, f"A,B LS KN4 @{hm}\n- wet paddy\n~Ravi", "M1") == "event"
    rep = wa.boss.get("/api/feed").json()[0]
    assert rep["trucks"] == ["A", "B"] and rep["remarks"] == "wet paddy" and rep["event_time"][11:16] == hm
    drain(client)
    assert wa.texts(CONTROL)[-1] == f"A,B LS KN4 @{hm}\nwet paddy\n~Amit".replace("\nwet", "\n- wet")
    # a line that isn't a remark/signature makes it ambiguous → question, nothing saved
    assert inbound(client, FLEET, "C LS KN4\nD LS KN4", "M2") == "unparsed"


def test_control_commands_take_a_time(client, wa):
    inbound(client, CONTROL, "shift start soc @05:30", "C1")
    s = wa.boss.get("/api/shifts").json()[0]
    assert s["started_at"].endswith("05:30:00+05:30") or s["started_at"][11:16] == "05:30"
    assert s["default_site"] == "SOC"


def test_own_echo_and_redelivery_are_ignored(client, wa):
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    drain(client)
    sent_id = "OUT1"  # the bot's "Shift start SOC @..." in control
    echo = wa.texts(CONTROL)[0]
    assert inbound(client, CONTROL, echo, sent_id, from_me=True) == "own"
    assert inbound(client, FLEET, "A LS SOC", "M1") == "event"
    assert inbound(client, FLEET, "A LS SOC", "M1") == "duplicate"
    assert len(wa.boss.get("/api/feed").json()) == 1
    assert len(wa.boss.get("/api/shifts").json()) == 1


def test_three_tiers_route_independently(client, wa):
    conn = client.app.state.conn
    wa.boss.put("/api/admin/settings", json={"relay_fleet": "1", "relay_control": "0",
                                             "summary_fleet": "1", "summary_control": "0",
                                             "notice_fleet": "0", "notice_control": "1"})
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    wa.boss.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC"})
    inbound(client, FLEET, "B LS SOC", "M1")
    wa.boss.post("/api/admin/wa/summary")
    drain(client)
    fleet, control = wa.texts(FLEET), wa.texts(CONTROL)
    assert any(t.startswith("A LS SOC") for t in fleet) and not any(t.startswith("A LS SOC") for t in control)
    assert any("Loaded" in t for t in fleet) and not any("Loaded" in t for t in control)
    assert any(t.startswith("Shift start") for t in control) and not any(t.startswith("Shift start") for t in fleet)
    assert any(t.startswith("B LS SOC") for t in control) and not any(t.startswith("B LS SOC") for t in fleet)

    wa.boss.put("/api/admin/settings", json={"notice_fleet": "1"})  # both: reply in fleet + line in control
    inbound(client, FLEET, "C LS SOC", "M2")
    drain(client)
    assert next(q for j, t, q in wa.sent if j == FLEET and t.startswith("C LS SOC"))["id"] == "M2"
    assert any(t.startswith("C LS SOC") for t in wa.texts(CONTROL))


def test_old_fleet_mode_setting_is_migrated(tmp_path, monkeypatch):
    from app import core as c
    monkeypatch.setattr(c, "DB_PATH", str(tmp_path / "x.db"))
    for mode, expect in (("full", "1"), ("silent", "0")):
        conn = c.connect(str(tmp_path / f"{mode}.db"))
        conn.executescript("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
        conn.execute("INSERT INTO settings VALUES ('fleet_mode', ?)", (mode,))
        c.init_db(conn)
        assert c.setting(conn, "summary_fleet") == expect and c.setting(conn, "notice_fleet") == expect
        assert c.setting(conn, "summary_control") == "1" and c.setting(conn, "notice_control") == "1"


def test_manual_count_relayed(client, wa):
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    m = wa.boss.post("/api/manual", json={"truck": "PB10", "kind": "load", "count": 2, "site": "SOC", "note": "contractor"}).json()
    wa.boss.delete(f"/api/manual/{m['id']}")
    drain(client)
    fleet = wa.texts(FLEET)
    assert "PB10 +2 loads SOC\n- manual add for earlier untracked truck\n- contractor\n~Boss" in fleet
    assert "~PB10 +2 loads SOC~\nmanual add removed ~Boss" in fleet


def test_signature_uses_full_name_only_when_first_names_clash(client, wa):
    from app.relay import who
    conn = client.app.state.conn
    login(client, "r1@x.org", "Ravi Kumar", phone="9876500001")
    assert who(conn, "Ravi Kumar") == "Ravi"
    login(client, "r2@x.org", "Ravi Sharma", phone="9876500002")
    assert who(conn, "Ravi Kumar") == "Ravi Kumar" and who(conn, "Ravi Sharma") == "Ravi Sharma"
    assert who(conn, "Boss Man") == "Boss"
    login(client, "r3@x.org", "Ravi Kumar", phone="9876503210")
    assert who(conn, "Ravi Kumar") in ("Ravi Kumar (0001)", "Ravi Kumar (3210)")

    r = login(client, "r2@x.org", None)  # existing Ravi Sharma
    r.post("/api/shifts/start", json={})
    r.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC"})
    drain(client)
    assert wa.texts(FLEET)[-1].endswith("~Ravi Sharma")
    assert r.get("/api/me").json()["signature"] == "Ravi Sharma"


def test_manual_entry_control_always_fleet_optional(client, wa):
    wa.boss.put("/api/admin/settings", json={"relay_control": "0"})  # control still gets manual entries
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    quiet = wa.boss.post("/api/manual", json={"trucks": ["Q1"], "kind": "load", "count": 1, "post_fleet": False}).json()[0]
    wa.boss.post("/api/manual", json={"trucks": ["Q2"], "kind": "load", "count": 1})
    wa.boss.delete(f"/api/manual/{quiet['id']}")
    drain(client)
    fleet, control = wa.texts(FLEET), wa.texts(CONTROL)
    assert any(t.startswith("Q1 +1 load") for t in control) and not any(t.startswith("Q1 +1 load") for t in fleet)
    assert any("~Q1 +1 load" in t for t in control) and not any("~Q1 +1 load" in t for t in fleet)  # removal too
    assert any(t.startswith("Q2 +1 load") for t in control) and any(t.startswith("Q2 +1 load") for t in fleet)


def test_real_free_text_messages_from_14_oct():
    from datetime import datetime
    from app.core import IST
    from app.parse import parse

    class Reg:
        trucks = {"a": "A", "b": "B", "d": "D", "f": "F", "up26r3436": "UP26R3436"}
        sites = {"skp": "SKP", "bg": "BG"}
        verbs = {"ls": "LS", "lo": "LO", "left": "LEFT", "enter": "ENTER", "us": "US", "uo": "UO"}

        def find(self, kind, text, active_only=True):
            table = {"truck": self.trucks, "site": self.sites, "verb": self.verbs}[kind]
            code = table.get(text.lower())
            return type("I", (), {"code": code})() if code else None

    at = lambda hm: datetime(2026, 10, 14, int(hm[:2]), int(hm[3:]), tzinfo=IST)
    p = parse("D,UP26R3436 left skp loaded at 3:26", Reg(), at("15:27"))
    assert p.ok and p.trucks == ["D", "UP26R3436"] and p.verb == "LEFT" and p.site == "SKP" and f"{p.time:%H:%M}" == "15:26"
    p = parse("B F LS at 3:35", Reg(), at("15:36"), default_site="SKP")
    assert p.ok and p.trucks == ["B", "F"] and p.site == "SKP" and f"{p.time:%H:%M}" == "15:35"
    p = parse("A LS at 5:08pm", Reg(), at("17:09"), default_site="SKP")
    assert p.ok and p.site == "SKP" and f"{p.time:%H:%M}" == "17:08"
    p = parse("Trolley D LS at 16:05", Reg(), at("16:06"), default_site="SKP")
    assert p.ok and p.trucks == ["D"] and f"{p.time:%H:%M}" == "16:05"
    p = parse("D reached bg at 3:38pm", Reg(), at("15:39"))
    assert p.ok and p.verb == "ENTER" and p.site == "BG" and f"{p.time:%H:%M}" == "15:38"
    p = parse("B left for BG at 3:37", Reg(), at("15:38"))
    assert not p.ok and p.missing == ["site"]  # destination isn't the site it left → bot asks
    p = parse("A LS at 3:41", Reg(), at("15:42"))  # no default loading site → ask, never guess BG
    assert not p.ok and p.missing == ["site"]


def test_default_site_never_an_unloading_site(client, wa):
    boss = wa.boss
    boss.post("/api/shifts/start", json={"site": "DAIRY"})  # shift default = unloading site
    assert inbound(client, FLEET, "A LS", "M1") == "unparsed"  # asks instead of 'A LS DAIRY'


def test_ambiguous_ten_thirty_at_night_is_pm():
    from datetime import datetime
    from app.core import IST
    from app.parse import take_time
    sent = datetime(2026, 10, 14, 22, 35, tzinfo=IST)
    assert f"{take_time(['10:30'], sent)[1]:%H:%M}" == "22:30"
    assert f"{take_time(['05:30'], sent)[1]:%H:%M}" == "05:30"


def test_ls_at_unloading_site_is_asked_not_recorded(client, wa):
    wa.boss.post("/api/shifts/start", json={"site": "SOC"})
    assert inbound(client, FLEET, "A LS DAIRY", "M1") == "unparsed"
    assert inbound(client, FLEET, "A US SOC", "M2") == "unparsed"
    assert inbound(client, FLEET, "A ENTER DAIRY", "M3") == "event"  # ENTER/LEFT fine anywhere
    assert inbound(client, FLEET, "A LS SOC", "M4") == "event"

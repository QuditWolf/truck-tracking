import json

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
    assert wa.texts(CONTROL)[0].startswith("Shift started") and wa.texts(CONTROL)[0].endswith("SOC Boss")
    assert wa.texts(FLEET) == []  # silent mode: notices stay in control

    r = boss.post("/api/reports", json={"trucks": ["A", "B"], "verb": "LS", "site": "SOC", "remarks": "wet"}).json()
    drain(client)
    line = wa.texts(FLEET)[-1]
    assert line.startswith("A,B LS SOC ") and line.endswith(" Boss\n- wet")  # first name only
    assert wa.texts(CONTROL)[-1] == line

    relays = {j: f"OUT{i + 1}" for i, (j, t, _) in enumerate(wa.sent) if t == line}
    boss.patch(f"/api/reports/{r['id']}", json={"verb": "LO"})
    drain(client)
    edits = {j: q for j, t, q in wa.sent if "~LS~ LO" in t}
    assert edits[FLEET]["id"] == relays[FLEET] and edits[CONTROL]["id"] == relays[CONTROL]
    assert edits[FLEET]["from_me"] is True

    boss.delete(f"/api/reports/{r['id']}")
    drain(client)
    assert wa.texts(FLEET)[-1].startswith("~A,B LO SOC") and wa.texts(FLEET)[-1].endswith("~ deleted")


def test_master_switch_off_skips_everything(client, wa):
    wa.boss.put("/api/admin/settings", json={"wa_enabled": "0"})
    wa.boss.post("/api/shifts/start", json={})
    drain(client)
    assert wa.sent == []
    assert client.app.state.conn.execute("SELECT status FROM outbox").fetchone()["status"] == "skipped"
    assert inbound(client, FLEET, "A LS SOC", "M1") == "off"


def test_relay_toggles_and_full_mode(client, wa):
    wa.boss.put("/api/admin/settings", json={"relay_control": "0", "fleet_mode": "full"})
    wa.boss.post("/api/shifts/start", json={})
    wa.boss.post("/api/reports", json={"trucks": ["C"], "verb": "LS", "site": "KN4"})
    drain(client)
    assert any(t.startswith("Shift started") for t in wa.texts(FLEET))  # full mode: notices in fleet too
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
    assert "! A LS already reported" in wa.texts(CONTROL)[-1]

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
    assert wa.texts(CONTROL)[-1].startswith('? "A LS somewhere" Amit: site unclear')


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
    assert texts[0].startswith("Shift started") and "KN4" in texts[0]
    assert any(t.startswith("Shift ") and "Loaded 0" in t for t in texts)
    assert any(t.startswith("Commands:") for t in texts)
    assert any(t.startswith("Shift ended") for t in texts)
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
    assert wa.texts(CONTROL)[-1].startswith("Truck tracking connected")
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
    assert sum("Send 'shift end'" in t for t in wa.texts(CONTROL)) == 1
    core.set_setting(conn, "_last_summary_at", "2000-01-01T00:00:00+05:30")
    drain(client)  # interval elapsed but nothing changed → no resend, no second warning
    assert len(summaries()) == 1 and sum("Send 'shift end'" in t for t in wa.texts(CONTROL)) == 1
    wa.boss.post("/api/reports", json={"trucks": ["A"], "verb": "LS", "site": "SOC"})
    core.set_setting(conn, "_last_summary_at", "2000-01-01T00:00:00+05:30")
    drain(client)
    assert len(summaries()) == 2 and "Loading A" in summaries()[-1]


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

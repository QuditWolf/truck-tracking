"""Read-only snapshot of a shift for sharing/debugging: summary, inferences, flags, every event.

    docker compose exec app .venv/bin/python -m app.dump            # current (or latest) shift
    docker compose exec app .venv/bin/python -m app.dump last       # latest ended shift
    docker compose exec app .venv/bin/python -m app.dump 12         # shift id 12

Opens the database read-only; prints phone numbers and emails nowhere.
"""

import sqlite3
import sys

from . import core, reports, summary
from .registry import Registry


def main(arg: str = "") -> None:
    conn = sqlite3.connect(f"file:{core.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    shift_id = None
    if arg == "last":
        row = conn.execute("SELECT id FROM shifts WHERE deleted = 0 AND ended_at IS NOT NULL "
                           "ORDER BY started_at DESC LIMIT 1").fetchone()
        shift_id = row["id"] if row else None
    elif arg.isdigit():
        shift_id = int(arg)
    s = summary.shift_summary(conn, shift_id)
    if not s:
        print("no shifts")
        return
    c = s["counts"]
    sh = conn.execute("SELECT * FROM shifts WHERE id = ?", (s["shift_id"],)).fetchone()
    print(f"== shift {s['shift_id']}  {sh['started_at']} → {sh['ended_at'] or 'running'}")
    print("\n== whatsapp summary\n" + s["text"])
    print(f"\n== counts  loaded {c['loaded']} (inf {c['loaded_inf']}, manual {c['loaded_manual']})  "
          f"unloaded {c['unloaded']} (inf {c['unloaded_inf']}, manual {c['unloaded_manual']})")
    print("== inferred\n" + ("\n".join(c["notes"]) or "-"))
    print("== flags\n" + ("\n".join(s["flags"]) or "-"))
    print("== manual\n" + ("\n".join(f"{m['truck']} +{m['count']} {m['kind']} {m['site'] or ''} {m['note']} ~{m['user']}"
                                     for m in s["manual"]) or "-"))
    print("== trips")
    for truck, ts in s["trips"].items():
        for i, t in enumerate(ts, 1):
            slots = " ".join(f"{k} {v}" for k, v in t["slots"].items())
            print(f"{truck} #{i} {t['load_site'] or '?'}→{t['unload_site'] or '?'} loaded={t['loaded']} "
                  f"unloaded={t['unloaded']} closed={t['closed']} | {slots}")

    reg = Registry(conn)
    end = sh["ended_at"] or "9999"
    rows = conn.execute("SELECT * FROM reports WHERE event_time >= ? AND event_time <= ? ORDER BY event_time, id",
                        (sh["started_at"], end)).fetchall()
    a = reports.analysis(conn, reg)
    print(f"\n== events ({len(rows)}, incl. deleted)")
    for row in rows:
        r = reports.report_dict(conn, reg, row)
        flags = reports.flags_for(a, r["id"], r["trucks"]) if not r["deleted"] else []
        print(f"#{r['id']} {r['event_time'][11:16]} {','.join(r['trucks'])} {r['verb']} {r['site'] or ''}"
              f"{' [deleted]' if r['deleted'] else ''} ~{r['user']} ({r['source']})"
              + (f" - {r['remarks']}" if r["remarks"] else "") + "".join(f"\n      ! {f}" for f in flags))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")

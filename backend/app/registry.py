"""Trucks / sites / verbs. Aliases and merges are the same thing: a row with merged_into set."""

from dataclasses import dataclass
from typing import Optional

from .core import audit, stamp


@dataclass
class Item:
    id: int
    kind: str
    code: str
    label: str
    site_type: Optional[str]
    plate: str
    notes: str
    merged_into: Optional[int]
    active: bool
    sort: int


class Registry:
    """In-memory snapshot. Small (tens of rows), so load it whole per request."""

    def __init__(self, conn):
        rows = conn.execute("SELECT * FROM registry").fetchall()
        self.by_id = {r["id"]: Item(r["id"], r["kind"], r["code"], r["label"], r["site_type"],
                                    r["plate"], r["notes"], r["merged_into"], bool(r["active"]), r["sort"]) for r in rows}

    def canon(self, id_: Optional[int]) -> Optional[Item]:
        item = self.by_id.get(id_)
        seen = set()
        while item and item.merged_into and item.id not in seen:
            seen.add(item.id)
            item = self.by_id.get(item.merged_into)
        return item

    def find(self, kind: str, text: str, active_only: bool = True) -> Optional[Item]:
        """Exact (case-insensitive) match on code or label of any row, resolved to canonical.
        Inactive rows don't match new input but still resolve for history (active_only=False)."""
        t = text.strip().lower()
        for item in self.by_id.values():
            if item.kind == kind and (item.active or not active_only) and t in (item.code.lower(), item.label.lower()):
                return self.canon(item.id)
        return None

    def listing(self, kind: str) -> list[dict]:
        items = [i for i in self.by_id.values() if i.kind == kind and i.active and not i.merged_into]
        items.sort(key=lambda i: (i.sort, i.code))
        return [{"id": i.id, "code": i.code, "label": i.label, "site_type": i.site_type,
                 "plate": i.plate, "notes": i.notes,
                 "aliases": sorted(a.code for a in self.by_id.values() if a.merged_into == i.id and a.active)}
                for i in items]


def create(conn, kind: str, code: str, label: str = "", site_type=None, user_id=None, sort=0,
           plate: str = "", notes: str = "") -> int:
    code = code.strip()
    cur = conn.execute(
        "INSERT INTO registry (kind, code, label, site_type, plate, notes, created_by, created_at, sort) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (kind, code, (label or code).strip(), site_type, plate.strip(), notes.strip(), user_id, stamp(), sort),
    )
    audit(conn, user_id, "create", "registry", cur.lastrowid,
          after={"kind": kind, "code": code, "label": label or code, "site_type": site_type,
                 "plate": plate, "notes": notes})
    return cur.lastrowid


def resolve_or_create(conn, reg: Registry, kind: str, text: str, user_id) -> Item:
    """Web path: unknown values become new registry entries (admin can merge later)."""
    item = reg.find(kind, text)
    if item:
        return item
    if kind == "truck" or kind == "verb":
        text = text.strip().upper()
    new_id = create(conn, kind, text, user_id=user_id)
    reg.by_id[new_id] = Item(new_id, kind, text, text, None, "", "", None, True, 0)
    return reg.by_id[new_id]


def merge(conn, item_id: int, into_id: int, user_id) -> None:
    reg = Registry(conn)
    a, b = reg.by_id.get(item_id), reg.canon(into_id)
    if not a or not b or a.kind != b.kind:
        raise ValueError("both items must exist and be the same kind")
    if a.kind not in ALIASABLE:
        raise ValueError("only trucks and sites can be merged")
    if b.id == a.id:
        raise ValueError("cannot merge an item into itself")
    conn.execute("UPDATE registry SET merged_into = ? WHERE id = ?", (b.id, a.id))
    audit(conn, user_id, "merge", "registry", a.id, before={"merged_into": a.merged_into},
          after={"merged_into": b.id})


def unmerge(conn, item_id: int, user_id) -> None:
    row = conn.execute("SELECT merged_into FROM registry WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError("not found")
    conn.execute("UPDATE registry SET merged_into = NULL WHERE id = ?", (item_id,))
    audit(conn, user_id, "unmerge", "registry", item_id, before={"merged_into": row["merged_into"]},
          after={"merged_into": None})


ALIASABLE = ("truck", "site")


def add_alias(conn, target_id: int, code: str, user_id) -> int:
    """An alias is a registry row born merged into its target."""
    reg = Registry(conn)
    target = reg.canon(target_id)
    if not target or target.kind not in ALIASABLE:
        raise ValueError("aliases only for trucks and sites")
    clash = reg.find(target.kind, code, active_only=False)
    if clash:
        raise ValueError(f"'{code}' already resolves to {clash.code}")
    new_id = create(conn, target.kind, code, code, user_id=user_id)
    conn.execute("UPDATE registry SET merged_into = ? WHERE id = ?", (target.id, new_id))
    return new_id


def edit(conn, item_id: int, user_id, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("code", "label", "site_type", "plate", "notes", "active", "sort") and v is not None}
    row = conn.execute("SELECT * FROM registry WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError("not found")
    if allowed:
        sets = ", ".join(f"{k} = ?" for k in allowed)
        conn.execute(f"UPDATE registry SET {sets} WHERE id = ?", (*allowed.values(), item_id))
        audit(conn, user_id, "update", "registry", item_id, before=dict(row), after=allowed)


def delete(conn, item_id: int, user_id) -> str:
    """Hard delete only if nothing references the row; otherwise deactivate (history keeps resolving)."""
    row = conn.execute("SELECT * FROM registry WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError("not found")
    used = conn.execute(
        "SELECT 1 FROM reports WHERE verb_id = :i OR site_id = :i "
        "UNION SELECT 1 FROM report_trucks WHERE truck_id = :i "
        "UNION SELECT 1 FROM registry WHERE merged_into = :i "
        "UNION SELECT 1 FROM shifts WHERE default_site_id = :i LIMIT 1", {"i": item_id}).fetchone()
    if used:
        conn.execute("UPDATE registry SET active = 0 WHERE id = ?", (item_id,))
        audit(conn, user_id, "deactivate", "registry", item_id, before=dict(row))
        return "deactivated"
    conn.execute("DELETE FROM registry WHERE id = ?", (item_id,))
    audit(conn, user_id, "delete", "registry", item_id, before=dict(row))
    return "deleted"


def admin_listing(reg: Registry) -> list[dict]:
    return [{**i.__dict__, "canonical": reg.canon(i.id).code} for i in
            sorted(reg.by_id.values(), key=lambda i: (i.kind, i.sort, i.code))]


CYCLE_VERBS = [
    ("ENTER", "Enter"), ("LS", "Loading started"), ("LO", "Loading over"), ("LEFT", "Left"),
    ("US", "Unloading started"), ("UO", "Unloading over"),
]


def seed_verbs(conn) -> None:
    for i, (code, label) in enumerate(CYCLE_VERBS):
        if not conn.execute("SELECT 1 FROM registry WHERE kind='verb' AND code=?", (code,)).fetchone():
            create(conn, "verb", code, label, sort=i)

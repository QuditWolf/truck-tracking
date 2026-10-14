"""Seed sites (+ aliases) carried over from the 2026 wheat season, and the starting trucks. Idempotent.

    uv run python -m app.seed

More trucks / licence numbers: Admin → Registry. Verbs are seeded on startup.
Matching is case-insensitive on code and label, so only genuinely different spellings are aliases.
"""

from . import core, registry

SITES = [
    ("DAIRY", "Dairy", "unloading", []),
    ("BG", "Bhandara Ground", "unloading", ["Bhandaagar", "Bhandaagar Ground", "Bandaagar", "Bandaagar Ground"]),
    ("KN4", "Kua No. 4", "loading", ["Kua No 4"]),
    ("SOC", "SOC", "loading", []),
    ("TN", "Tannery", "loading", []),
    ("BDP", "Bahadarpur", "loading", []),
    ("LJ", "Lal Zameen", "loading", ["Lal Jameen"]),
    ("SKP", "Sikandarpur", "loading", ["SDP"]),
    ("DC", "Delhi Camp", "loading", []),
    ("GKT", "Gende Ka Teela", "loading", []),
    ("KF", "Kriplani Fields", "loading", []),
    ("DPS", "Delhi Public School", "loading", []),
    ("PF", "Punjabi Farms", "loading", []),
    ("LG", "Lal Ghadi", "loading", []),
]

TRUCKS = ["A", "B", "C", "D", "E"]


def seed(conn) -> None:
    with core.tx(conn):
        registry.seed_verbs(conn)
        for code, label, site_type, aliases in SITES:
            reg = registry.Registry(conn)
            item = reg.find("site", code, active_only=False)
            site_id = item.id if item else registry.create(conn, "site", code, label, site_type)
            for alias in aliases:
                if not registry.Registry(conn).find("site", alias, active_only=False):
                    registry.add_alias(conn, site_id, alias, None)
        for i, code in enumerate(TRUCKS):
            if not registry.Registry(conn).find("truck", code, active_only=False):
                registry.create(conn, "truck", code, sort=i)


if __name__ == "__main__":
    c = core.connect()
    core.init_db(c)
    seed(c)
    print(f"seeded {len(SITES)} sites and trucks {', '.join(TRUCKS)} into {core.DB_PATH}")

"""Seed sites (+ aliases) carried over from the 2026 wheat season. Idempotent.

    uv run python -m app.seed

Trucks are deliberately not seeded — add them in Admin. Verbs are seeded on startup.
Matching is case-insensitive on code and label, so only genuinely different spellings are aliases.
"""

from . import core, registry

SITES = [
    ("DAIRY", "Dairy", "unloading", []),
    ("BG", "Bhandara Ground", "depot", ["Bhandaagar", "Bhandaagar Ground", "Bandaagar", "Bandaagar Ground"]),
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


if __name__ == "__main__":
    c = core.connect()
    core.init_db(c)
    seed(c)
    print(f"seeded {len(SITES)} sites into {core.DB_PATH}")

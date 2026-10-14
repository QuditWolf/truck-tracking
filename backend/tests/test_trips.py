from datetime import datetime, timedelta, timezone

from app.trips import Event, Shift, analyze, count

IST = timezone(timedelta(hours=5, minutes=30))
SITES = {"SOC": "loading", "KN4": "loading", "SKP": "loading", "DAIRY": "unloading", "BG": "unloading", "DEPOT": "depot", "NEW": None}


def t(hm: str, day: int = 13) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=IST)


def ev(rid, truck, verb, site, hm, user="", day=13):
    return Event(rid, truck, verb, site, SITES.get(site), t(hm, day), user)


SHIFT = Shift(1, t("06:00"), None)


def run(events, shifts=(SHIFT,)):
    a = analyze(events, list(shifts))
    return a, count(a.segment(shifts[0].id), a.flags)


def texts(a, rid, truck):
    return [f.text for f in a.flags.get((rid, truck), [])]


def test_full_cycle_counts_once():
    a, c = run([
        ev(1, "D", "ENTER", "SOC", "08:00"), ev(2, "D", "LS", "SOC", "08:05"),
        ev(3, "D", "LO", "SOC", "08:40"), ev(4, "D", "LEFT", "SOC", "08:45"),
        ev(5, "D", "ENTER", "DAIRY", "09:20"), ev(6, "D", "US", "DAIRY", "09:25"),
        ev(7, "D", "UO", "DAIRY", "09:50"), ev(8, "D", "LEFT", "DAIRY", "09:55"),
    ])
    assert (c.loaded, c.loaded_inf, c.reached, c.unloaded, c.unloaded_inf) == (1, 0, 1, 1, 0)
    assert c.loaded_by_site == {"SOC": 1} and c.unloaded_by_site == {"DAIRY": 1}
    assert c.position == {"empty": ["D"]}
    assert a.flags == {}


def test_duplicate_from_second_reporter_ignored():
    a, c = run([ev(1, "D", "LS", "SOC", "08:10", "Ravi"), ev(2, "D", "LS", "SOC", "08:12", "Amit")])
    assert texts(a, 2, "D") == ["D LS SOC already reported @08:10 ~Ravi"]
    assert c.position == {"loading": ["D"]} and c.loaded == 0


def test_same_verb_far_apart_is_new_trip():
    a, c = run([ev(1, "D", "LS", "SOC", "08:00"), ev(2, "D", "LS", "KN4", "10:40")])
    # first trip closed by second → load inferred, and it must have unloaded somewhere
    assert (c.loaded, c.loaded_inf, c.unloaded, c.unloaded_inf) == (1, 1, 1, 1)
    assert c.loaded_by_site == {"SOC": 1} and c.unloaded_by_site == {"?": 1}
    assert "D LO not reported after LS SOC @08:00" in texts(a, 2, "D")
    assert c.notes == ["D load SOC inferred: LS @08:00, no LO", "D unload ? inferred: loaded again later"]
    assert c.position == {"loading": ["D"]}


def test_example_from_design():
    a, c = run([
        ev(1, "D", "LS", "SOC", "08:10", "Ravi"), ev(2, "D", "LS", "SOC", "08:12", "Amit"),
        ev(3, "D", "US", "DAIRY", "09:30"), ev(4, "D", "LS", "KN4", "10:40"),
    ])
    assert (c.loaded, c.loaded_inf, c.unloaded, c.unloaded_inf) == (1, 1, 1, 1)
    assert c.loaded_by_site == {"SOC": 1} and c.unloaded_by_site == {"DAIRY": 1}
    assert texts(a, 3, "D") == ["D LO not reported between LS SOC @08:10 and US DAIRY @09:30"]
    assert c.position == {"loading": ["D"]}


def test_report_order_does_not_matter():
    evs = [ev(1, "D", "LS", "SOC", "08:00"), ev(2, "D", "LO", "SOC", "08:30"), ev(3, "D", "UO", "DAIRY", "09:30")]
    _, c1 = run(evs)
    _, c2 = run(list(reversed(evs)))
    assert c1 == c2


def test_open_ls_counts_at_shift_end():
    sh = Shift(1, t("06:00"), t("18:00"))
    _, c = run([ev(1, "D", "LS", "SOC", "17:00")], (sh,))
    assert (c.loaded, c.loaded_inf) == (1, 1) and c.position == {}
    assert c.notes == ["D load SOC inferred: LS @17:00, no LO by shift end"]


def test_open_ls_not_counted_while_shift_running():
    _, c = run([ev(1, "D", "LS", "SOC", "17:00")])
    assert c.loaded == 0 and c.position == {"loading": ["D"]}


def test_carry_over_between_shifts_counts_load_once():
    s1 = Shift(1, t("06:00"), t("18:00"))
    s2 = Shift(2, t("18:00"), None)
    a = analyze([ev(1, "D", "LO", "SOC", "17:30"), ev(2, "D", "UO", "DAIRY", "18:40")], [s1, s2])
    c1, c2 = count(a.segment(1), a.flags), count(a.segment(2), a.flags)
    assert (c1.loaded, c1.unloaded) == (1, 0)
    assert (c2.loaded, c2.unloaded) == (0, 1)
    assert (2, "D") not in a.flags  # carried trip doesn't complain about LS/LO missing
    assert c2.notes == ["D load carried from previous shift"]


def test_unload_without_any_load_report_does_not_infer_load():
    _, c = run([ev(1, "D", "UO", "DAIRY", "09:00")])
    assert (c.loaded, c.loaded_inf, c.unloaded) == (0, 0, 1)
    assert c.loaded_by_site == {}


def test_enter_left_without_loading_is_flagged_not_counted():
    a, c = run([ev(1, "D", "ENTER", "SOC", "08:00"), ev(2, "D", "LEFT", "SOC", "08:20")])
    assert c.loaded == 0
    assert texts(a, 2, "D") == ["D LEFT SOC @08:20 without LS/LO"]


def test_unknown_site_type_inferred_from_position():
    _, c = run([ev(1, "D", "LO", "SOC", "08:00"), ev(2, "D", "ENTER", "NEW", "09:00")])
    assert c.reached == 1


def test_depot_and_custom_verbs_ignored():
    a, c = run([ev(1, "D", "ENTER", "DEPOT", "07:00"), ev(2, "D", "BREAKDOWN", "SOC", "07:30"),
                ev(3, "D", "LS", "SOC", "08:00")])
    assert a.flags == {} and c.position == {"loading": ["D"]}


def test_unshifted_event_flagged():
    a, _ = run([ev(1, "D", "LS", "SOC", "05:00")])
    assert texts(a, 1, "D") == ["outside any shift"]


def test_multi_truck_report_flags_per_truck():
    a, c = run([ev(1, "A", "LS", "SOC", "08:00"), ev(1, "B", "LS", "SOC", "08:00"),
                ev(2, "A", "LS", "SOC", "08:05")])
    assert texts(a, 2, "A") and not a.flags.get((1, "B"))
    assert c.position == {"loading": ["A", "B"]}


def test_enter_is_at_site_not_loading():
    _, c = run([ev(1, "D", "ENTER", "SOC", "08:00"), ev(2, "E", "LS", "SOC", "08:05"),
                ev(3, "F", "ENTER", "DAIRY", "08:10")])
    assert c.position == {"at_loading": ["D"], "loading": ["E"], "at_unloading": ["F"]}


def test_summary_lists_loading_now_and_loads_per_truck():
    from app.summary import counts_text
    evs = [ev(1, "A", "LO", "SOC", "06:30"), ev(2, "A", "UO", "DAIRY", "07:30"),
           ev(3, "A", "LO", "SOC", "08:30"),
           ev(4, "B", "LO", "SOC", "06:40"), ev(5, "B", "UO", "DAIRY", "07:40"), ev(6, "B", "LS", "SOC", "08:40")]
    _, c = run(evs)
    text = counts_text("T", c, notes=False)
    assert "Loading: B" in text and "Loaded: A*2 B*1" in text and "En route" not in text
    assert "Unloaded: A*1 B*1" in text


def test_entered_truck_is_at_loading_site_not_loading():
    from app.summary import counts_text
    _, c = run([ev(1, "B", "LO", "SOC", "07:00"), ev(2, "B", "UO", "DAIRY", "08:00"), ev(3, "B", "ENTER", "SOC", "09:00")])
    text = counts_text("T", c, notes=False)
    assert "At loading site: B" in text and "Loading:" not in text and "Loaded: B*1" in text


def test_summary_has_no_reached_line():
    from app.summary import counts_text
    _, c = run([ev(1, "D", "LO", "SOC", "07:00"), ev(2, "D", "US", "DAIRY", "08:00")])
    assert "Reached" not in counts_text("T", c)


def test_unload_counted_without_reported_load():
    # entered and left the unloading site, nothing else reported
    _, c = run([ev(1, "D", "ENTER", "BG", "07:00"), ev(2, "D", "LEFT", "BG", "07:40")])
    assert (c.unloaded, c.unloaded_by_site, c.loaded, c.loaded_inf) == (1, {"BG": 1}, 0, 0)
    # US + UO only
    _, c = run([ev(1, "E", "US", "DAIRY", "07:00"), ev(2, "E", "UO", "DAIRY", "07:30")])
    assert (c.unloaded, c.unloaded_inf, c.unloaded_by_site) == (1, 0, {"DAIRY": 1})
    # entered unloading site and started a new trip later → unload inferred
    _, c = run([ev(1, "F", "ENTER", "BG", "07:00"), ev(2, "F", "ENTER", "SOC", "09:00")])
    assert c.unloaded == 1 and c.unloaded_by_site == {"BG": 1}


def test_real_shift_14_oct_bg_enter_left():
    """From the live 14 Oct shift: BG visits are reported as ENTER + LEFT only."""
    evs = [ev(13, "D", "ENTER", "BG", "15:38", "Mileeth"), ev(14, "D", "ENTER", "BG", "15:38", "Dheer"),
           ev(16, "D", "LEFT", "BG", "15:51"), ev(15, "U", "ENTER", "BG", "15:48"), ev(17, "U", "LEFT", "BG", "15:57"),
           ev(22, "U", "LS", "SKP", "16:14"), ev(30, "U", "ENTER", "BG", "17:07"), ev(32, "U", "LEFT", "BG", "17:08"),
           ev(31, "A", "LS", "BG", "17:08"), ev(38, "A", "LO", "SKP", "17:30")]
    sh = Shift(2, t("15:38", 14), None)
    a = analyze([Event(e.report_id, e.truck, e.verb, e.site, e.site_type, e.time.replace(day=14), e.user) for e in evs], [sh])
    c = count(a.segment(2), a.flags)
    assert (c.unloaded, c.unloaded_inf) == (3, 0)  # D once, U twice — reported, not inferred
    every = [f.text for fs in a.flags.values() for f in fs]
    assert not any("US" in f or "UO" in f for f in every)  # no more US/UO noise
    assert "D ENTER BG already reported @15:38 ~Mileeth" in every
    assert "A LS at BG, an unloading site" in every
    assert c.loaded_by_site == {"SKP": 2}  # U LS→BG (inferred), A LO at SKP

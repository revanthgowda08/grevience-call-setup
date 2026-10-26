"""Load 200 demo tickets: ~40 closed before the pilot (shadow baseline), the rest marked resolved
with a few repeat-complaint clusters. Usage: python -m demo.seed [db_path]"""
import math
import os
import random
import sys

from app.engine import Engine
from app.hotspot import CELL_DEG

ISSUES = {
    "Drainage": ["Drain overflowing near the road", "Sewage blocked drain smells", "Open drain not cleaned"],
    "Streetlight": ["Streetlight not working at night", "Street light pole dark since weeks", "Lamp broken on main road"],
    "Garbage": ["Garbage not collected for days", "Waste pile on the corner", "Dustbin overflowing garbage"],
    "Water supply": ["No water supply in morning", "Water pipe leakage on street", "Low pressure water supply"],
    "Road": ["Pothole on the road", "Road damaged after digging", "Broken road surface potholes"],
}
WARDS = {"Jayanagar": (12.925, 77.583), "Malleshwaram": (13.003, 77.564), "Koramangala": (12.935, 77.624),
         "Indiranagar": (12.978, 77.640), "Yelahanka": (13.100, 77.596), "Whitefield": (12.970, 77.750)}
OFFICERS = [("Ravi Kumar", "S. Murthy"), ("Anita Rao", "S. Murthy"), ("Imran Pasha", "K. Gowda"), ("Meena Devi", "K. Gowda")]
HOTSPOTS = [("Jayanagar", "Drainage", 9), ("Malleshwaram", "Streetlight", 7), ("Koramangala", "Garbage", 6)]


def build(n=200, seed=7):
    rng = random.Random(seed)
    rows = []

    def add(ward, category, status, spread=0.0008):
        i = len(rows) + 1
        lat, lon = (round((math.floor(v / CELL_DEG) + 0.5) * CELL_DEG, 6) for v in WARDS[ward])  # centre of a map cell
        officer, supervisor = rng.choice(OFFICERS)
        rows.append({
            "id": f"PS-{i:04d}", "citizen_name": f"Citizen {i}", "phone": f"9{rng.randint(100000000, 999999999)}",
            "language": rng.choices(["kn", "hi", "en"], [0.6, 0.2, 0.2])[0], "department": "BBMP",
            "category": category, "description": rng.choice(ISSUES[category]), "ward": ward,
            "lat": round(lat + rng.uniform(-spread, spread), 6), "lon": round(lon + rng.uniform(-spread, spread), 6),
            "officer": officer, "supervisor": supervisor, "head": "Zonal Commissioner", "status": status, "shadow": False})

    for ward, category, count in HOTSPOTS:
        for _ in range(count):
            add(ward, category, "resolved")
    while len(rows) < n:
        add(rng.choice(list(WARDS)), rng.choice(list(ISSUES)), "resolved", spread=0.03)  # scattered, no cluster
    for r in rng.sample(rows, 40):  # closed last month: asked in shadow mode, never reopened
        r["shadow"] = True
    return rows


def main(db_path=None):
    db_path = db_path or (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SATYA_DB", "satya.db"))
    if os.path.exists(db_path):
        os.remove(db_path)
    engine = Engine(db_path)
    engine.ingest(build())
    # Shadow baseline first, then live verification with retries.
    for _ in range(6):
        engine.run_verifications(shadow=True)
        engine.run_verifications()
        engine.advance_clock(8)
    engine.clock_offset = type(engine.clock_offset)()  # reset the clock; leftover pending tickets stay for the live demo
    m = engine.metrics()
    print(f"Seeded {db_path}: {m['rounds_finished']} verified, confirmed {m['confirmed_rate']}, false-closure {m['false_closure_rate']}, "
          f"baseline false-closure {m['baseline']['false_closure_rate']}, hotspots {len(m['hotspots'])}")


if __name__ == "__main__":
    main()

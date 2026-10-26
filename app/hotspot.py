"""Hotspot Radar: places with repeated similar complaints.

Tickets are bucketed by place (ward, or a ~300 m map cell when coordinates exist),
then clustered by text similarity so different wordings of one issue group together.
"""
import math

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CELL_DEG = 0.0027  # ~300 m of latitude
MIN_TICKETS = 3
SIMILARITY = 0.3
DONE = {"verified_closed", "shadow_pending", "shadow_done"}


def place_key(t):
    if t.get("lat") is not None and t.get("lon") is not None:
        return f'cell {math.floor(t["lat"] / CELL_DEG)}:{math.floor(t["lon"] / CELL_DEG)}' + (f' ({t["ward"]})' if t.get("ward") else "")
    return t.get("ward") or "unknown"


def _components(sim, threshold):
    n = len(sim)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i][j] >= threshold:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def find_hotspots(tickets, min_tickets=MIN_TICKETS, threshold=SIMILARITY):
    """tickets: dicts with id, category, description, ward, lat, lon, status.
    Returns clusters sorted by unresolved count, largest first."""
    by_place = {}
    for t in tickets:
        by_place.setdefault(place_key(t), []).append(t)
    out = []
    for place, items in by_place.items():
        if len(items) < min_tickets:
            continue
        texts = [f'{t["category"]} {t["category"]} {t["description"]}' for t in items]  # category counts double
        try:
            sim = cosine_similarity(TfidfVectorizer(stop_words="english").fit_transform(texts))
        except ValueError:  # empty vocabulary
            continue
        for idx in _components(sim, threshold):
            if len(idx) < min_tickets:
                continue
            members = [items[i] for i in idx]
            cats = [m["category"] for m in members]
            issue = max(set(cats), key=cats.count)
            out.append({
                "place": place,
                "issue": issue,
                "tickets": len(members),
                "unresolved": sum(1 for m in members if m["status"] not in DONE),
                "ticket_ids": [m["id"] for m in members],
            })
    out.sort(key=lambda c: (-c["unresolved"], -c["tickets"]))
    return out

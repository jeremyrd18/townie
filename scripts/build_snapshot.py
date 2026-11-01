"""Save nearby places for the demo spots to data/osm_snapshot.json, so the live demo
never waits on a busy OpenStreetMap server. Run: python scripts/build_snapshot.py
Add your venue with: python scripts/build_snapshot.py 43.6596 -79.3977"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import places  # noqa: E402
from app.main import DEMO_SPOTS  # noqa: E402

CATEGORIES = ["coffee", "food", "washroom", "subway", "bar", "atm", "pharmacy", "attraction"]


async def main():
    spots = [(s["lat"], s["lon"]) for s in DEMO_SPOTS]
    if len(sys.argv) == 3:
        spots = [(float(sys.argv[1]), float(sys.argv[2]))]
    for lat, lon in dict.fromkeys(spots):
        for cat in CATEGORIES:
            for radius in (500, 1200):
                found = await places.nearby(lat, lon, cat, radius=radius)
                print(f"{lat},{lon} {cat:<10} r{radius}: {len(found)} e.g. {found[0]['name'] if found else '-'}")
        print("saved", places.save_snapshot(), "entries")


asyncio.run(main())

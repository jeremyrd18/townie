"""Render Workflow service for Townie's Prep mode.

Deploy this repo a second time on Render as a Workflow service:
  Build command: pip install -r requirements.txt
  Start command: python workflow.py
The web service starts `prep_day`, which fans out to subtasks you can watch in the Render dashboard.
"""
import asyncio

from render import TaskContext, Workflows

from app import prep

wf = Workflows()


@wf.task
async def locate_area(ctx: TaskContext, area: str) -> dict:
    return await prep.locate_area(area)


@wf.task
async def scout_spots(ctx: TaskContext, lat: float, lon: float, category: str) -> list:
    return await prep.scout_spots(lat, lon, category)


@wf.task
async def write_plan(ctx: TaskContext, area: dict, interests: str, coffee: list, food: list, sights: list) -> dict:
    landmarks = prep.nearby_landmarks(area["lat"], area["lon"])
    return await prep.write_plan(area, interests, coffee, food, sights, landmarks)


@wf.task(timeout_seconds=180)
async def prep_day(ctx: TaskContext, area: str, interests: str = "") -> dict:
    """Find the start point, scout coffee/food/sights in parallel, then write the day plan."""
    spot = await ctx.run(locate_area, area)
    coffee, food, sights = await asyncio.gather(
        ctx.run(scout_spots, spot["lat"], spot["lon"], "coffee"),
        ctx.run(scout_spots, spot["lat"], spot["lon"], "food"),
        ctx.run(scout_spots, spot["lat"], spot["lon"], "attraction"),
    )
    return await ctx.run(write_plan, spot, interests, coffee, food, sights)


if __name__ == "__main__":
    wf.start()

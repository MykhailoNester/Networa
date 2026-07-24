from fastapi import APIRouter

from ..services import snapshot_service

router = APIRouter()


@router.post("/api/v1/snapshots/take")
async def take_snapshot(snapshot_date: str | None = None):
    return await snapshot_service.take_snapshot(snapshot_date)


@router.get("/api/v1/net-worth/history")
async def net_worth_history(from_date: str | None = None, to_date: str | None = None):
    return await snapshot_service.get_net_worth_history(from_date, to_date)


@router.get("/api/v1/net-worth/current")
async def current_net_worth():
    return await snapshot_service.get_current_net_worth()

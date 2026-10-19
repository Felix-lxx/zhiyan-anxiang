"""Database-leased exercise scheduler. Does not depend on an open browser."""
import asyncio
import logging


async def serve():
    from app.api.routes import operations
    from app.core.database import SessionLocal

    def tick():
        from sqlalchemy import select
        from app.models.operations import DrillSession
        from app.services.engine_lease import acquire_engine_lease
        # Discovery is read-only. Each lease and simulation step owns a short,
        # independent transaction so one drill cannot hold SQLite's writer lock
        # while the scheduler iterates over every other running drill.
        with SessionLocal() as discovery:
            drill_ids = list(discovery.scalars(select(DrillSession.id).where(DrillSession.status == "running")))
        for drill_id in drill_ids:
            try:
                with SessionLocal() as lease_session:
                    acquired = acquire_engine_lease(lease_session, drill_id)
                    if acquired:
                        lease_session.commit()
                    else:
                        lease_session.rollback()
                if not acquired:
                    continue
                with SessionLocal() as work_session:
                    drill = work_session.get(DrillSession, drill_id)
                    if drill is None or drill.status != "running":
                        continue
                    operations.advance_engine(work_session, drill)
            except Exception:
                # Session context managers roll back this drill. A malformed world
                # must not starve every subsequent running drill on every tick.
                logging.getLogger(__name__).exception("场次 %s 推进失败，继续处理其他场次", drill_id)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logging.getLogger(__name__).exception("演练调度失败，将在下一轮重试")
        await asyncio.sleep(1)

"""Single-process local exercise scheduler. Does not depend on an open browser."""
import asyncio
import logging


async def serve():
    from app.api.routes import operations

    def tick():
        from sqlalchemy import select
        from app.models.operations import DrillSession
        with operations.SessionLocal() as session:
            for drill in session.scalars(select(DrillSession).where(DrillSession.status == "running")):
                operations.advance_engine(session, drill)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            logging.getLogger(__name__).exception("演练调度失败，将在下一轮重试")
        await asyncio.sleep(1)

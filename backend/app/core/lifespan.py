"""Application lifecycle composition.

后台演练推进与智能体监督都属于进程级任务；把它们从 ``main`` 移出，使
API 装配、运行期任务和业务服务保持清楚的单向依赖。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.core.database import initialize_schema


def create_lifespan(settings: Settings):
    """Create a lifespan handler bound to the immutable application settings."""

    @asynccontextmanager
    async def lifespan(_: object) -> AsyncIterator[None]:
        initialized = initialize_schema()
        if not initialized and settings.app_env != "development":
            raise RuntimeError("数据库初始化失败，停止启动以避免不完整部署。")

        is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if is_test:
            yield
            return

        from app.services.agent_workflow import serve as serve_agent
        from app.services.engine_scheduler import serve as serve_engine

        workers = [
            asyncio.create_task(serve_engine(), name="drill-engine-scheduler"),
            asyncio.create_task(serve_agent(), name="agent-workflow-supervisor"),
        ]
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            for worker in workers:
                with suppress(asyncio.CancelledError):
                    await worker

    return lifespan

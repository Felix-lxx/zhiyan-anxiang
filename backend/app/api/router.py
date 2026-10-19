"""HTTP API composition root.

业务路由在各自模块内定义；本文件只负责装配，避免应用启动文件同时承担
业务依赖、路由注册与运行时配置三种职责。
"""
from fastapi import APIRouter

from app.api.routes import (
    account,
    agent,
    assistant,
    auth,
    communities,
    decisions,
    demo,
    health,
    map_objects,
    operations,
    road_network,
    roles,
    scenes,
    tasks,
)


api_router = APIRouter()

for route_module in (
    health,
    auth,
    account,
    demo,
    communities,
    map_objects,
    road_network,
    scenes,
    decisions,
    tasks,
    operations,
    roles,
    assistant,
    agent,
):
    api_router.include_router(route_module.router)

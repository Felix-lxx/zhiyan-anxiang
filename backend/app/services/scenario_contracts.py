"""Versioned capabilities of implemented scenarios, independent of UI and ORM.

Template names or stored defaults never grant an engine capability. New cases
must register an executable contract before authoring and runtime are enabled.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ScenarioContract:
    code: str
    contract_version: int
    title: str
    status: str
    notice: str
    source_types: tuple[str, ...]
    location_kinds: tuple[str, ...]
    features: tuple[str, ...]
    parameter_schema: str | None
    environment_model: str | None

    @property
    def available(self):
        return self.status == "available"

    def payload(self):
        return {**asdict(self), "can_create": self.available,
                "can_configure": self.available, "can_preview": self.available,
                "can_publish": self.available, "can_run": self.available}


CONTRACTS = {
    "night_charging_shed_fire": ScenarioContract(
        code="night_charging_shed_fire", contract_version=1,
        title="夜间充电棚火灾", status="available",
        notice="可配置充电棚起火点、居民和通道，预览后发布并进入演练。",
        source_types=("charging_shed",), location_kinds=("object",),
        features=("室外火情推演", "楼内外连续疏散", "机器人协同", "集合清点与复盘"),
        parameter_schema="charging_shed.v1", environment_model="outdoor_rules.v1"),
    "kitchen_fire": ScenarioContract(
        code="kitchen_fire", contract_version=1,
        title="住宅厨房火灾", status="available",
        notice="选择住宅楼、楼层与厨房，观察房间—走廊—楼梯烟气并组织疏散。",
        source_types=("kitchen",), location_kinds=("room",),
        features=('房间起火选点', '分区烟气与门控', '连续室内疏散', '燃气切断与清点复盘'), parameter_schema='kitchen.v1', environment_model='indoor_zones.v1'),
}


def contract_for(code):
    return CONTRACTS.get(code) or ScenarioContract(
        code=code or "unknown", contract_version=1, title="未注册案例",
        status="unsupported", notice="该模板尚无可运行规则，请选择已支持的案例。",
        source_types=(), location_kinds=(), features=(),
        parameter_schema=None, environment_model=None)


def scene_contract(scene):
    template = scene.template
    return contract_for(template.code if template else None)


class ScenarioUnavailable(ValueError):
    pass


def require_available(contract):
    if not contract.available:
        raise ScenarioUnavailable(contract.notice)


def canonical_defaults(defaults):
    """Translate legacy template keys only when creating a new draft."""
    values = dict(defaults)
    values["start_time"] = values.get("start_time", values.get("time", "20:15"))
    values["wind_direction"] = values.get("wind_direction", values.get("wind", "微风"))
    values.pop("time", None)
    values.pop("wind", None)
    return values

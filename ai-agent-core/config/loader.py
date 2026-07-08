from pathlib import Path
import yaml
from .models import RulesConfig, RoutingConfig


def _read_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_rules(path: str) -> RulesConfig:
    return RulesConfig.model_validate(_read_yaml(path))


def load_routing(path: str) -> RoutingConfig:
    return RoutingConfig.model_validate(_read_yaml(path))

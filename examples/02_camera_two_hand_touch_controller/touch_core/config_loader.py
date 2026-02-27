from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_controller_layout(cfg: Dict[str, Any], config_dir: Path) -> Dict[str, Any]:
    touch_cfg = cfg.get("controller_touch")
    if not isinstance(touch_cfg, dict):
        return cfg

    layout_file = touch_cfg.get("layout_file")
    if not layout_file:
        return cfg

    layout_path = (config_dir / str(layout_file)).resolve()
    if not layout_path.exists():
        print(f"[WARN] controller_touch.layout_file not found: {layout_path}")
        return cfg

    with layout_path.open("r", encoding="utf-8") as f:
        layout = yaml.safe_load(f) or {}

    template = layout.get("template", {})
    transform = layout.get("transform", {})
    sticks = layout.get("sticks", {})
    buttons = layout.get("buttons", {})

    if isinstance(template, dict):
        size = template.get("size")
        if isinstance(size, list) and len(size) == 2:
            touch_cfg["template_size"] = [float(size[0]), float(size[1])]
        image = template.get("image")
        if image:
            touch_cfg["ui_image"] = str(image)

    if isinstance(transform, dict):
        for key in ["width_torso_scale", "global_scale", "min_width", "anchor_y_ratio", "offset_x"]:
            if key in transform:
                touch_cfg[key] = float(transform[key])

    if isinstance(sticks, dict):
        if "motion_radius_px" in sticks:
            touch_cfg["stick_motion_radius_px"] = float(sticks["motion_radius_px"])
        if "deadzone" in sticks:
            touch_cfg["stick_deadzone"] = float(sticks["deadzone"])

        out_sticks: Dict[str, list[float]] = {}
        for side in ["left", "right"]:
            spec = sticks.get(side)
            if not isinstance(spec, dict):
                continue
            center = spec.get("center")
            touch_radius = spec.get("touch_radius")
            if isinstance(center, list) and len(center) == 2 and touch_radius is not None:
                out_sticks[side] = [float(center[0]), float(center[1]), float(touch_radius)]
        if out_sticks:
            touch_cfg["sticks"] = out_sticks

    if isinstance(buttons, dict):
        out_buttons: Dict[str, list[float]] = {}
        for name, spec in buttons.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("shape", "circle") != "circle":
                continue
            center = spec.get("center")
            radius = spec.get("radius")
            if isinstance(center, list) and len(center) == 2 and radius is not None:
                out_buttons[str(name)] = [float(center[0]), float(center[1]), float(radius)]
        if out_buttons:
            touch_cfg["buttons"] = out_buttons

    cfg["controller_touch"] = touch_cfg
    return cfg


def load_config(config_dir: Path) -> Dict[str, Any]:
    default_path = config_dir / "default.yaml"
    runtime_path = config_dir / "runtime.yaml"

    with default_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if runtime_path.exists():
        with runtime_path.open("r", encoding="utf-8") as f:
            runtime_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, runtime_cfg)

    cfg = _apply_controller_layout(cfg, config_dir)
    return cfg


def write_runtime_overrides(config_dir: Path, overrides: Dict[str, Any]) -> None:
    runtime_path = config_dir / "runtime.yaml"
    with runtime_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(overrides, f, sort_keys=False)

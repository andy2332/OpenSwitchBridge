from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from .features import PoseFeatures
from .models import ActionActivation


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _vec_deadzone(v: Tuple[float, float], dz: float) -> Tuple[float, float]:
    x, y = v
    if (x * x + y * y) ** 0.5 < dz:
        return (0.0, 0.0)
    return (x, y)


class ControllerTouchMapper:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _button_hit(self, point: np.ndarray, center: Tuple[float, float], radius: float) -> bool:
        dx = float(point[0]) - float(center[0])
        dy = float(point[1]) - float(center[1])
        return (dx * dx + dy * dy) <= radius * radius

    def _stick_from_template(
        self,
        point: np.ndarray,
        center: Tuple[float, float],
        touch_radius_px: float,
        motion_radius_px: float,
        deadzone: float,
    ) -> Tuple[float, float]:
        dx_px = float(point[0]) - float(center[0])
        dy_px = float(point[1]) - float(center[1])
        dist = (dx_px * dx_px + dy_px * dy_px) ** 0.5
        if dist > touch_radius_px:
            return (0.0, 0.0)

        sx = _clamp(dx_px / max(motion_radius_px, 1e-5))
        sy = _clamp(-dy_px / max(motion_radius_px, 1e-5))
        return _vec_deadzone((sx, sy), deadzone)

    def _to_template_point(
        self,
        p: np.ndarray,
        rect_center: np.ndarray,
        rect_size: np.ndarray,
        template_size: np.ndarray,
    ) -> np.ndarray:
        u = (float(p[0]) - (float(rect_center[0]) - float(rect_size[0]) * 0.5)) / max(float(rect_size[0]), 1e-5)
        v = (float(p[1]) - (float(rect_center[1]) - float(rect_size[1]) * 0.5)) / max(float(rect_size[1]), 1e-5)
        return np.array([u * float(template_size[0]), v * float(template_size[1])], dtype=float)

    def evaluate(self, features: PoseFeatures) -> tuple[list[ActionActivation], Dict[str, Any]]:
        touch_cfg = self.cfg.get("controller_touch", {})
        template_size = np.array(touch_cfg.get("template_size", [768.0, 674.0]), dtype=float)
        torso_len = max(features.torso_len, 1e-5)

        width = max(
            float(touch_cfg.get("min_width", 0.42)),
            torso_len * float(touch_cfg.get("width_torso_scale", 3.3)),
        )
        width *= float(touch_cfg.get("global_scale", 1.0))
        height = width * float(template_size[1]) / max(float(template_size[0]), 1e-5)
        rect_size = np.array([width, height], dtype=float)
        rect_center = np.array(
            [
                float(features.shoulder_center[0]) + float(touch_cfg.get("offset_x", 0.0)) * torso_len,
                float(features.shoulder_center[1]) + float(touch_cfg.get("anchor_y_ratio", 0.95)) * torso_len,
            ],
            dtype=float,
        )

        lw_tpl = self._to_template_point(features.left_wrist, rect_center, rect_size, template_size)
        rw_tpl = self._to_template_point(features.right_wrist, rect_center, rect_size, template_size)

        left_stick_cfg = touch_cfg.get("sticks", {}).get("left", [194, 274, 58])
        right_stick_cfg = touch_cfg.get("sticks", {}).get("right", [458, 399, 58])
        left_center = (float(left_stick_cfg[0]), float(left_stick_cfg[1]))
        right_center = (float(right_stick_cfg[0]), float(right_stick_cfg[1]))
        left_touch_r = float(left_stick_cfg[2])
        right_touch_r = float(right_stick_cfg[2])
        motion_radius = float(touch_cfg.get("stick_motion_radius_px", 44.0))
        stick_deadzone = float(touch_cfg.get("stick_deadzone", 0.18))

        left_vec = self._stick_from_template(lw_tpl, left_center, left_touch_r, motion_radius, stick_deadzone)
        right_vec = self._stick_from_template(rw_tpl, right_center, right_touch_r, motion_radius, stick_deadzone)

        pressed: Dict[str, bool] = {}
        buttons_cfg: Dict[str, Tuple[float, float, float]] = touch_cfg.get("buttons", {})
        for key, spec in buttons_cfg.items():
            if len(spec) != 3:
                continue
            center = (float(spec[0]), float(spec[1]))
            radius = float(spec[2])
            pressed[key] = self._button_hit(lw_tpl, center, radius) or self._button_hit(rw_tpl, center, radius)

        button_payload = {k: v for k, v in pressed.items() if v}
        stick_conf = max(
            (left_vec[0] * left_vec[0] + left_vec[1] * left_vec[1]) ** 0.5,
            (right_vec[0] * right_vec[0] + right_vec[1] * right_vec[1]) ** 0.5,
        )
        btn_conf = min(1.0, float(len(button_payload)) / 4.0) if button_payload else 0.0

        debug = {
            "enabled": True,
            "rect_center": [float(rect_center[0]), float(rect_center[1])],
            "rect_size": [float(rect_size[0]), float(rect_size[1])],
            "template_size": [float(template_size[0]), float(template_size[1])],
            "left_wrist_tpl": [float(lw_tpl[0]), float(lw_tpl[1])],
            "right_wrist_tpl": [float(rw_tpl[0]), float(rw_tpl[1])],
            "sticks": {
                "left": [float(left_center[0]), float(left_center[1]), float(left_touch_r)],
                "right": [float(right_center[0]), float(right_center[1]), float(right_touch_r)],
            },
            "buttons": {k: [float(v[0]), float(v[1]), float(v[2])] for k, v in buttons_cfg.items() if len(v) == 3},
            "pressed": list(button_payload.keys()),
        }

        actions = [
            ActionActivation(
                name="spatial_touch_sticks",
                confidence=stick_conf,
                priority=100,
                left_stick=left_vec,
                right_stick=right_vec,
            ),
            ActionActivation(
                name="spatial_touch_buttons",
                confidence=btn_conf,
                priority=100,
                buttons=button_payload,
            ),
        ]
        return actions, debug

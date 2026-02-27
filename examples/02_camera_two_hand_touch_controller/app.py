from __future__ import annotations

import time
from pathlib import Path

import cv2

from touch_core.arbiter import Arbiter
from touch_core.config_loader import load_config
from touch_core.controller_touch_mapper import ControllerTouchMapper
from touch_core.features import extract_features
from touch_core.filters import LandmarkEMAFilter
from touch_core.overlay import draw_overlay, export_controller_base_image, export_controller_debug_image
from touch_core.pose_backend import PoseBackend


def _open_camera(cfg: dict):
    cam = cv2.VideoCapture(int(cfg["camera"]["index"]))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg["camera"].get("width", 1280)))
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg["camera"].get("height", 720)))
    return cam


def _load_touch_ui_image(cfg: dict, project_root: Path):
    touch_cfg = cfg.get("controller_touch", {})
    image_path = touch_cfg.get("ui_image", "")
    if not image_path:
        return None
    resolved = (project_root / image_path).resolve()
    image = cv2.imread(str(resolved), cv2.IMREAD_COLOR)
    if image is None:
        print(f"[WARN] failed to load controller_touch.ui_image: {resolved}")
        return None
    print(f"[INFO] controller touch UI image loaded: {resolved}")
    return image


def run() -> None:
    project_root = Path(__file__).resolve().parent
    config_dir = project_root / "configs"

    cfg = load_config(config_dir)
    cap = _open_camera(cfg)
    if not cap.isOpened():
        raise RuntimeError("Failed to open camera")

    pose_backend = PoseBackend(cfg["pose"])
    landmark_filter = LandmarkEMAFilter(alpha_xy=float(cfg["ema"].get("alpha_xy", 0.35)))
    mapper = ControllerTouchMapper(cfg)
    arbiter = Arbiter()
    touch_ui_image = _load_touch_ui_image(cfg, project_root)

    size_step = 0.05
    size_min = 0.5
    size_max = 2.0
    debug_overlay = None

    while True:
        ok, frame = cap.read()
        if not ok:
            continue

        frame = cv2.flip(frame, 1)
        result = pose_backend.infer(frame)
        landmarks = pose_backend.to_landmark_dict(result)

        features = None
        controller_state = arbiter.state
        debug_overlay = None

        if landmarks:
            landmarks = landmark_filter.update(landmarks)
            features = extract_features(landmarks)

        if features is not None:
            actions, debug_overlay = mapper.evaluate(features)
            controller_state = arbiter.arbitrate(actions)

        if cfg["ui"].get("show_skeleton", True):
            pose_backend.draw_skeleton(frame, result)

        draw_overlay(frame, features, controller_state, cfg, debug_overlay, touch_ui_image)
        cv2.imshow("Controller Touch Standalone", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            cfg = load_config(config_dir)
            mapper = ControllerTouchMapper(cfg)
            touch_ui_image = _load_touch_ui_image(cfg, project_root)
            print("[INFO] config reloaded")
        if key == ord("p"):
            if debug_overlay is None:
                print("[WARN] no touch debug data yet, cannot export image")
            else:
                ts = time.strftime("%Y%m%d_%H%M%S")
                out_base = project_root / "debug_outputs" / f"controller_base_{ts}.png"
                out_render = project_root / "debug_outputs" / f"controller_touch_render_{ts}.png"
                ok_base = export_controller_base_image(debug_overlay, touch_ui_image, out_base)
                ok_render = export_controller_debug_image(debug_overlay, touch_ui_image, out_render)
                if ok_base and ok_render:
                    print(f"[INFO] touch debug images saved: {out_base}, {out_render}")
                else:
                    print(f"[WARN] failed to save touch debug images: base={out_base}, render={out_render}")
        if key in (ord("+"), ord("=")):
            touch_cfg = cfg.setdefault("controller_touch", {})
            curr = float(touch_cfg.get("global_scale", 1.0))
            curr = min(size_max, curr + size_step)
            touch_cfg["global_scale"] = curr
            print(f"[INFO] controller_touch.global_scale = {curr:.2f}")
        if key in (ord("-"), ord("_")):
            touch_cfg = cfg.setdefault("controller_touch", {})
            curr = float(touch_cfg.get("global_scale", 1.0))
            curr = max(size_min, curr - size_step)
            touch_cfg["global_scale"] = curr
            print(f"[INFO] controller_touch.global_scale = {curr:.2f}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run()

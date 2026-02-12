#!/usr/bin/env python3
import argparse
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

import cv2
import numpy as np
try:
    import mediapipe as mp
except Exception:
    mp = None


def has_mediapipe_pose_solutions() -> bool:
    if mp is None:
        return False
    solutions = getattr(mp, "solutions", None)
    if solutions is None:
        return False
    pose_mod = getattr(solutions, "pose", None)
    return pose_mod is not None and hasattr(pose_mod, "Pose") and hasattr(pose_mod, "PoseLandmark")


@dataclass
class MotionState:
    centers: Deque[Tuple[int, int]]
    upper_scores: Deque[float]
    lower_scores: Deque[float]


def build_hog_detector() -> cv2.HOGDescriptor:
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


def build_upper_body_detector() -> cv2.CascadeClassifier:
    cascade_path = cv2.data.haarcascades + "haarcascade_upperbody.xml"
    return cv2.CascadeClassifier(cascade_path)


def build_face_detector() -> cv2.CascadeClassifier:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    return cv2.CascadeClassifier(cascade_path)


def build_tracker() -> Optional[object]:
    creators = [
        ("TrackerCSRT_create", cv2),
        ("TrackerKCF_create", cv2),
        ("TrackerMIL_create", cv2),
    ]
    legacy = getattr(cv2, "legacy", None)
    if legacy is not None:
        creators.extend([
            ("TrackerCSRT_create", legacy),
            ("TrackerKCF_create", legacy),
            ("TrackerMIL_create", legacy),
        ])

    for name, mod in creators:
        fn = getattr(mod, name, None)
        if fn is not None:
            try:
                return fn()
            except Exception:
                continue
    return None


def detect_face_as_upper_body(face_cascade: cv2.CascadeClassifier,
                              frame: np.ndarray,
                              min_area: int) -> Tuple[Optional[Tuple[int, int, int, int]], int]:
    if face_cascade.empty():
        return None, 0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    boxes = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(36, 36),
    )
    if len(boxes) == 0:
        return None, 0

    frame_h, frame_w = frame.shape[:2]
    best_box = None
    best_area = 0
    valid_count = 0
    for (fx, fy, fw, fh) in boxes:
        torso_w = int(fw * 3.0)
        torso_h = int(fh * 5.0)
        torso_x = int(fx + fw * 0.5 - torso_w * 0.5)
        torso_y = int(fy - fh * 0.5)
        torso = clip_box((torso_x, torso_y, torso_w, torso_h), frame_w, frame_h)
        area = torso[2] * torso[3]
        if area < min_area // 3:
            continue
        valid_count += 1
        if area > best_area:
            best_area = area
            best_box = torso
    return best_box, valid_count


def detect_upper_body(upper_body_cascade: cv2.CascadeClassifier,
                      frame: np.ndarray,
                      min_area: int) -> Tuple[Optional[Tuple[int, int, int, int]], int]:
    if upper_body_cascade.empty():
        return None, 0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    boxes = upper_body_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(80, 80),
    )
    if len(boxes) == 0:
        return None, 0

    best_box = None
    best_area = 0
    valid_count = 0
    for (x, y, w, h) in boxes:
        area = int(w * h)
        if area < min_area // 3:
            continue
        valid_count += 1
        if area > best_area:
            best_area = area
            best_box = (int(x), int(y), int(w), int(h))
    return best_box, valid_count


def detect_person(hog: cv2.HOGDescriptor, frame: np.ndarray, min_area: int) -> Tuple[Optional[Tuple[int, int, int, int]], int]:
    boxes, weights = hog.detectMultiScale(
        frame,
        winStride=(8, 8),
        padding=(8, 8),
        scale=1.05,
    )
    if len(boxes) == 0:
        return None, 0

    best_box = None
    best_score = -1.0
    valid_count = 0
    for (x, y, w, h), conf in zip(boxes, weights):
        area = int(w * h)
        if area < min_area:
            continue
        valid_count += 1
        score = float(conf) * area
        if score > best_score:
            best_score = score
            best_box = (int(x), int(y), int(w), int(h))
    return best_box, valid_count


def clip_box(box: Tuple[int, int, int, int], width: int, height: int) -> Tuple[int, int, int, int]:
    x, y, w, h = box
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    return x, y, w, h


def draw_body_framework(frame: np.ndarray, box: Tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    cv2.rectangle(frame, (x, y), (x + w, y + h), (32, 220, 32), 2)

    head = (x + w // 2, y + int(0.12 * h))
    neck = (x + w // 2, y + int(0.22 * h))
    left_shoulder = (x + int(0.30 * w), y + int(0.27 * h))
    right_shoulder = (x + int(0.70 * w), y + int(0.27 * h))
    chest = (x + w // 2, y + int(0.36 * h))
    pelvis = (x + w // 2, y + int(0.58 * h))
    left_elbow = (x + int(0.20 * w), y + int(0.42 * h))
    right_elbow = (x + int(0.80 * w), y + int(0.42 * h))
    left_hand = (x + int(0.16 * w), y + int(0.56 * h))
    right_hand = (x + int(0.84 * w), y + int(0.56 * h))
    left_knee = (x + int(0.40 * w), y + int(0.77 * h))
    right_knee = (x + int(0.60 * w), y + int(0.77 * h))
    left_foot = (x + int(0.38 * w), y + int(0.96 * h))
    right_foot = (x + int(0.62 * w), y + int(0.96 * h))

    lines = [
        (head, neck),
        (neck, left_shoulder),
        (neck, right_shoulder),
        (left_shoulder, left_elbow),
        (left_elbow, left_hand),
        (right_shoulder, right_elbow),
        (right_elbow, right_hand),
        (neck, chest),
        (chest, pelvis),
        (pelvis, left_knee),
        (left_knee, left_foot),
        (pelvis, right_knee),
        (right_knee, right_foot),
    ]

    for p0, p1 in lines:
        cv2.line(frame, p0, p1, (64, 170, 255), 2)
    for point in [head, neck, left_shoulder, right_shoulder, pelvis, left_hand, right_hand, left_foot, right_foot]:
        cv2.circle(frame, point, 3, (255, 255, 255), -1)


def draw_upper_body_framework(frame: np.ndarray, box: Tuple[int, int, int, int]) -> None:
    x, y, w, h = box
    cv2.rectangle(frame, (x, y), (x + w, y + h), (32, 220, 32), 2)

    head = (x + w // 2, y + int(0.12 * h))
    neck = (x + w // 2, y + int(0.28 * h))
    left_shoulder = (x + int(0.25 * w), y + int(0.35 * h))
    right_shoulder = (x + int(0.75 * w), y + int(0.35 * h))
    chest = (x + w // 2, y + int(0.48 * h))
    left_elbow = (x + int(0.16 * w), y + int(0.55 * h))
    right_elbow = (x + int(0.84 * w), y + int(0.55 * h))
    left_hand = (x + int(0.14 * w), y + int(0.75 * h))
    right_hand = (x + int(0.86 * w), y + int(0.75 * h))

    lines = [
        (head, neck),
        (neck, left_shoulder),
        (neck, right_shoulder),
        (left_shoulder, left_elbow),
        (left_elbow, left_hand),
        (right_shoulder, right_elbow),
        (right_elbow, right_hand),
        (neck, chest),
    ]
    for p0, p1 in lines:
        cv2.line(frame, p0, p1, (64, 170, 255), 2)
    for point in [head, neck, left_shoulder, right_shoulder, left_hand, right_hand]:
        cv2.circle(frame, point, 3, (255, 255, 255), -1)


def draw_pose_upper_body(frame: np.ndarray, pose_landmarks, pose_landmark_enum, min_visibility: float = 0.35) -> bool:
    if pose_landmarks is None or pose_landmark_enum is None:
        return False

    h, w = frame.shape[:2]
    lms = pose_landmarks.landmark
    idx = pose_landmark_enum

    def point_of(landmark_id):
        lm = lms[int(landmark_id)]
        if lm.visibility < min_visibility:
            return None
        x = int(lm.x * w)
        y = int(lm.y * h)
        if x < 0 or y < 0 or x >= w or y >= h:
            return None
        return (x, y)

    p = {
        "nose": point_of(idx.NOSE),
        "left_shoulder": point_of(idx.LEFT_SHOULDER),
        "right_shoulder": point_of(idx.RIGHT_SHOULDER),
        "left_elbow": point_of(idx.LEFT_ELBOW),
        "right_elbow": point_of(idx.RIGHT_ELBOW),
        "left_wrist": point_of(idx.LEFT_WRIST),
        "right_wrist": point_of(idx.RIGHT_WRIST),
        "left_hip": point_of(idx.LEFT_HIP),
        "right_hip": point_of(idx.RIGHT_HIP),
    }

    pairs = [
        ("left_shoulder", "right_shoulder"),
        ("left_shoulder", "left_elbow"),
        ("left_elbow", "left_wrist"),
        ("right_shoulder", "right_elbow"),
        ("right_elbow", "right_wrist"),
        ("left_shoulder", "left_hip"),
        ("right_shoulder", "right_hip"),
        ("left_hip", "right_hip"),
    ]
    drawn = False
    for a, b in pairs:
        if p[a] is not None and p[b] is not None:
            cv2.line(frame, p[a], p[b], (0, 220, 255), 2)
            drawn = True
    for key in p:
        if p[key] is not None:
            cv2.circle(frame, p[key], 3, (255, 255, 255), -1)
            drawn = True
    return drawn


def roi_motion_score(curr_gray: np.ndarray, prev_gray: np.ndarray, roi: Tuple[int, int, int, int]) -> float:
    x, y, w, h = roi
    curr = curr_gray[y:y + h, x:x + w]
    prev = prev_gray[y:y + h, x:x + w]
    if curr.size == 0 or prev.size == 0:
        return 0.0
    diff = cv2.absdiff(curr, prev)
    return float(np.mean(diff))


def classify_action(state: MotionState) -> str:
    if len(state.centers) < 2:
        return "detecting"

    center_move = 0.0
    for i in range(1, len(state.centers)):
        p0 = np.array(state.centers[i - 1], dtype=np.float32)
        p1 = np.array(state.centers[i], dtype=np.float32)
        center_move += float(np.linalg.norm(p1 - p0))
    center_move /= max(1, len(state.centers) - 1)

    upper_motion = float(np.mean(state.upper_scores)) if state.upper_scores else 0.0
    lower_motion = float(np.mean(state.lower_scores)) if state.lower_scores else 0.0

    if upper_motion < 6.0 and lower_motion < 6.0 and center_move < 4.0:
        return "standing"
    if center_move > 10.0 or lower_motion > 11.0:
        return "walking_or_running"
    if upper_motion > 14.0 and center_move < 8.0:
        return "upper_body_active"
    return "moving"


def parse_resolution(value: str) -> Tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError("resolution format should be WIDTHxHEIGHT, e.g. 1280x720")
    width = int(parts[0])
    height = int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError("resolution width/height must be > 0")
    return width, height


def smooth_box_ema(prev_box: Optional[Tuple[float, float, float, float]],
                   new_box: Tuple[int, int, int, int],
                   alpha: float) -> Tuple[float, float, float, float]:
    nx, ny, nw, nh = [float(v) for v in new_box]
    if prev_box is None:
        return nx, ny, nw, nh
    px, py, pw, ph = prev_box
    return (
        alpha * nx + (1.0 - alpha) * px,
        alpha * ny + (1.0 - alpha) * py,
        alpha * nw + (1.0 - alpha) * pw,
        alpha * nh + (1.0 - alpha) * ph,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenCV human framework + action demo")
    parser.add_argument("--source", default="0", help="camera index like 0, or video file path")
    parser.add_argument("--min-area", type=int, default=12000, help="minimum person bbox area")
    parser.add_argument("--history", type=int, default=10, help="history length for action smoothing")
    parser.add_argument("--display-scale", type=float, default=1.0, help="display resize scale")
    parser.add_argument("--full-body", action="store_true", help="force full-body mode")
    parser.add_argument("--set-res", default="", help="set camera resolution, e.g. 1280x720")
    parser.add_argument("--debug", action="store_true", help="enable debug logs and overlays")
    parser.add_argument("--smooth-alpha", type=float, default=0.45, help="bbox smoothing alpha (0..1)")
    parser.add_argument("--detect-interval", type=int, default=6, help="run detector every N frames when tracking")
    parser.add_argument("--pose", choices=["auto", "on", "off"], default="auto",
                        help="use mediapipe pose for real skeleton drawing")
    parser.add_argument("--pose-min-visibility", type=float, default=0.35,
                        help="mediapipe landmark visibility threshold")
    args = parser.parse_args()

    source: int | str = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[ERROR] failed to open source: {args.source}")
        return 1
    if args.set_res:
        try:
            req_w, req_h = parse_resolution(args.set_res)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)
        except ValueError as exc:
            print(f"[ERROR] invalid --set-res: {exc}")
            return 1

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[INFO] camera resolution: {actual_w}x{actual_h}")

    hog = build_hog_detector()
    face_cascade = build_face_detector()
    upper_body_cascade = build_upper_body_detector()
    pose = None
    pose_landmark_enum = None
    mp_pose_available = has_mediapipe_pose_solutions()
    use_pose = (args.pose == "on" and mp_pose_available) or (args.pose == "auto" and mp_pose_available)
    if use_pose:
        pose = mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        pose_landmark_enum = mp.solutions.pose.PoseLandmark
        print("[INFO] pose: mediapipe enabled")
    else:
        if args.pose == "on" and not mp_pose_available:
            mp_ver = getattr(mp, "__version__", "unknown") if mp is not None else "not-installed"
            print(
                "[WARN] pose requested, but mediapipe pose solutions unavailable; fallback enabled "
                f"(python={sys.version_info.major}.{sys.version_info.minor}, mediapipe={mp_ver})"
            )
        print("[INFO] pose: fallback framework only")
    tracker = None
    tracker_enabled = True
    tracker_ok = False
    track_box: Optional[Tuple[int, int, int, int]] = None
    state = MotionState(centers=deque(maxlen=args.history), upper_scores=deque(maxlen=args.history), lower_scores=deque(maxlen=args.history))
    prev_gray = None
    prev_center: Optional[Tuple[int, int]] = None
    smoothed_box: Optional[Tuple[float, float, float, float]] = None
    last_stat_ts = time.time()
    stat_frames = 0
    stat_upper_detects = 0
    stat_face_detects = 0
    stat_full_detects = 0
    frame_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_index += 1
        frame_h, frame_w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        use_upper_body = not args.full_body
        upper_count = 0
        face_count = 0
        full_count = 0
        box = None
        detected_mode = "none"

        if tracker_enabled and tracker_ok and tracker is not None:
            ok_track, tracked = tracker.update(frame)
            if ok_track:
                tx, ty, tw, th = tracked
                box = clip_box((int(tx), int(ty), int(tw), int(th)), frame_w, frame_h)
                detected_mode = "tracker"
            else:
                tracker_ok = False

        need_detect = (box is None) or (args.detect_interval > 0 and (frame_index % args.detect_interval == 0))
        if need_detect:
            det_box = None
            det_mode = "none"
            if use_upper_body:
                det_box, face_count = detect_face_as_upper_body(face_cascade, frame, args.min_area)
                if det_box is not None:
                    det_mode = "face_upper"
                else:
                    det_box, upper_count = detect_upper_body(upper_body_cascade, frame, args.min_area)
                    if det_box is not None:
                        det_mode = "upper_body"
            if det_box is None:
                det_box, full_count = detect_person(hog, frame, args.min_area)
                if det_box is not None:
                    det_mode = "full_body"

            if det_box is not None:
                box = det_box
                detected_mode = det_mode
                if tracker_enabled:
                    tracker = build_tracker()
                    if tracker is not None:
                        init_box = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
                        try:
                            init_ret = tracker.init(frame, init_box)
                            tracker_ok = True if init_ret is None else bool(init_ret)
                        except cv2.error:
                            tracker_ok = False
                    else:
                        tracker_ok = False
                        tracker_enabled = False
        stat_frames += 1
        if upper_count > 0:
            stat_upper_detects += 1
        if face_count > 0:
            stat_face_detects += 1
        if full_count > 0:
            stat_full_detects += 1

        if box is not None:
            box = clip_box(box, frame_w, frame_h)
            smoothed_box = smooth_box_ema(smoothed_box, box, max(0.0, min(1.0, args.smooth_alpha)))
            box = clip_box((int(smoothed_box[0]), int(smoothed_box[1]), int(smoothed_box[2]), int(smoothed_box[3])),
                           frame_w, frame_h)
            x, y, w, h = box
            center = (x + w // 2, y + h // 2)
            state.centers.append(center)

            if prev_gray is not None:
                upper_roi = clip_box((x, y, w, max(1, h // 2)), frame_w, frame_h)
                lower_roi = clip_box((x, y + h // 2, w, max(1, h // 2)), frame_w, frame_h)
                state.upper_scores.append(roi_motion_score(gray, prev_gray, upper_roi))
                state.lower_scores.append(roi_motion_score(gray, prev_gray, lower_roi))

            action = classify_action(state)
            pose_drawn = False
            if pose is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = pose.process(rgb)
                pose_drawn = draw_pose_upper_body(
                    frame,
                    result.pose_landmarks,
                    pose_landmark_enum,
                    min_visibility=max(0.0, min(1.0, args.pose_min_visibility)),
                )

            if not pose_drawn:
                if detected_mode == "upper_body":
                    draw_upper_body_framework(frame, box)
                elif detected_mode == "face_upper":
                    draw_upper_body_framework(frame, box)
                else:
                    draw_body_framework(frame, box)
            cv2.putText(frame, f"mode:{detected_mode} action:{action}",
                        (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 250, 20), 2)
            if args.debug:
                delta = 0.0
                if prev_center is not None:
                    delta = float(np.linalg.norm(np.array(center, dtype=np.float32) -
                                                 np.array(prev_center, dtype=np.float32)))
                cv2.putText(frame, f"box=({x},{y},{w},{h}) area={w*h} delta={delta:.1f}px",
                            (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 210, 0), 2)
                prev_center = center
        else:
            cv2.putText(frame, "person: not found", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 120, 255), 2)
            prev_center = None

        now_ts = time.time()
        elapsed = now_ts - last_stat_ts
        if elapsed >= 1.0:
            fps = stat_frames / elapsed
            if args.debug:
                print(f"[DEBUG] fps={fps:.1f} face_count={face_count} upper_count={upper_count} "
                      f"full_count={full_count} mode={detected_mode} track_ok={tracker_ok} "
                      f"frame={frame_w}x{frame_h}")
            else:
                print(f"[INFO] fps={fps:.1f} face_hit={stat_face_detects} upper_hit={stat_upper_detects} "
                      f"full_hit={stat_full_detects}")
            last_stat_ts = now_ts
            stat_frames = 0
            stat_face_detects = 0
            stat_upper_detects = 0
            stat_full_detects = 0

        prev_gray = gray

        if args.display_scale != 1.0:
            view = cv2.resize(frame, None, fx=args.display_scale, fy=args.display_scale)
        else:
            view = frame
        if args.debug:
            cv2.putText(view, f"res:{frame_w}x{frame_h}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
        cv2.imshow("OpenCV Human Action Demo", view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    cap.release()
    if pose is not None:
        pose.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

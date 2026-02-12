#!/usr/bin/env python3
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def http_get_json(base_url: str, path: str, params: dict | None = None, timeout: float = 3.0) -> dict:
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params)
    url = f"{base_url}{path}{query}"
    req = urllib.request.Request(url=url, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def assert_ok(name: str, payload: dict) -> None:
    if not payload.get("ok"):
        raise AssertionError(f"[{name}] not ok: {payload}")


def run_tests(base_url: str, timeout: float) -> None:
    print(f"Testing HTTP API on: {base_url}")

    health = http_get_json(base_url, "/health", timeout=timeout)
    assert_ok("health", health)
    print("✓ /health")

    button = http_get_json(base_url, "/button", {"name": "B"}, timeout=timeout)
    assert_ok("button", button)
    if button.get("button") != "B":
        raise AssertionError(f"[/button] unexpected button: {button}")
    print("✓ /button?name=B")

    press = http_get_json(base_url, "/press", {"name": "A"}, timeout=timeout)
    assert_ok("press", press)
    if press.get("mode") != "press":
        raise AssertionError(f"[/press] unexpected mode: {press}")
    print("✓ /press?name=A")

    hold = http_get_json(base_url, "/hold", {"name": "HOME", "ms": "300"}, timeout=timeout)
    assert_ok("hold", hold)
    if hold.get("mode") != "hold":
        raise AssertionError(f"[/hold] unexpected mode: {hold}")
    print("✓ /hold?name=HOME&ms=300")

    time.sleep(0.35)
    release = http_get_json(base_url, "/release", timeout=timeout)
    assert_ok("release", release)
    if release.get("mode") != "release":
        raise AssertionError(f"[/release] unexpected mode: {release}")
    print("✓ /release")

    auto = http_get_json(base_url, "/auto", timeout=timeout)
    assert_ok("auto", auto)
    if auto.get("mode") != "auto":
        raise AssertionError(f"[/auto] unexpected mode: {auto}")
    print("✓ /auto")

    print("All API checks passed.")


def run_stress(base_url: str, loops: int, interval: float, timeout: float) -> None:
    buttons = [
        "Y", "X", "B", "A", "L", "R", "ZL", "ZR",
        "MINUS", "PLUS", "L_STICK", "R_STICK",
        "HOME", "CAPTURE", "UP", "DOWN", "LEFT", "RIGHT",
    ]
    print(f"Stress mode: loops={loops}, interval={interval}s, target={base_url}")

    for index in range(1, loops + 1):
        button = random.choice(buttons)
        hold_ms = random.choice([50, 80, 100, 150, 200, 300])
        payload = http_get_json(base_url, "/hold", {"name": button, "ms": str(hold_ms)}, timeout=timeout)
        assert_ok("hold", payload)
        print(f"[{index:04d}/{loops}] hold {button} {hold_ms}ms")
        time.sleep(interval)

    http_get_json(base_url, "/release", timeout=timeout)
    http_get_json(base_url, "/auto", timeout=timeout)
    print("Stress mode finished.")


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenSwitchBridge HTTP API tester")
    parser.add_argument(
        "--host",
        default="192.168.4.1",
        help="Target device IP or host (default: 192.168.4.1)",
    )
    parser.add_argument(
        "--port",
        default=80,
        type=int,
        help="Target HTTP port (default: 80)",
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="Run stress loop instead of one-shot smoke tests",
    )
    parser.add_argument(
        "--loops",
        default=200,
        type=int,
        help="Stress loops count (default: 200)",
    )
    parser.add_argument(
        "--interval",
        default=0.2,
        type=float,
        help="Stress request interval seconds (default: 0.2)",
    )
    parser.add_argument(
        "--timeout",
        default=8.0,
        type=float,
        help="HTTP timeout seconds (default: 8.0)",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    try:
        if args.stress:
            run_stress(base_url, args.loops, args.interval, args.timeout)
        else:
            run_tests(base_url, args.timeout)
        return 0
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 2
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f"API test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

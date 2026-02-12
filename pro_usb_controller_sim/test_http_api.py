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
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"[HTTP {exc.code}] {url} -> {err_body}") from exc
    return json.loads(body)


def assert_ok(name: str, payload: dict) -> None:
    if not payload.get("ok"):
        raise AssertionError(f"[{name}] not ok: {payload}")


def api_input(base_url: str, buttons: str, timeout: float, ms: int = 0,
              lx: int | None = None, ly: int | None = None,
              rx: int | None = None, ry: int | None = None,
              hat: int | None = None) -> dict:
    button_value = urllib.parse.quote(buttons, safe=",+")
    query_parts = [f"buttons={button_value}"]
    if ms > 0:
        query_parts.append(f"ms={ms}")
    if lx is not None:
        query_parts.append(f"lx={lx}")
    if ly is not None:
        query_parts.append(f"ly={ly}")
    if rx is not None:
        query_parts.append(f"rx={rx}")
    if ry is not None:
        query_parts.append(f"ry={ry}")
    if hat is not None:
        query_parts.append(f"hat={hat}")
    path = "/input?" + "&".join(query_parts)
    return http_get_json(base_url, path, timeout=timeout)


def api_sequence(base_url: str, steps: str, timeout: float, gap: int = 50, repeat: bool = False) -> dict:
    step_value = urllib.parse.quote(steps, safe=">,:+,")
    path = f"/sequence?steps={step_value}&gap={gap}&repeat={'1' if repeat else '0'}"
    return http_get_json(base_url, path, timeout=timeout)


def run_tests(base_url: str, timeout: float) -> None:
    print(f"Testing HTTP API on: {base_url}")

    health = http_get_json(base_url, "/health", timeout=timeout)
    assert_ok("health", health)
    print("✓ /health")

    input_single = api_input(base_url, "B", timeout=timeout)
    assert_ok("input_single", input_single)
    if input_single.get("mode") != "input":
        raise AssertionError(f"[/input single] unexpected payload: {input_single}")
    print("✓ /input?buttons=B")

    input_press = api_input(base_url, "A", timeout=timeout, ms=100)
    assert_ok("input_press", input_press)
    print("✓ /input?buttons=A&ms=100")

    hold = api_input(base_url, "HOME", timeout=timeout, ms=300)
    assert_ok("hold", hold)
    print("✓ /input?buttons=HOME&ms=300")

    chord = api_input(base_url, "A,B,X,Y,UP", timeout=timeout, ms=800)
    assert_ok("chord", chord)
    print("✓ /input?buttons=A,B,X,Y,UP&ms=800")

    sequence = api_sequence(
        base_url,
        "L:120>R:120>L:120>R:120>B:120>A:120>B:120>A:120",
        timeout=timeout,
        gap=50,
        repeat=False,
    )
    assert_ok("sequence", sequence)
    print("✓ /sequence?steps=...&gap=50&repeat=0")
    time.sleep(0.8)

    combo_loop = api_sequence(
        base_url,
        "UP:100>RIGHT:100>DOWN:100>LEFT:100",
        timeout=timeout,
        gap=40,
        repeat=True,
    )
    assert_ok("combo_loop", combo_loop)
    print("✓ combo loop /sequence repeat=1")
    time.sleep(0.5)

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
        if random.random() < 0.15:
            sequence = random.choice([
                "L:120>R:120>L:120>R:120>B:120>A:120>B:120>A:120",
                "UP:100>DOWN:100>LEFT:100>RIGHT:100",
                "A,B:120>X,Y:120>L,R:120",
            ])
            gap_ms = random.choice([30, 50, 80])
            payload = api_sequence(base_url, sequence, timeout=timeout, gap=gap_ms, repeat=False)
            assert_ok("sequence", payload)
            print(f"[{index:04d}/{loops}] sequence gap={gap_ms}ms")
        else:
            button = random.choice(buttons)
            hold_ms = random.choice([50, 80, 100, 150, 200, 300])
            payload = api_input(base_url, button, timeout=timeout, ms=hold_ms)
            assert_ok("input", payload)
            print(f"[{index:04d}/{loops}] input {button} {hold_ms}ms")
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

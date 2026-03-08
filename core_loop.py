from __future__ import annotations

"""
Core Perception Loop — grabs frames from Mentra bridge or webcam,
detects sustained focus via perceptual hashing, calls Claude Vision
for structured scene analysis, and publishes GOTO commands over MQTT.
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env file if present (key=value, one per line)
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

from utils.interest_detector import InterestDetector
from utils.command_bus import CommandBus

# ─── Optional imports ────────────────────────────────────────────────────────

try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ─── Configuration ───────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-20250514"

SCENE_ANALYSIS_PROMPT = """\
You are analyzing a scene captured from a child's point of view through camera glasses.
Identify the main object or thing the child appears to be focused on (usually center of frame).

Respond ONLY with valid JSON in this exact format:
{
  "object": "<short name of the object>",
  "description": "<one sentence describing what you see>",
  "location_hint": "<left|right|center|above|below>",
  "category": "<toy|nature|animal|food|book|art|building|person|other>",
  "suggested_actions": ["<action 1>", "<action 2>"]
}
"""

# ─── Image sources ───────────────────────────────────────────────────────────


def capture_from_webcam(webcam_index: int = 0) -> bytes | None:
    """Capture a single frame from the webcam as JPEG bytes."""
    if not CV2_AVAILABLE:
        print("  opencv-python not found: pip install opencv-python")
        return None
    cap = cv2.VideoCapture(webcam_index)
    if not cap.isOpened():
        print("  Could not open webcam.")
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    # Discard initial frames (often dark/blurry)
    for _ in range(8):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return None
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buffer.tobytes()


def fetch_from_bridge(bridge_url: str) -> bytes | None:
    """Download the latest photo from the Mentra bridge."""
    if not REQUESTS_AVAILABLE:
        print("  requests not installed: pip install requests")
        return None
    try:
        r = requests.get(f"{bridge_url}/photo", timeout=10)
        if r.status_code == 200:
            return r.content
        elif r.status_code == 503:
            print("  No photo available yet...")
    except Exception as e:
        print(f"  Bridge error: {e}")
    return None


def wait_for_bridge(bridge_url: str, timeout: int = 30) -> bool:
    """Wait for the Mentra bridge to become available."""
    if not REQUESTS_AVAILABLE:
        return False
    print(f"Waiting for Mentra bridge at {bridge_url} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{bridge_url}/status", timeout=2)
            if r.status_code == 200:
                print("Bridge ready.")
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ─── Claude Vision ───────────────────────────────────────────────────────────


def analyze_scene(claude, frame_bytes: bytes) -> dict | None:
    """Send frame to Claude Vision, return structured scene analysis."""
    image_b64 = base64.standard_b64encode(frame_bytes).decode("utf-8")

    try:
        response = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=SCENE_ANALYSIS_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "What is the child focused on?",
                        },
                    ],
                }
            ],
        )

        text = response.content[0].text.strip()
        # Handle markdown-wrapped JSON
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    except json.JSONDecodeError as e:
        print(f"  Claude returned invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Reachy Mini — Core Perception Loop"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Use local webcam instead of Mentra bridge"
    )
    parser.add_argument(
        "--image", type=str, default=None,
        help="Use a static image file (repeats it as frames, for testing)"
    )
    parser.add_argument(
        "--bridge", type=str, default="http://localhost:7001",
        help="Mentra bridge URL (default: http://localhost:7001)"
    )
    parser.add_argument(
        "--broker", type=str, default=None,
        help="MQTT broker hostname"
    )
    parser.add_argument(
        "--mqtt-port", type=int, default=1883,
        help="MQTT broker port (default: 1883)"
    )
    parser.add_argument(
        "--interest-time", type=float, default=3.0,
        help="Seconds of focus to trigger interest (default: 3.0)"
    )
    parser.add_argument(
        "--similarity", type=float, default=0.85,
        help="Frame similarity threshold (default: 0.85)"
    )
    parser.add_argument(
        "--cooldown", type=float, default=8.0,
        help="Seconds to wait after triggering before re-detecting (default: 8.0)"
    )
    parser.add_argument(
        "--http-agents", nargs="*", default=[],
        help="HTTP fallback agent endpoints (e.g. http://localhost:8001)"
    )
    parser.add_argument(
        "--frame-interval", type=float, default=0.5,
        help="Seconds between frame captures (default: 0.5 = 2 FPS)"
    )
    args = parser.parse_args()

    # ── Check prerequisites ──────────────────────────────────────────────────

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not set.")
        print("  export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    if not CLAUDE_AVAILABLE:
        print("anthropic not installed: pip install anthropic")
        sys.exit(1)

    claude = Anthropic(api_key=api_key)

    # ── Setup image source ───────────────────────────────────────────────────

    if args.image:
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"Image file not found: {args.image}")
            sys.exit(1)
        image_bytes = image_path.read_bytes()
        print(f"Static image mode — using {args.image} ({len(image_bytes):,} bytes)")
        get_photo = lambda: image_bytes
    elif args.demo:
        if not CV2_AVAILABLE:
            print("Demo mode requires opencv-python: pip install opencv-python")
            sys.exit(1)
        print("Demo mode — using local webcam")
        get_photo = lambda: capture_from_webcam()
    else:
        if not wait_for_bridge(args.bridge):
            print("Bridge not available. Is glasses_server.ts running?")
            sys.exit(1)
        get_photo = lambda: fetch_from_bridge(args.bridge)

    # ── Setup command bus ────────────────────────────────────────────────────

    bus = CommandBus(
        mqtt_broker=args.broker,
        mqtt_port=args.mqtt_port,
        http_endpoints=args.http_agents,
    )
    mqtt_ok = bus.connect()
    if mqtt_ok:
        print(f"Connected to MQTT broker at {args.broker}")
    elif args.http_agents:
        print(f"Using HTTP fallback to: {', '.join(args.http_agents)}")
    else:
        print("WARNING: No MQTT broker and no --http-agents. Commands won't reach agents.")

    # ── Setup interest detector ──────────────────────────────────────────────

    detector = InterestDetector(
        similarity_threshold=args.similarity,
        interest_time=args.interest_time,
    )

    # ── Banner ───────────────────────────────────────────────────────────────

    print("\n" + "=" * 60)
    print("  REACHY MINI — CORE PERCEPTION LOOP")
    print("=" * 60)
    print(f"  Source:      {'Webcam (demo)' if args.demo else f'Mentra bridge ({args.bridge})'}")
    print(f"  Model:       {CLAUDE_MODEL}")
    print(f"  Focus time:  {args.interest_time}s")
    print(f"  Similarity:  {args.similarity}")
    print(f"  Cooldown:    {args.cooldown}s")
    print(f"  Transport:   {'MQTT' if mqtt_ok else 'HTTP fallback'}")
    print(f"  Frame rate:  {1/args.frame_interval:.1f} FPS")
    print("=" * 60 + "\n")
    print("Watching... (Ctrl+C to stop)\n")

    # ── Main loop ────────────────────────────────────────────────────────────

    interaction_id = 0
    cooldown_until = 0.0

    try:
        while True:
            now = time.time()

            # Cooldown check
            if now < cooldown_until:
                time.sleep(args.frame_interval)
                continue

            # Capture frame
            frame_bytes = get_photo()
            if frame_bytes is None:
                time.sleep(args.frame_interval)
                continue

            # Check for sustained focus
            result = detector.update(frame_bytes, now)

            if result["focused"]:
                interaction_id += 1
                focus_duration = result["duration"]

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"INTEREST #{interaction_id} detected "
                    f"(focused {focus_duration:.1f}s, similarity {result['similarity']:.2f})"
                )

                # Analyze with Claude Vision
                print("  Analyzing scene with Claude...")
                scene = analyze_scene(claude, frame_bytes)

                if scene:
                    # Build and publish GOTO command
                    frame_b64 = base64.standard_b64encode(frame_bytes).decode("utf-8")
                    goto_cmd = {
                        "type": "goto",
                        "interaction_id": interaction_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "object": scene.get("object", "unknown"),
                        "description": scene.get("description", ""),
                        "location_hint": scene.get("location_hint", "center"),
                        "category": scene.get("category", "other"),
                        "suggested_actions": scene.get("suggested_actions", []),
                        "focus_duration": round(focus_duration, 1),
                        "frame_b64": frame_b64,
                    }

                    print(
                        f"  => {scene.get('object', '?')} "
                        f"({scene.get('category', '?')}, {scene.get('location_hint', '?')})"
                    )
                    print(f"  => {scene.get('description', '')}")

                    bus.publish("reachy/commands/goto", goto_cmd)
                    print("  => GOTO command published")
                else:
                    print("  => Scene analysis failed, skipping")

                # Enter cooldown
                detector.reset()
                cooldown_until = time.time() + args.cooldown

            time.sleep(args.frame_interval)

    except KeyboardInterrupt:
        print("\n\nShutting down core loop.")
        bus.publish("reachy/commands/system", {"type": "shutdown"})
    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()

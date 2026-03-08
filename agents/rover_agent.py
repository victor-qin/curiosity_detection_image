from __future__ import annotations

"""
Rover Agent — Claude-powered wheeled robot that drives toward objects.

Receives GOTO commands, asks Claude which driving behavior to use,
then executes via differential drive motor commands (HTTP POST).
Falls back to deterministic steering map when Claude is unavailable.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.base_agent import BaseAgent
from utils.claude_agent_mixin import ClaudeAgentMixin
from utils.behavior_registry import ROVER_BEHAVIORS

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Deterministic fallback (same as nav_agent.py)
STEERING_MAP = {
    "left":   (0.3, 0.7, 800),
    "right":  (0.7, 0.3, 800),
    "center": (0.5, 0.5, 1000),
    "up":     (0.5, 0.5, 600),
    "down":   (0.4, 0.4, 500),
}


class RoverAgent(BaseAgent, ClaudeAgentMixin):
    AGENT_NAME = "rover-agent"
    BEHAVIOR_VOCABULARY = ROVER_BEHAVIORS

    ROBOT_SYSTEM_PROMPT = """\
You are Rover, a small wheeled robot that drives around exploring the world.
A child wearing camera glasses looks at interesting things, and you drive toward them.

PERSONALITY: Methodical but enthusiastic. You're a determined little explorer.
You take careful paths but get genuinely excited when you find something.

You do NOT speak or narrate — you only move physically.
Choose the driving behavior that best matches the situation.\
"""

    def __init__(self):
        super().__init__()
        self.motor_url = os.environ.get("MOTOR_URL")
        self._processing = threading.Lock()

    def on_start(self):
        if self.motor_url:
            print(f"[{self.AGENT_NAME}] Motor controller: {self.motor_url}")
        else:
            print(f"[{self.AGENT_NAME}] No MOTOR_URL set — simulation mode")

        if not self.args.no_claude:
            self.init_claude(model=self.args.model)
        else:
            print(f"[{self.AGENT_NAME}] Claude disabled — deterministic only")

    def handle_goto(self, payload: dict):
        if not self._processing.acquire(blocking=False):
            print(f"[{self.AGENT_NAME}] Still processing previous command, skipping")
            return

        threading.Thread(
            target=self._process_goto,
            args=(payload,),
            daemon=True,
        ).start()

    def _process_goto(self, payload: dict):
        try:
            self._do_goto(payload)
        finally:
            self._processing.release()

    def _do_goto(self, payload: dict):
        self.update_session_context(payload)
        location = payload.get("location_hint", "center")
        obj_name = payload.get("object", "unknown")

        # Try Claude
        if self._claude is not None:
            user_text = (
                f"A child is looking at: {obj_name} "
                f"({payload.get('description', '')}). "
                f"It appears to be {location} in their view. "
                f"Decide how to drive toward it."
            )
            result = self.call_claude(
                frame_b64=payload.get("frame_b64"),
                user_text=user_text,
                timeout=5.0,
            )
            if result:
                behavior = result.get("behavior", "drive_toward")
                direction = result.get("direction", location)
                print(
                    f"[{self.AGENT_NAME}] Claude chose: {behavior} "
                    f"(direction={direction}, thought={result.get('internal_thought', '')})"
                )
                self._execute_behavior(behavior, direction, obj_name, payload)
                return

        # Deterministic fallback
        self._deterministic_drive(location, obj_name, payload)

    def _execute_behavior(self, behavior: str, direction: str, obj_name: str, payload: dict):
        behavior_def = ROVER_BEHAVIORS.get(behavior)
        if not behavior_def:
            print(f"[{self.AGENT_NAME}] Unknown behavior '{behavior}', falling back to drive_toward")
            behavior_def = ROVER_BEHAVIORS["drive_toward"]
            behavior = "drive_toward"

        if "motor_sequence" in behavior_def:
            for cmd in behavior_def["motor_sequence"]:
                self._send_motor_command(cmd, obj_name)
                time.sleep(cmd["duration_ms"] / 1000.0)
        elif "motor_map" in behavior_def:
            motor_map = behavior_def["motor_map"]
            if "left" in motor_map:
                # Direct motor command (no direction needed)
                self._send_motor_command(motor_map, obj_name)
            else:
                # Direction-keyed motor map
                cmd = motor_map.get(direction, motor_map.get("center", {"left": 0.5, "right": 0.5, "duration_ms": 800}))
                self._send_motor_command(cmd, obj_name)

        self.publish_event({
            "event": "navigation_complete",
            "interaction_id": payload.get("interaction_id"),
            "behavior": behavior,
            "direction": direction,
            "object": obj_name,
            "simulated": self.motor_url is None,
        })

    def _deterministic_drive(self, location: str, obj_name: str, payload: dict):
        left, right, duration = STEERING_MAP.get(location, (0.5, 0.5, 800))
        cmd = {"left": left, "right": right, "duration_ms": duration}
        self._send_motor_command(cmd, obj_name)

        self.publish_event({
            "event": "navigation_complete",
            "interaction_id": payload.get("interaction_id"),
            "behavior": "drive_toward",
            "direction": location,
            "object": obj_name,
            "simulated": self.motor_url is None,
        })

    def _send_motor_command(self, cmd: dict, obj_name: str):
        if self.motor_url and REQUESTS_AVAILABLE:
            try:
                r = requests.post(
                    f"{self.motor_url}/drive",
                    json=cmd,
                    timeout=5,
                )
                print(
                    f"[{self.AGENT_NAME}] Drive toward '{obj_name}' — "
                    f"L:{cmd.get('left')} R:{cmd.get('right')} "
                    f"{cmd.get('duration_ms')}ms [{r.status_code}]"
                )
            except Exception as e:
                print(f"[{self.AGENT_NAME}] Motor command failed: {e}")
        else:
            print(
                f"[{self.AGENT_NAME}] [SIM] Drive toward '{obj_name}' — "
                f"L:{cmd.get('left')} R:{cmd.get('right')} "
                f"{cmd.get('duration_ms')}ms"
            )


if __name__ == "__main__":
    RoverAgent().run()

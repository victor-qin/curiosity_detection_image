from __future__ import annotations

"""
Body Agent — controls Reachy Mini robot head animations.

Subscribes to GOTO commands (plays "thinking" animation) and
narrate agent events (plays "excited" when narration finishes).
Silently no-ops if no Reachy hardware is connected.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.base_agent import BaseAgent

try:
    from reachy_sdk import ReachySDK
    REACHY_AVAILABLE = True
except ImportError:
    REACHY_AVAILABLE = False


class BodyAgent(BaseAgent):
    AGENT_NAME = "body-agent"

    def __init__(self):
        super().__init__()
        self.reachy = None

    def add_args(self, parser):
        parser.add_argument(
            "--reachy-ip", type=str, default="localhost",
            help="Reachy Mini IP address (default: localhost)"
        )

    def on_start(self):
        # Subscribe to narrate agent events for post-narration animation
        self.bus.subscribe("reachy/events/identify-agent", self._on_narration)

        if not REACHY_AVAILABLE:
            print(f"[{self.AGENT_NAME}] reachy_sdk not installed — animation disabled")
            return

        try:
            self.reachy = ReachySDK(host=self.args.reachy_ip)
            print(f"[{self.AGENT_NAME}] Connected to Reachy at {self.args.reachy_ip}")
        except Exception as e:
            print(f"[{self.AGENT_NAME}] Could not connect to Reachy: {e}")
            self.reachy = None

    def handle_goto(self, payload: dict):
        """Play "thinking" animation when a new object is detected."""
        obj_name = payload.get("object", "something")
        print(f"[{self.AGENT_NAME}] Thinking about '{obj_name}'...")
        self._run_async(self._anim_thinking)

    def _on_narration(self, topic: str, payload: dict):
        """Play "excited" animation when narration finishes."""
        print(f"[{self.AGENT_NAME}] Narration done — excited!")
        self._run_async(self._anim_excited)

    def _run_async(self, fn):
        """Run animation in a daemon thread so it doesn't block message processing."""
        threading.Thread(target=self._safe_move, args=(fn,), daemon=True).start()

    def _safe_move(self, fn):
        try:
            fn()
        except Exception:
            pass

    def _anim_thinking(self):
        if not self.reachy:
            return
        self.reachy.head.look_at(x=1, y=0, z=0.18, duration=0.7)
        time.sleep(0.6)
        self.reachy.head.look_at(x=1, y=0, z=0, duration=0.7)

    def _anim_excited(self):
        if not self.reachy:
            return
        for _ in range(2):
            self.reachy.head.look_at(x=1, y=0.15, z=0.1, duration=0.25)
            time.sleep(0.15)
            self.reachy.head.look_at(x=1, y=-0.15, z=0.1, duration=0.25)
            time.sleep(0.15)
        self.reachy.head.look_at(x=1, y=0, z=0, duration=0.3)

    def _anim_happy(self):
        if not self.reachy:
            return
        self.reachy.head.look_at(x=1, y=0, z=0, duration=0.4)
        time.sleep(0.2)
        self.reachy.head.look_at(x=1, y=0.12, z=0.08, duration=0.35)
        time.sleep(0.2)
        self.reachy.head.look_at(x=1, y=0, z=0, duration=0.35)


if __name__ == "__main__":
    BodyAgent().run()

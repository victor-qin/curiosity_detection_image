# Reachy Mini Multi-Agent Perception System

## What This Is

A multi-agent system that watches what a child looks at through camera glasses, detects when they focus on something interesting, identifies the object, and coordinates robots to react — driving toward it, animating, narrating facts, and logging the interaction.

Built for children ages 6-9 interacting with a Reachy Mini humanoid robot plus companion robots (wheeled rover, flying butterfly drone).

## How It Works (30-Second Version)

```
Camera frames (JPEG)
  → Perceptual hashing detects sustained gaze (≥3s on same scene)
  → Claude Vision identifies the object as structured JSON
  → GOTO command published to all agents via MQTT (or HTTP fallback)
  → Agents react in parallel:
      Rover: drives toward the object
      Butterfly: flies toward it
      Body: animates Reachy's head (curious, excited, etc.)
      Narrator: speaks 4-5 creative sentences about it
      Logger: records everything to disk
```

## Integration Point: Image Input

**This is what you need to connect.** The core loop (`core_loop.py`) fetches JPEG frames from one of three sources:

### Current: HTTP polling from glasses bridge
```
GET http://localhost:7001/photo → raw JPEG bytes
GET http://localhost:7001/status → {"status": "ok"}
```

The core loop polls this endpoint every 500ms (2 FPS). The bridge server (`glasses_server.ts`) is **not in this repo** — it runs on the glasses hardware and serves frames over HTTP.

### Alternative: Static image or webcam
```bash
python core_loop.py --image test_sunflower.jpg   # static file, loops
python core_loop.py --demo                        # local webcam via OpenCV
```

### Future: WebSocket
The system is designed to be switched to WebSocket input. The integration point is a single function in `core_loop.py`:

```python
# Current: HTTP polling
get_photo = lambda: fetch_from_bridge(args.bridge)

# To integrate WebSocket, replace with:
get_photo = lambda: ws_client.get_latest_frame()
```

All downstream processing (hashing, Claude Vision, GOTO commands) is agnostic to how the frame arrived.

## MQTT Topics (Message Contract)

### Commands (published by core_loop, consumed by agents)

**`reachy/commands/goto`** — "Look at this object"
```json
{
  "type": "goto",
  "interaction_id": 1,
  "timestamp": "2026-03-08T14:32:01Z",
  "object": "sunflower",
  "description": "A tall yellow sunflower with a brown center",
  "location_hint": "center",        // left|right|center|up|down
  "category": "nature",             // nature|animal|toy|food|book|other
  "suggested_actions": ["count the petals", "smell it"],
  "focus_duration": 3.2,
  "source": "child-camera",         // or "butterfly-agent" for discoveries
  "frame_b64": "<base64 JPEG>",     // full image for agents with Vision
  "recent_objects": ["sunflower"]    // memory of recent objects
}
```

**`reachy/commands/context`** — "Here's what's happening in the demo"
```json
{
  "type": "context",
  "scene_id": "single_sunflower",
  "timestamp": "2026-03-08T14:32:01Z",
  "hints": {
    "body-agent": "Show gentle curiosity, lean in to look.",
    "rover-agent": "Drive forward slowly.",
    "butterfly-agent": "Fly to it eagerly.",
    "identify-agent": "Use WONDER mode about sunflowers."
  }
}
```

**`reachy/commands/system`** — "Shut down"
```json
{"type": "shutdown"}
```

### Events (published by agents, consumed by body-agent + log-agent)

**`reachy/events/{agent-name}`** — "I finished doing something"
```json
{
  "agent": "rover-agent",
  "event": "navigation_complete",
  "interaction_id": 1,
  "behavior": "drive_toward",
  "direction": "center",
  "object": "sunflower",
  "simulated": true
}
```

## Transport: CommandBus

`utils/command_bus.py` abstracts MQTT and HTTP behind a single API:

```python
bus = CommandBus(mqtt_broker="localhost", mqtt_port=1883,
                 http_endpoints=["http://localhost:8001", ...])
bus.connect()           # True if MQTT connected
bus.publish(topic, payload)
bus.subscribe(topic, handler)
bus.loop_forever()      # blocking (for agents)
```

**MQTT** is primary. If unavailable, falls back to **HTTP POST** to each agent's `POST /command` endpoint with topic in `X-Reachy-Topic` header.

## Agents (What They Do)

| Agent | Port | Purpose | Outbound Hardware |
|-------|------|---------|-------------------|
| `rover_agent.py` | 8001 | Drives wheeled robot toward objects | `POST $MOTOR_URL/drive` |
| `butterfly_agent.py` | 8002 | Flies drone toward objects | `POST $FLIGHT_CONTROLLER_URL/command` |
| `body_agent.py` | 8003 | Animates Reachy's head | Reachy SDK (TCP) |
| `identify_agent.py` | — | Speaks creative narration | gTTS → system audio |
| `log_agent.py` | 8004 | Records all interactions | `reachy_sessions.jsonl` |

Each agent independently:
1. Receives GOTO commands
2. Asks Claude which behavior to use (or falls back to deterministic)
3. Executes the behavior on hardware (or simulates)
4. Publishes a completion event

### Rover Motor Commands
```json
POST $MOTOR_URL/drive
{"left": 0.5, "right": 0.5, "duration_ms": 1000}
```
Values are 0.0-1.0 speed (negative for reverse). If `MOTOR_URL` is unset, commands are printed only (simulation mode).

### Butterfly Flight Commands
```json
POST $FLIGHT_CONTROLLER_URL/command
{"behavior": "fly_toward", "direction": "left", ...}
```

## Interest Detection (How Gaze Tracking Works)

`utils/interest_detector.py` uses perceptual hashing:

1. Convert JPEG → 16x16 grayscale → 256-float vector
2. Compare to EMA-blended reference (80% old + 20% new)
3. Similarity = normalized cross-correlation (0.0 to 1.0)
4. If similarity ≥ 0.85 for ≥ 3 seconds → **interest triggered**
5. One-shot: won't re-fire until child looks away (similarity drops)

The EMA blending means gradual head movement doesn't break tracking — only looking at something distinctly different resets the detector.

## Demo Scripting (Choreographed Demos)

`demos/example_demo.json` defines timed scenes with scripted discoveries:

```
0-30s:  Child sees sunflower → agents react
  20s:  Butterfly "discovers" a sunflower field → rover speaks about it
30-60s: Exploring the sunflower field → agents react
  45s:  Butterfly finds a baby sunflower → rover speaks
```

Run with: `./dev.sh --script=demos/example_demo.json`

In demo mode, Claude Vision is skipped — the script provides object metadata directly. Agents still use Claude for their individual behavior decisions.

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (unless demo-only) | Claude Vision + agent conversations |
| `MOTOR_URL` | No | Rover motor controller (`http://host:port`) |
| `FLIGHT_CONTROLLER_URL` | No | Butterfly flight controller |

## Running

```bash
# Full stack with static image
./dev.sh

# With demo script
./dev.sh --script=demos/example_demo.json

# With webcam
./dev.sh --demo

# Pointing at glasses bridge
python core_loop.py --bridge http://glasses-host:7001 \
  --http-agents http://localhost:8001 http://localhost:8002 \
                http://localhost:8003 http://localhost:8004

# No Claude (deterministic only)
./dev.sh --no-claude
```

## Key Files for Integration

| What you need | File | Why |
|---------------|------|-----|
| **Image input** | `core_loop.py` lines 75-110 | `fetch_from_bridge()` and `get_photo` lambda — replace these to change image source |
| **Frame format** | `core_loop.py` | Raw JPEG bytes. Must be valid JPEG that OpenCV/PIL can decode. |
| **GOTO payload** | `core_loop.py` lines 460-475 | Full payload structure including `frame_b64` (base64-encoded JPEG) |
| **Transport setup** | `utils/command_bus.py` | MQTT broker config or HTTP endpoint list |
| **Interest tuning** | `utils/interest_detector.py` | `similarity_threshold`, `interest_time`, `ema_alpha` |

## What Needs to Change for WebSocket Integration

1. **New image source in `core_loop.py`**: Replace `fetch_from_bridge()` with a WebSocket client that receives JPEG frames
2. **New command output**: Replace `bus.publish("reachy/commands/goto", ...)` with WebSocket sends to robot controllers
3. **Frame rate**: Currently 2 FPS polling. WebSocket could push frames faster — but the perceptual hashing + Claude Vision pipeline is the bottleneck, not frame capture
4. **Robot commands**: Currently HTTP POST to `MOTOR_URL`/`FLIGHT_CONTROLLER_URL`. Could be WebSocket messages instead

The internal architecture (hashing, memory, Claude calls, agent behavior selection) stays the same regardless of transport.

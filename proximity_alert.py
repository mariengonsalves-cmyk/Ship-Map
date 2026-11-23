#!/usr/bin/env python3
"""Ship proximity alert.

Listens to live AIS data (AISstream.io) for two ships and sends a phone push
notification (ntfy.sh) when they come within THRESHOLD_NM of each other, and
again when they drift apart.

Environment variables:
  AISSTREAM_API_KEY  required  (free key from https://aisstream.io)
  NTFY_TOPIC         optional  (your private ntfy topic name; phone alerts are skipped if unset)
  THRESHOLD_NM       optional  default 25
  LISTEN_SECONDS     optional  default 200
  TEST_NOTIFY        optional  "true" = just send a test notification and exit
"""
import asyncio
import json
import math
import os
import sys
import time
import urllib.request

MY_SHIP = {"name": "Brilliance of the Seas", "mmsi": "311361000"}
HER_SHIP = {"name": "Margaritaville at Sea Paradise", "mmsi": "311000969"}

THRESHOLD_NM = float(os.environ.get("THRESHOLD_NM", "25"))
HYSTERESIS_NM = 2.0  # must be this far outside the range before "left range" fires
LISTEN_SECONDS = int(os.environ.get("LISTEN_SECONDS", "480"))
STATE_FILE = "state.json"
POSITIONS_FILE = "positions.json"  # read by index.html (the live map page)
EARTH_RADIUS_NM = 3440.065


def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def decide(distance_nm, was_in_range, threshold=THRESHOLD_NM, hysteresis=HYSTERESIS_NM):
    """Return (event, now_in_range). event is 'entered', 'left' or None."""
    if not was_in_range and distance_nm <= threshold:
        return "entered", True
    if was_in_range and distance_nm > threshold + hysteresis:
        return "left", False
    return None, was_in_range


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"in_range": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def save_positions(found):
    """Merge newly heard positions into positions.json for the map page."""
    try:
        with open(POSITIONS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    ships = data.get("ships", {})
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for mmsi, (lat, lon) in found.items():
        ships[mmsi] = {"lat": lat, "lon": lon, "time": now}
    with open(POSITIONS_FILE, "w") as f:
        json.dump({"updated": now, "ships": ships}, f, indent=1)


def notify(topic, title, message, priority="default", tags="ship"):
    if not topic:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority, "Tags": tags},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


async def listen(api_key, seconds):
    """Collect the latest position of each ship. Returns {mmsi: (lat, lon)}.

    Reconnects after any connection problem until the time window ends.
    """
    import websockets  # pip install websockets

    wanted = {MY_SHIP["mmsi"], HER_SHIP["mmsi"]}
    found = {}
    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": sorted(wanted),
        "FilterMessageTypes": ["PositionReport"],
    }
    deadline = time.time() + seconds
    received = 0
    attempt = 0
    while time.time() < deadline and len(found) < len(wanted):
        attempt += 1
        try:
            async with websockets.connect(
                "wss://stream.aisstream.io/v0/stream",
                open_timeout=30,
                ping_interval=20,
            ) as ws:
                print(f"Connected to AISstream (attempt {attempt}).")
                await ws.send(json.dumps(subscription))
                while time.time() < deadline and len(found) < len(wanted):
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.time()))
                    msg = json.loads(raw)
                    received += 1
                    if "error" in msg:
                        print("AISstream error:", msg["error"])
                        print(f"Feed messages received: {received}")
                        return found
                    try:
                        mmsi = str(msg["MetaData"]["MMSI"])
                        report = msg["Message"]["PositionReport"]
                        lat, lon = report["Latitude"], report["Longitude"]
                    except (KeyError, TypeError):
                        continue
                    if mmsi in wanted and abs(lat) <= 90 and abs(lon) <= 180:
                        found[mmsi] = (lat, lon)
                        print(f"Got position for {mmsi}: {lat:.4f}, {lon:.4f}")
        except asyncio.TimeoutError:
            break  # the listening window ended while waiting for a message
        except Exception as exc:  # connection refused, handshake timeout, dropped link
            print(f"Connection problem ({type(exc).__name__}: {exc}). Retrying in 10 s.")
            await asyncio.sleep(10)
    print(f"Feed messages received: {received}")
    return found


def main():
    topic = os.environ.get("NTFY_TOPIC")

    if os.environ.get("TEST_NOTIFY", "").lower() == "true":
        if not topic:
            sys.exit("NTFY_TOPIC is not set")
        notify(topic, "Ship alert test", "Notifications are working.")
        print("Test notification sent.")
        return

    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        sys.exit("AISSTREAM_API_KEY is not set")

    found = asyncio.run(listen(api_key, LISTEN_SECONDS))
    if found:
        save_positions(found)
    mine, hers = found.get(MY_SHIP["mmsi"]), found.get(HER_SHIP["mmsi"])
    if not (mine and hers):
        missing = [s["name"] for s in (MY_SHIP, HER_SHIP) if s["mmsi"] not in found]
        print("No position received for:", ", ".join(missing), "- skipping this run.")
        return

    distance = haversine_nm(*mine, *hers)
    print(f"Distance: {distance:.1f} NM (threshold {THRESHOLD_NM:g} NM)")

    state = load_state()
    event, now_in_range = decide(distance, state.get("in_range", False))

    if event == "entered":
        notify(
            topic,
            "Ships are close!",
            f"{MY_SHIP['name']} and {HER_SHIP['name']} are {distance:.1f} NM apart.",
            priority="high",
            tags="ship,tada",
        )
    elif event == "left":
        notify(
            topic,
            "Ships drifting apart",
            f"The ships are now {distance:.1f} NM apart.",
            tags="ship",
        )

    if now_in_range != state.get("in_range", False):
        save_state({"in_range": now_in_range})


if __name__ == "__main__":
    main()

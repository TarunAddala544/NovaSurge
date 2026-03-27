#!/usr/bin/env python3
"""Test WebSocket connection."""

import asyncio
import json
import websockets


async def test_websocket():
    uri = "ws://localhost:8000/ws/stream"
    print(f"Connecting to {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to WebSocket")

            # Receive messages for 20 seconds
            for i in range(4):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10)
                    data = json.loads(message)

                    print(f"\n📨 Message {i+1}:")
                    print(f"  Timestamp: {data.get('timestamp')}")
                    print(f"  Anomaly: {data.get('anomaly') is not None}")
                    print(f"  Scores: {json.dumps(data.get('scores', {}), indent=4)}")

                    if data.get('anomaly'):
                        print(f"  🚨 ANOMALY: {data['anomaly']}")

                    if data.get('reasoning'):
                        print(f"  💭 Reasoning: {data['reasoning'][:100]}...")

                except asyncio.TimeoutError:
                    print("⏱️  Timeout waiting for message")
                    break

            print("\n✅ WebSocket test complete")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_websocket())

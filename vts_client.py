import asyncio
import websockets
import json

VTS_URL = "ws://127.0.0.1:8001"

async def send_expression(hotkey):
    async with websockets.connect(VTS_URL) as ws:
        msg = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": "test",
            "messageType": "HotkeyTriggerRequest",
            "data": {
                "hotkeyID": hotkey
            }
        }
        await ws.send(json.dumps(msg))
        await ws.recv()


def vts_set_expression(mode):
    try:
        if mode == "talk":
            asyncio.run(send_expression("Talk"))
        elif mode == "idle":
            asyncio.run(send_expression("Idle"))
    except Exception as e:
        print("[VTS 오류]", e)
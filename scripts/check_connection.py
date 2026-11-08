"""Non-secret AssemblyAI connection check for the workspace trial."""
import asyncio
import json

import websockets

from tt.storage import load_api_key


async def main():
    key = load_api_key()
    if not key:
        print("NO_KEY")
        return
    url = "wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&speech_model=universal-3-6-pro"
    async with websockets.connect(url, additional_headers={"Authorization": key}, open_timeout=10) as socket:
        message = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
        print("RESPONSE", message.get("type"))
        await socket.send('{"type":"Terminate"}')
        await asyncio.wait_for(socket.recv(), timeout=10)
        print("CONNECTION_OK")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as exc:
        print(f"NETWORK_ERROR {type(exc).__name__}: {exc}")
    except Exception as exc:
        print(f"CONNECTION_ERROR {type(exc).__name__}: {exc}")

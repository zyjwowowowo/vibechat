"""Run against a live local API: python scripts/smoke.py [base_url]."""

import asyncio
import json
import sys
import time

import httpx
import websockets


base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def create_user() -> tuple[dict, dict]:
    session = httpx.post(f"{base_url}/api/v1/sessions", timeout=10).raise_for_status().json()
    return session, {"X-Session-Token": session["token"]}


first, first_headers = create_user()
second, second_headers = create_user()

first_emotion = httpx.post(
    f"{base_url}/api/v1/emotions/analyze",
    headers=first_headers,
    json={"text": "最近项目压力很大，我有点焦虑，担心自己做不好。"},
    timeout=10,
).raise_for_status().json()
second_emotion = httpx.post(
    f"{base_url}/api/v1/emotions/analyze",
    headers=second_headers,
    json={"text": "明天要交作品了，我很紧张，也担心来不及。"},
    timeout=10,
).raise_for_status().json()

first_ticket = httpx.post(
    f"{base_url}/api/v1/matches",
    headers=first_headers,
    json={"emotion_id": first_emotion["id"]},
    timeout=10,
).raise_for_status().json()
second_ticket = httpx.post(
    f"{base_url}/api/v1/matches",
    headers=second_headers,
    json={"emotion_id": second_emotion["id"]},
    timeout=10,
).raise_for_status().json()

first_match = httpx.get(
    f"{base_url}/api/v1/matches/{first_ticket['ticket_id']}", headers=first_headers, timeout=10
).raise_for_status().json()
assert first_match["conversation_id"] == second_ticket["conversation_id"]

conversation_id = first_match["conversation_id"]
message = httpx.post(
    f"{base_url}/api/v1/conversations/{conversation_id}/messages",
    headers=first_headers,
    json={"content": "原来你也在经历相似的紧张。"},
    timeout=10,
).raise_for_status().json()
conversation = httpx.get(
    f"{base_url}/api/v1/conversations/{conversation_id}", headers=second_headers, timeout=10
).raise_for_status().json()
assert conversation["kind"] == "human"
assert any(item["id"] == message["id"] for item in conversation["messages"])


async def websocket_roundtrip() -> None:
    ws_base = base_url.replace("http://", "ws://").replace("https://", "wss://")
    socket_url = f"{ws_base}/api/v1/ws/conversations/{conversation_id}"
    async with websockets.connect(socket_url, subprotocols=["vibechat", f"token.{first['token']}"]) as first_socket:
        async with websockets.connect(socket_url, subprotocols=["vibechat", f"token.{second['token']}"]) as second_socket:
            await first_socket.send(json.dumps({"type": "message", "content": "WebSocket 也已同频。"}))
            for socket in (first_socket, second_socket):
                while True:
                    event = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
                    if event.get("type") == "message.created":
                        assert event["message"]["content"] == "WebSocket 也已同频。"
                        break


asyncio.run(websocket_roundtrip())

# A lone user should be moved into a clearly identified AI conversation after timeout.
third, third_headers = create_user()
third_emotion = httpx.post(
    f"{base_url}/api/v1/emotions/analyze",
    headers=third_headers,
    json={"text": "忙完以后突然觉得有一点空，好像没人能听我说话。"},
    timeout=10,
).raise_for_status().json()
third_ticket = httpx.post(
    f"{base_url}/api/v1/matches",
    headers=third_headers,
    json={"emotion_id": third_emotion["id"]},
    timeout=10,
).raise_for_status().json()
time.sleep(2.2)
third_match = httpx.get(
    f"{base_url}/api/v1/matches/{third_ticket['ticket_id']}", headers=third_headers, timeout=10
).raise_for_status().json()
ai_conversation = httpx.get(
    f"{base_url}/api/v1/conversations/{third_match['conversation_id']}", headers=third_headers, timeout=10
).raise_for_status().json()
assert ai_conversation["kind"] == "ai"
assert any(item["is_ai"] for item in ai_conversation["participants"])

print(
    {
        "status": "ok",
        "users": [first["nickname"], second["nickname"]],
        "emotion": first_emotion["primary_emotion"],
        "match_score": first_match["match_score"],
        "conversation_id": conversation_id,
        "messages": len(conversation["messages"]),
        "ai_fallback": ai_conversation["kind"],
    }
)

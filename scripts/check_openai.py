"""Inspect accessible model IDs without printing credentials or error bodies."""
import asyncio
import httpx
from app.credentials import get_api_key


async def main():
    key = get_api_key()
    if not key:
        raise SystemExit("OpenAI is not configured")
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        response = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    if response.status_code != 200:
        print("Authentication/model listing HTTP status:", response.status_code)
        raise SystemExit(1)
    models = sorted(m["id"] for m in response.json()["data"] if m["id"].startswith(("gpt-6", "gpt-5", "o3")))
    print("Authentication verified. Available reasoning models:")
    for model in models:
        print(model)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from .config import get_settings

async def poll_loop():
    settings = get_settings()
    print(f"Worker started, polling every {settings.worker_poll_interval}s", flush=True)
    while True:
        # Job runner will be added in Task 11
        await asyncio.sleep(settings.worker_poll_interval)

def main():
    asyncio.run(poll_loop())

if __name__ == "__main__":
    main()

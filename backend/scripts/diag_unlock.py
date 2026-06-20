"""调试 HDHive 解锁响应。"""
import asyncio
import json
import re

from app.services.hdhive_service import hdhive_service
from app.services.runtime_settings_service import runtime_settings_service


async def main() -> None:
    runtime_settings_service.apply_runtime_overrides()
    slug = "5d367b70795311efa3030242ac120003"
    web = hdhive_service._web
    html = await web._fetch_text(f"/resource/115/{slug}")

    chunk_paths = web._extract_next_static_chunk_paths(html)
    print("chunk paths:", len(chunk_paths))
    for path in chunk_paths[:8]:
        print(" ", path)

    for fn_name in (
        "unlockResource",
        "getShareLink",
        "getResourceLink",
        "fetchShareLink",
        "getPan115Link",
        "getResource",
    ):
        for path in chunk_paths:
            try:
                chunk_text = await web._fetch_text(
                    path, accept="application/javascript,text/javascript,*/*;q=0.8"
                )
            except Exception:
                continue
            action_id = web._extract_server_action_id_from_chunk(chunk_text, fn_name)
            if action_id:
                print(f"found {fn_name} action:", action_id)

    action_result = await web._unlock_resource_via_next_action(slug, html)
    print("\naction_result:", json.dumps(action_result, ensure_ascii=False)[:2500])

    unlock = await hdhive_service.unlock_resource(slug)
    print("\nunlock:", json.dumps(unlock, ensure_ascii=False)[:800])

    # Search response text for 115 links
    raw = str(action_result.get("raw") or "")
    links = re.findall(r"https?://[^\"\\;\\s]+115[^\"\\;\\s]*", raw)
    print("links in raw:", links[:5])


if __name__ == "__main__":
    asyncio.run(main())

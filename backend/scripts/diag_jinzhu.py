"""诊断金猪玉叶 HDHive 转存链路。"""
import asyncio
import json

from app.models.models import MediaType
from app.services.hdhive_service import hdhive_service
from app.services.subscription_service import SubscriptionService, SubscriptionSnapshot


async def main() -> None:
    resources = await hdhive_service.get_tv_pan115(256018)
    print("=== HDHive raw resources ===")
    print(json.dumps(resources, ensure_ascii=False, indent=2)[:5000])

    sub = SubscriptionSnapshot(
        id=0,
        tmdb_id=256018,
        douban_id="256018",
        title="金猪玉叶",
        media_type=MediaType.TV,
        year="2024",
        auto_download=False,
        tv_scope="all",
        tv_season_number=None,
        tv_episode_start=None,
        tv_episode_end=None,
        tv_follow_mode="missing",
        tv_include_specials=False,
        has_successful_transfer=False,
    )
    svc = SubscriptionService()
    primary, traces, meta = await svc._fetch_resources(channel="all", sub=sub)
    print("\n=== After _fetch_resources ===")
    print("primary count:", len(primary))
    print("attempts:", meta.get("attempts"))
    for i, resource in enumerate(primary[:5]):
        print(f"--- resource {i} ---")
        print("name:", resource.get("resource_name") or resource.get("name"))
        print("source:", resource.get("source_service"))
        print("share_link:", resource.get("share_link") or resource.get("pan115_share_link"))
        print("locked:", resource.get("hdhive_locked"), "unlock_points:", resource.get("unlock_points"))
        print("slug:", resource.get("slug"))
    print("\n=== Key traces ===")
    for trace in traces:
        step = str(trace.get("step") or "")
        if any(key in step for key in ("hdhive", "quality", "unlock", "fetch", "offline")):
            print(step, "|", str(trace.get("message") or "")[:240])


if __name__ == "__main__":
    asyncio.run(main())

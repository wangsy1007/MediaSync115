import asyncio
from time import monotonic

from app.services.hdhive_service import HDHiveService


class TestHDHiveService:
    def test_extract_current_user_with_points(self) -> None:
        raw = (
            'xxx\\"currentUser\\":{\\"username\\":\\"alice\\",\\"nickname\\":\\"Alice\\",'
            '\\"is_vip\\":true,\\"points\\":128,\\"permissions\\":[]}yyy'
        )

        user = HDHiveService._extract_current_user(raw)

        assert user == {
            "username": "alice",
            "nickname": "Alice",
            "is_vip": True,
            "points": 128,
        }

    def test_extract_current_user_with_credit_balance_text(self) -> None:
        raw = (
            'xxx"currentUser":{"username":"bob","nickname":"","is_vip":0,'
            '"credit_balance":"86 points","permissions":[]}yyy'
        )

        user = HDHiveService._extract_current_user(raw)

        assert user == {
            "username": "bob",
            "nickname": "",
            "is_vip": False,
            "points": 86,
        }

    def test_extract_current_user_with_nested_user_meta_points(self) -> None:
        raw = (
            'xxx"currentUser":{"username":"carol","nickname":"Carol","is_vip":true,'
            '"user_meta":{"points":781,"signin_days_total":37},"permissions":null}yyy'
        )

        user = HDHiveService._extract_current_user(raw)

        assert user == {
            "username": "carol",
            "nickname": "Carol",
            "is_vip": True,
            "points": 781,
        }

    def test_get_user_info_merges_points_from_settings_page(self) -> None:
        service = HDHiveService(cookie="test-cookie")

        async def fake_get_user_info() -> dict:
            return {
                "username": "dave",
                "nickname": "Dave",
                "is_vip": True,
                "points": 502,
            }

        async def fake_ensure_authenticated(*args, **kwargs) -> None:
            return None

        service._web.get_user_info = fake_get_user_info  # type: ignore[method-assign]
        service.ensure_authenticated = fake_ensure_authenticated  # type: ignore[method-assign]

        user = asyncio.run(service.get_user_info())

        assert user == {
            "id": None,
            "username": "dave",
            "nickname": "Dave",
            "email": "",
            "avatar_url": "",
            "is_vip": True,
            "vip_expiration_date": "",
            "last_active_at": "",
            "points": 502,
            "user_meta": {},
            "telegram_user": None,
            "created_at": "",
        }

    def test_extract_server_action_id_from_chunk(self) -> None:
        raw = (
            'xxx(0,e.createServerReference)("40104633e124c17495f8f0497d9a91bd9a5b843744",'
            'e.callServer,void 0,e.findSourceMapURL,"unlockResource")yyy'
        )

        action_id = HDHiveService._extract_server_action_id_from_chunk(raw, "unlockResource")

        assert action_id == "40104633e124c17495f8f0497d9a91bd9a5b843744"

    def test_build_cookie_header_refreshes_action_token(self) -> None:
        service = HDHiveService(cookie="token=abc; hdh_sa_token=stale-token")
        client = service._web._create_client()
        client.cookies.set("hdh_sa_token", "fresh-token")
        header = service._web._build_cookie_header(client, service._web._cookie)
        assert "token=abc" in header
        assert "hdh_sa_token=fresh-token" in header
        assert "stale-token" not in header

    def test_is_action_token_error(self) -> None:
        service = HDHiveService()
        assert service._web._is_action_token_error({"code": "action_token_invalid"}) is True
        assert service._web._is_action_token_error({"code": "action_token_required"}) is True
        assert service._web._is_action_token_error({"code": "200"}) is False

    def test_parse_next_action_plain_json_error(self) -> None:
        service = HDHiveService()
        parsed = service._web._parse_next_action_response(
            '{"success":false,"code":"action_token_invalid","message":"请刷新页面后重试"}'
        )
        assert parsed["success"] is False
        assert parsed["code"] == "action_token_invalid"
        assert parsed["message"] == "请刷新页面后重试"

    def test_extract_checkin_action_id_from_chunk(self) -> None:
        raw = (
            'xxx(0,e.createServerReference)("406e0e83ed93f56902b65d137f5f98bfb98187e837",'
            'e.callServer,void 0,e.findSourceMapURL,"checkIn")yyy'
        )

        action_id = HDHiveService._extract_server_action_id_from_chunk(raw, "checkIn")

        assert action_id == "406e0e83ed93f56902b65d137f5f98bfb98187e837"

    def test_extract_next_static_chunk_paths(self) -> None:
        raw = (
            'a "/_next/static/chunks/abc123.js" b '
            '"/_next/static/chunks/def456.js" c '
            '"/_next/static/chunks/abc123.js"'
        )

        paths = HDHiveService._extract_next_static_chunk_paths(raw)

        assert paths == [
            "/_next/static/chunks/abc123.js",
            "/_next/static/chunks/def456.js",
        ]

    def test_map_resource_row_marks_api_resource_as_locked_until_unlock(self) -> None:
        service = HDHiveService()

        row = service._map_resource_row(
            {
                "slug": "a1b2c3d4e5f647898765432112345678",
                "title": "Fight Club 4K REMUX",
                "pan_type": "115",
                "media_url": "https://hdhive.com/movie/example",
                "media_slug": "905baf2b010911ee89d70242ac130004",
                "share_size": "58.3 GB",
                "video_resolution": ["2160p"],
                "source": ["REMUX"],
                "remark": "杜比视界",
                "unlock_points": 10,
                "validate_status": "valid",
                "validate_message": None,
                "is_unlocked": False,
                "is_official": True,
            },
            0,
        )

        assert row["slug"] == "a1b2c3d4e5f647898765432112345678"
        assert row["share_link"] == ""
        assert row["unlock_points"] == 10
        assert row["hdhive_locked"] is True
        assert row["hdhive_pan_type"] == "115"
        assert row["hdhive_media_url"] == "https://hdhive.com/movie/example"
        assert row["hdhive_media_slug"] == "905baf2b010911ee89d70242ac130004"
        assert row["hdhive_resource_url"] == "https://hdhive.com/movie/example"
        assert row["pan115_savable"] is False

    def test_extract_share_link_from_action_data(self) -> None:
        service = HDHiveService()
        share_link, access_code, already_owned = service._web._extract_share_link_from_action_data(
            {
                "success": True,
                "message": "资源已解锁，无需重复支付",
                "data": {
                    "access_code": "",
                    "already_owned": True,
                    "full_url": "https://115.com/s/swhzqwy3wwq?password=ddc3&#",
                    "url": "https://115.com/s/swhzqwy3wwq?password=ddc3&#",
                },
            }
        )

        assert share_link == "https://115.com/s/swhzqwy3wwq?password=ddc3"
        assert access_code == ""
        assert already_owned is True

    def test_extract_share_link_from_action_data_with_separate_code(self) -> None:
        service = HDHiveService()
        share_link, access_code, already_owned = service._web._extract_share_link_from_action_data(
            {
                "success": True,
                "data": {
                    "access_code": "abcd",
                    "already_owned": False,
                    "full_url": "",
                    "url": "https://115.com/s/example",
                },
            }
        )

        assert share_link == "https://115.com/s/example?password=abcd"
        assert access_code == "abcd"
        assert already_owned is False

    def test_resolve_unlock_action_id_uses_cache_without_refetch(self) -> None:
        service = HDHiveService()
        web = service._web
        web._unlock_action_id = "cached-action-id"
        web._unlock_action_id_cached_at = monotonic()

        async def fake_fetch(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("should not fetch chunks when action id cache is warm")

        web._fetch_text_with_retry = fake_fetch  # type: ignore[method-assign]
        action_id = asyncio.run(web._resolve_unlock_action_id("<html></html>"))
        assert action_id == "cached-action-id"

    def test_unlock_resource_skips_action_when_page_already_has_link(self) -> None:
        service = HDHiveService(cookie="token=test")
        web = service._web
        slug = "abc123def456"
        share_url = "https://115.com/s/example?password=abcd"
        html = (
            f'\\"slug\\":\\"{slug}\\",\\"data\\":{{'
            f'\\"url\\":\\"{share_url}\\",\\"access_code\\":\\"abcd\\",\\"full_url\\":\\"{share_url}\\",'
            f'\\"unlock_points\\":0}},\\"error\\":null,\\"poster\\":'
        )

        async def fake_fetch(client, path, accept=None, max_retries=2):  # noqa: ANN001
            assert path == f"/resource/115/{slug}"
            return html

        async def fake_prefetch(client) -> None:  # noqa: ANN001
            return None

        async def fake_unlock_action(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("should not call unlock action when page already unlocked")

        web._fetch_text_with_retry_using_client = fake_fetch  # type: ignore[method-assign]
        web._prefetch_action_token = fake_prefetch  # type: ignore[method-assign]
        web._unlock_resource_via_next_action = fake_unlock_action  # type: ignore[method-assign]

        result = asyncio.run(web.unlock_resource(slug))
        assert result["success"] is True
        assert result["method"] == "cached_page"
        assert result["share_link"] == share_url

    def test_list_resources_by_tmdb_only_keeps_115_rows(self) -> None:
        service = HDHiveService(cookie="test-cookie")

        async def fake_collect(tmdb_id: int, media_type: str, *, target_pan_type: str = "115"):
            assert tmdb_id == 550
            assert media_type == "movie"
            assert target_pan_type == "115"
            rows = [
                {
                    "slug": "115slug",
                    "title": "Fight Club 115",
                    "pan_type": "115",
                    "share_size": "10 GB",
                },
                {
                    "slug": "quarkslug",
                    "title": "Fight Club Quark",
                    "pan_type": "quark",
                    "share_size": "11 GB",
                },
                {
                    "slug": "baiduslug",
                    "title": "Fight Club Baidu",
                    "pan_type": "baidu",
                    "share_size": "12 GB",
                },
                {
                    "slug": "115slug2",
                    "title": "Fight Club 115 2",
                    "pan_type": "115.com",
                    "share_size": "13 GB",
                },
            ]
            filtered = []
            for idx, row in enumerate(rows):
                if service._normalize_pan_type(row.get("pan_type")) != "115":
                    continue
                filtered.append(service._map_resource_row(row, idx))
            return {
                "items": filtered,
                "raw_total": len(rows),
                "filtered_total": len(filtered),
                "pan_type_counts": {"115": 2, "quark": 1, "baidu": 1},
            }

        async def fake_ensure_authenticated(*args, **kwargs) -> None:
            return None

        service._web._collect_tmdb_resources = fake_collect  # type: ignore[method-assign]
        service.ensure_authenticated = fake_ensure_authenticated  # type: ignore[method-assign]

        rows = asyncio.run(service.get_movie_pan115(550))

        assert [row["slug"] for row in rows] == ["115slug", "115slug2"]
        assert all(row["hdhive_pan_type"] == "115" for row in rows)

    def test_extract_bracket_payload_respects_string_brackets(self) -> None:
        raw = r'prefix \"115\":[{\"title\":\"A [4K]\",\"remark\":\"line1\nline2\"}] suffix'
        payload = HDHiveService._extract_bracket_payload(raw, '\\"115\\":[')
        parsed = HDHiveService._decode_json_candidates(payload)
        assert parsed
        rows = parsed[0]
        assert isinstance(rows, list)
        assert rows[0]["title"] == "A [4K]"

import asyncio

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
        service = HDHiveService(api_key="test-key")

        async def fake_request_open_api(method: str, path: str, **kwargs):
            assert method == "GET"
            assert path == "/me"
            return None, {
                "success": True,
                "code": "200",
                "message": "success",
                "data": {
                    "id": 1,
                    "username": "dave",
                    "nickname": "Dave",
                    "email": "dave@example.com",
                    "avatar_url": "https://example.com/avatar.jpg",
                    "is_vip": True,
                    "user_meta": {
                        "points": 502,
                    },
                },
            }

        service._request_open_api = fake_request_open_api  # type: ignore[method-assign]

        user = asyncio.run(service.get_user_info())

        assert user == {
            "id": 1,
            "username": "dave",
            "nickname": "Dave",
            "email": "dave@example.com",
            "avatar_url": "https://example.com/avatar.jpg",
            "is_vip": True,
            "vip_expiration_date": "",
            "last_active_at": "",
            "points": 502,
            "user_meta": {
                "points": 502,
            },
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
        service = HDHiveService(api_key="test-key")

        row = service._map_resource_row(
            {
                "slug": "a1b2c3d4e5f647898765432112345678",
                "title": "Fight Club 4K REMUX",
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
        assert row["pan115_savable"] is False

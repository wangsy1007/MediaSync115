from io import BytesIO

from PIL import Image

from app.services.library_cover_service import LibraryCoverService


def _sample_posters(count: int = 9) -> list[Image.Image]:
    colors = [
        (220, 60, 60),
        (60, 120, 220),
        (60, 180, 100),
        (240, 180, 40),
        (160, 80, 200),
        (40, 180, 180),
        (230, 120, 80),
        (90, 90, 200),
        (200, 90, 140),
    ]
    images: list[Image.Image] = []
    for idx in range(count):
        color = colors[idx % len(colors)]
        images.append(Image.new("RGB", (300, 450), color))
    return images


def test_compose_grid_cover():
    service = LibraryCoverService()
    cover = service._compose_cover(
        _sample_posters(),
        style="grid",
        title="电影",
        width=960,
        height=540,
    )
    assert cover.size == (960, 540)
    buf = BytesIO()
    cover.save(buf, format="JPEG")
    assert len(buf.getvalue()) > 1000


def test_compose_blur_and_single_cover():
    service = LibraryCoverService()
    posters = _sample_posters(5)
    blur = service._compose_cover(
        posters, style="blur", title="剧集", width=1280, height=720
    )
    single = service._compose_cover(
        posters, style="single", title="动漫", width=1280, height=720
    )
    assert blur.size == (1280, 720)
    assert single.size == (1280, 720)

from src.property_media_upload import use_multipart


def test_large_property_media_uses_multipart_policy() -> None:
    assert use_multipart(8 * 1024 * 1024) is True
    assert use_multipart(8 * 1024 * 1024 - 1) is False

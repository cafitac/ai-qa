from pathlib import Path


def is_screenshot(path: Path, content: bytes | None = None) -> bool:
    magic = {
        ".png": b"\x89PNG\r\n\x1a\n",
        ".jpg": b"\xff\xd8\xff",
        ".jpeg": b"\xff\xd8\xff",
    }.get(path.suffix.lower())
    if magic is None or path.is_symlink() or not path.is_file():
        return False
    if content is None:
        with path.open("rb") as handle:
            content = handle.read(8)
    return content.startswith(magic)

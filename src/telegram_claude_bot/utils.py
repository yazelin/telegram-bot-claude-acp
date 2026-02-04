"""
Utility functions for Telegram Claude Bot.
"""

import hashlib
import logging
import os
import re
from glob import glob
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def expand_directory_patterns(patterns: list[str]) -> list[str]:
    """
    Expand glob patterns into a list of absolute directory paths.

    Patterns may include:
    - "/home/user/projects/*" - immediate subdirectories
    - "/home/user/projects/**" - all subdirectories recursively
    - "/home/user/projects/app" - specific directory

    Non-existent or non-directory matches are ignored.
    """
    dirs: set[str] = set()

    for pattern in patterns:
        matches = glob(pattern, recursive=True)
        for match in matches:
            path = Path(match)
            try:
                if path.is_dir():
                    dirs.add(str(path.resolve()))
            except OSError:
                pass

    return sorted(dirs)


def split_long_message(text: str, max_len: int = 4096) -> list[str]:
    """
    Split a long message into chunks that fit within Telegram's limit.

    Tries to split on newline boundaries when possible.
    """
    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        chunk = remaining[:max_len]
        # Try to split on newline
        last_newline = chunk.rfind("\n")
        if last_newline > max_len * 0.8:
            chunk = remaining[: last_newline + 1]

        chunks.append(chunk)
        remaining = remaining[len(chunk) :]

    return chunks


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.

    Characters that need escaping: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def format_markdown_for_telegram(text: str) -> str:
    """
    Convert standard Markdown to Telegram MarkdownV2 format.

    - Converts headers (###) to bold text
    - Properly escapes special characters
    - Preserves code blocks
    """
    # Split by code blocks to preserve them
    parts = re.split(r"(```[\s\S]*?```|`[^`\n]+`)", text)
    result_parts = []

    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            # Preserve code blocks, escape backticks inside
            inner = part[3:-3]
            newline_idx = inner.find("\n")
            if newline_idx > -1:
                lang = inner[:newline_idx]
                code = inner[newline_idx + 1 :]
                escaped_code = code.replace("\\", "\\\\").replace("`", "\\`")
                result_parts.append(f"```{lang}\n{escaped_code}```")
            else:
                escaped_inner = inner.replace("\\", "\\\\").replace("`", "\\`")
                result_parts.append(f"```{escaped_inner}```")
        elif part.startswith("`") and part.endswith("`"):
            # Preserve inline code
            inner = part[1:-1]
            escaped_inner = inner.replace("\\", "\\\\").replace("`", "\\`")
            result_parts.append(f"`{escaped_inner}`")
        else:
            # Process normal text
            processed = part

            # Convert headers to bold
            processed = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", processed, flags=re.MULTILINE)

            # Escape special characters (but preserve formatting markers we'll add)
            processed = escape_markdown_v2(processed)

            result_parts.append(processed)

    return "".join(result_parts)


def generate_result_key(chat_id: int) -> str:
    """Generate a unique key for storing tool results."""
    import random
    import time

    timestamp = int(time.time() * 1000)
    rand = random.randint(0, 999999)
    return f"{chat_id}:{timestamp}:{rand:06d}"


def add_to_recent_models(recent: list[str], new_model: str, max_count: int = 2) -> list[str]:
    """
    Add a model to the recent models list.

    Most recently used is at index 0. No duplicates.
    """
    filtered = [m for m in recent if m != new_model]
    filtered.insert(0, new_model)
    return filtered[:max_count]


def format_chat_target(
    user_first_name: str | None,
    user_last_name: str | None,
    username: str | None,
    chat_id: int,
) -> str:
    """Format the chat target name for display."""
    name_parts = []
    if user_first_name:
        name_parts.append(user_first_name)
    if user_last_name:
        name_parts.append(user_last_name)

    name = " ".join(name_parts).strip()
    if name:
        return f"{name} ({chat_id})"
    elif username:
        return f"@{username} ({chat_id})"
    else:
        return f"chatId: {chat_id}"


def extract_image_urls(text: str) -> list[str]:
    """Extract image URLs from text."""
    pattern = r'https?://[^\s\n\[\]()<>\"\']+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s\n\[\]()<>\"\']*)?'
    urls = re.findall(pattern, text, re.IGNORECASE)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def extract_local_image_paths(text: str) -> list[str]:
    """Extract local image file paths from text (e.g., from nanobanana output)."""
    # Match paths that look like /path/to/image.jpg
    pattern = r'(/[^\s\n\[\]()<>\"\']+\.(?:jpg|jpeg|png|gif|webp))'
    paths = re.findall(pattern, text, re.IGNORECASE)
    # Filter to only existing files
    return [p for p in paths if os.path.isfile(p)]


async def download_image_from_url(
    url: str, download_dir: str = "/tmp/telegram-claude-bot/images"
) -> str | None:
    """Download an image from URL to local path."""
    os.makedirs(download_dir, exist_ok=True)

    # Headers to avoid 403 Forbidden from many sites
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url.split("/")[0] + "//" + url.split("/")[2] + "/",  # Use site root as referer
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Failed to download image HTTP {resp.status_code}: {url}")
                return None

            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                logger.warning(f"Not an image content-type {content_type}: {url}")
                return None

            # Determine extension from URL
            ext = ".jpg"
            for e in [".png", ".gif", ".webp", ".jpeg"]:
                if e in url.lower():
                    ext = e
                    break

            filename = hashlib.md5(url.encode()).hexdigest()[:12] + ext
            file_path = os.path.join(download_dir, filename)

            with open(file_path, "wb") as f:
                f.write(resp.content)

            logger.info(f"Downloaded image: {url} -> {file_path}")
            return file_path

    except Exception as e:
        logger.warning(f"Failed to download image: {url}: {e}")
        return None

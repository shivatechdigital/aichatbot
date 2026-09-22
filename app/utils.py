"""Shared application helpers."""

import sys

from loguru import logger

from app.config import config


def setup_logger():
    logger.remove()
    logger.add(
        sys.stdout,
        level=config.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
    )
    logger.add(
        config.LOG_FILE,
        level=config.LOG_LEVEL,
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    return logger


def generate_chat_title(first_message: str, max_length: int = 40) -> str:
    title = first_message.strip().splitlines()[0] if first_message.strip() else "New Chat"
    return f"{title[:max_length].rstrip()}..." if len(title) > max_length else title
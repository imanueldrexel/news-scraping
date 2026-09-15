"""
Shared library for Indonesian News Scraper Microservices.
Contains common schemas, Redis client, and configuration.
"""

from shared.config.settings import Settings
from shared.telegram.notifier import TelegramNotifier

__version__ = "1.0.0"
__all__ = ["Settings", "TelegramNotifier"]


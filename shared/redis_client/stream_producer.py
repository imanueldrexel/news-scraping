"""Redis Streams producer for publishing messages."""

import redis
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RedisStreamProducer:
    """
    Producer for publishing messages to Redis Streams.
    Used by services to send messages downstream.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_stream_length: int = 100000,
    ):
        """
        Initialize Redis Stream producer.

        Args:
            redis_url: Redis connection URL
            max_stream_length: Maximum number of messages to keep in stream
        """
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.max_stream_length = max_stream_length

    def publish(
        self,
        stream: str,
        message: Dict[str, Any],
        message_id: str = "*",
    ) -> str:
        """
        Publish a message to a Redis Stream.

        Args:
            stream: Stream name to publish to
            message: Message dictionary to publish
            message_id: Message ID (* for auto-generate)

        Returns:
            Generated message ID
        """
        try:
            # Ensure all values are strings for Redis
            redis_message = {}
            for key, value in message.items():
                if value is None:
                    redis_message[key] = ""
                elif isinstance(value, (datetime,)):
                    redis_message[key] = value.isoformat()
                elif isinstance(value, (list, dict)):
                    import json
                    redis_message[key] = json.dumps(value)
                elif isinstance(value, bool):
                    redis_message[key] = "1" if value else "0"
                else:
                    redis_message[key] = str(value)

            # Add message to stream with approximate trimming
            result = self.redis.xadd(
                stream,
                redis_message,
                id=message_id,
                maxlen=self.max_stream_length,
                approximate=True,
            )

            logger.debug(f"Published message {result} to stream {stream}")
            return result

        except redis.RedisError as e:
            logger.error(f"Failed to publish to stream {stream}: {e}")
            raise

    def publish_batch(
        self,
        stream: str,
        messages: list[Dict[str, Any]],
    ) -> list[str]:
        """
        Publish multiple messages to a Redis Stream using pipeline.

        Args:
            stream: Stream name to publish to
            messages: List of message dictionaries

        Returns:
            List of generated message IDs
        """
        try:
            pipe = self.redis.pipeline()

            for message in messages:
                redis_message = {}
                for key, value in message.items():
                    if value is None:
                        redis_message[key] = ""
                    elif isinstance(value, (datetime,)):
                        redis_message[key] = value.isoformat()
                    elif isinstance(value, (list, dict)):
                        import json
                        redis_message[key] = json.dumps(value)
                    elif isinstance(value, bool):
                        redis_message[key] = "1" if value else "0"
                    else:
                        redis_message[key] = str(value)

                pipe.xadd(
                    stream,
                    redis_message,
                    maxlen=self.max_stream_length,
                    approximate=True,
                )

            results = pipe.execute()
            logger.debug(f"Published {len(results)} messages to stream {stream}")
            return results

        except redis.RedisError as e:
            logger.error(f"Failed to batch publish to stream {stream}: {e}")
            raise

    def get_stream_info(self, stream: str) -> Optional[Dict]:
        """Get information about a stream."""
        try:
            return self.redis.xinfo_stream(stream)
        except redis.ResponseError:
            return None

    def get_stream_length(self, stream: str) -> int:
        """Get the number of messages in a stream."""
        try:
            return self.redis.xlen(stream)
        except redis.ResponseError:
            return 0

    def close(self):
        """Close Redis connection."""
        self.redis.close()

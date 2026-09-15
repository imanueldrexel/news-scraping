"""Redis Streams consumer for processing messages."""

import redis
import logging
import time
from typing import Callable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StreamMessage:
    """Represents a message from Redis Streams."""

    message_id: str
    stream: str
    data: Dict[str, str]


class RedisStreamConsumer:
    """
    Consumer for reading messages from Redis Streams.
    Supports consumer groups for load balancing and fault tolerance.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        group: str = "default-group",
        consumer: str = "consumer-1",
        block_ms: int = 5000,
        batch_size: int = 10,
        max_retries: int = 3,
    ):
        """
        Initialize Redis Stream consumer.

        Args:
            redis_url: Redis connection URL
            group: Consumer group name
            consumer: Consumer name within the group
            block_ms: Milliseconds to block when waiting for messages
            batch_size: Number of messages to fetch per batch
            max_retries: Maximum retry attempts for failed messages
        """
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.group = group
        self.consumer = consumer
        self.block_ms = block_ms
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._running = False

    def ensure_group(self, stream: str, start_id: str = "0") -> bool:
        """
        Ensure consumer group exists for the stream.

        Args:
            stream: Stream name
            start_id: Starting message ID for new group

        Returns:
            True if group was created, False if already exists
        """
        try:
            self.redis.xgroup_create(stream, self.group, id=start_id, mkstream=True)
            logger.info(f"Created consumer group '{self.group}' for stream '{stream}'")
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer group '{self.group}' already exists")
                return False
            raise

    def consume(
        self,
        streams: List[str],
        handler: Callable[[StreamMessage], bool],
        process_pending: bool = True,
    ):
        """
        Start consuming messages from streams.

        Args:
            streams: List of stream names to consume from
            handler: Function to process each message, returns True on success
            process_pending: Whether to process pending messages first
        """
        # Ensure groups exist
        for stream in streams:
            self.ensure_group(stream)

        self._running = True
        logger.info(
            f"Starting consumer '{self.consumer}' in group '{self.group}' "
            f"for streams: {streams}"
        )

        # Process pending messages first
        if process_pending:
            self._process_pending(streams, handler)

        # Main consume loop
        while self._running:
            try:
                self._consume_batch(streams, handler)
            except redis.ConnectionError as e:
                logger.error(f"Redis connection lost: {e}")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error in consume loop: {e}")
                time.sleep(1)

    def _process_pending(
        self,
        streams: List[str],
        handler: Callable[[StreamMessage], bool],
    ):
        """Process pending messages that weren't acknowledged."""
        for stream in streams:
            try:
                # Get pending messages for this consumer
                pending = self.redis.xpending_range(
                    stream,
                    self.group,
                    min="-",
                    max="+",
                    count=100,
                    consumername=self.consumer,
                )

                if not pending:
                    continue

                logger.info(f"Processing {len(pending)} pending messages from {stream}")

                for entry in pending:
                    msg_id = entry["message_id"]
                    delivery_count = entry["times_delivered"]

                    # Skip if too many retries
                    if delivery_count > self.max_retries:
                        logger.warning(
                            f"Message {msg_id} exceeded max retries, acknowledging"
                        )
                        self.redis.xack(stream, self.group, msg_id)
                        continue

                    # Claim and process the message
                    claimed = self.redis.xclaim(
                        stream,
                        self.group,
                        self.consumer,
                        min_idle_time=60000,  # 1 minute idle
                        message_ids=[msg_id],
                    )

                    for msg_id, data in claimed:
                        message = StreamMessage(
                            message_id=msg_id,
                            stream=stream,
                            data=data,
                        )
                        if handler(message):
                            self.redis.xack(stream, self.group, msg_id)

            except Exception as e:
                logger.error(f"Error processing pending messages: {e}")

    def _consume_batch(
        self,
        streams: List[str],
        handler: Callable[[StreamMessage], bool],
    ):
        """Consume a batch of messages from streams."""
        # Build streams dict with > to get new messages
        streams_dict = {stream: ">" for stream in streams}

        result = self.redis.xreadgroup(
            groupname=self.group,
            consumername=self.consumer,
            streams=streams_dict,
            count=self.batch_size,
            block=self.block_ms,
        )

        if not result:
            return

        for stream_name, messages in result:
            for msg_id, data in messages:
                message = StreamMessage(
                    message_id=msg_id,
                    stream=stream_name,
                    data=data,
                )

                try:
                    success = handler(message)
                    if success:
                        self.redis.xack(stream_name, self.group, msg_id)
                        logger.debug(f"Processed and acknowledged {msg_id}")
                    else:
                        logger.warning(f"Handler returned False for {msg_id}")
                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {e}")
                    # Message will be retried as pending

    def consume_one(
        self,
        streams: List[str],
        timeout_ms: int = 5000,
    ) -> Optional[StreamMessage]:
        """
        Consume a single message (useful for testing).

        Args:
            streams: List of stream names
            timeout_ms: Timeout in milliseconds

        Returns:
            StreamMessage or None if timeout
        """
        for stream in streams:
            self.ensure_group(stream)

        streams_dict = {stream: ">" for stream in streams}

        result = self.redis.xreadgroup(
            groupname=self.group,
            consumername=self.consumer,
            streams=streams_dict,
            count=1,
            block=timeout_ms,
        )

        if not result:
            return None

        stream_name, messages = result[0]
        if not messages:
            return None

        msg_id, data = messages[0]
        return StreamMessage(message_id=msg_id, stream=stream_name, data=data)

    def acknowledge(self, stream: str, message_id: str):
        """Manually acknowledge a message."""
        self.redis.xack(stream, self.group, message_id)

    def stop(self):
        """Stop the consumer loop."""
        self._running = False
        logger.info(f"Stopping consumer '{self.consumer}'")

    def get_pending_count(self, stream: str) -> int:
        """Get number of pending messages for this group."""
        try:
            info = self.redis.xpending(stream, self.group)
            return info["pending"] if info else 0
        except redis.ResponseError:
            return 0

    def close(self):
        """Close Redis connection."""
        self.stop()
        self.redis.close()

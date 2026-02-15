"""Slack Socket Mode listener for Mini-Mao activation.

Listens for messages in the #mao channel and routes them to Claude CLI sessions.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient

from .session_manager import SessionManager

logger = logging.getLogger(__name__)


class SlackListener:
    """Slack Socket Mode listener for Mini-Mao sessions.

    Connects to Slack via Socket Mode, listens for messages in the configured
    channel, and routes them to appropriate Claude CLI sessions managed by
    SessionManager.
    """

    def __init__(
        self, session_manager: SessionManager, bot_token: str, app_token: str
    ) -> None:
        """Initialize the Slack listener.

        Args:
            session_manager: SessionManager instance for handling sessions.
            bot_token: Slack bot token (xoxb-...) for API calls.
            app_token: Slack app token (xapp-...) for Socket Mode.
        """
        self.session_manager = session_manager
        self.bot_token = bot_token
        self.app_token = app_token
        self.web_client = AsyncWebClient(token=bot_token)
        self.socket_client = SocketModeClient(
            app_token=app_token, web_client=self.web_client
        )

        # Configuration from environment
        self.mao_channel_name = os.getenv("HERD_MAO_CHANNEL", "mao")
        self.mao_channel_id: str | None = None
        self.authorized_users = self._parse_authorized_users()
        self.bot_user_id: str | None = None

    def _parse_authorized_users(self) -> set[str]:
        """Parse authorized user IDs from environment.

        Returns:
            Set of authorized Slack user IDs.
        """
        users_env = os.getenv("HERD_AUTHORIZED_USERS", "")
        if not users_env:
            return set()

        return {u.strip() for u in users_env.split(",") if u.strip()}

    async def start(self) -> None:
        """Connect to Slack and start listening for messages."""
        # Get bot user ID
        auth_response = await self.web_client.auth_test()
        self.bot_user_id = auth_response["user_id"]

        # Find #mao channel ID
        channels_response = await self.web_client.conversations_list(
            types="public_channel,private_channel"
        )
        for channel in channels_response["channels"]:
            if channel["name"] == self.mao_channel_name:
                self.mao_channel_id = channel["id"]
                break

        if not self.mao_channel_id:
            logger.warning(
                f"Channel #{self.mao_channel_name} not found. "
                "Will not process messages until channel is found."
            )

        # Register message handler
        self.socket_client.socket_mode_request_listeners.append(
            self._handle_socket_event
        )

        # Connect to Socket Mode
        await self.socket_client.connect()
        logger.info(
            f"Connected to Slack Socket Mode. "
            f"Listening for messages in #{self.mao_channel_name}"
        )

    async def stop(self) -> None:
        """Disconnect from Slack gracefully."""
        await self.socket_client.disconnect()
        await self.socket_client.close()
        logger.info("Disconnected from Slack")

    async def _handle_socket_event(
        self, client: SocketModeClient, request: SocketModeRequest
    ) -> None:
        """Handle incoming Socket Mode events.

        Args:
            client: Socket Mode client instance.
            request: Socket Mode request with event data.
        """
        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=request.envelope_id)
        await client.send_socket_mode_response(response)

        # Process event asynchronously (don't block socket listener)
        if request.type == "events_api":
            event = request.payload.get("event", {})
            if event.get("type") == "message":
                asyncio.create_task(self._handle_message(event))

    async def _handle_message(self, event: dict[str, Any]) -> None:
        """Process a message event.

        Args:
            event: Slack message event data.
        """
        try:
            # Extract event data
            channel_id = event.get("channel")
            user_id = event.get("user")
            text = event.get("text", "")
            thread_ts = event.get("thread_ts") or event.get(
                "ts"
            )  # Use ts if not in thread
            message_ts = event.get("ts")

            # Filter: only #mao channel
            if channel_id != self.mao_channel_id:
                return

            # Filter: ignore bot messages (including our own)
            if event.get("bot_id") or user_id == self.bot_user_id:
                return

            # Filter: only authorized users (if configured)
            if self.authorized_users and user_id not in self.authorized_users:
                logger.warning(f"Ignoring message from unauthorized user: {user_id}")
                await self._post_message(
                    channel_id,
                    "Sorry, you are not authorized to activate Mini-Mao.",
                    thread_ts,
                )
                return

            # Get user's display name
            user_info = await self.web_client.users_info(user=user_id)
            user_name = (
                user_info["user"]["profile"].get("display_name")
                or user_info["user"]["name"]
            )

            # Send message to session manager
            response = await self.session_manager.send_message(
                thread_ts, text, user_name
            )

            # Post response back to Slack thread
            await self._post_message(channel_id, response, thread_ts)

        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            # Try to post error to thread
            try:
                if "channel_id" in locals() and "thread_ts" in locals():
                    await self._post_message(
                        channel_id,
                        f"Error processing message: {str(e)}",
                        thread_ts,
                    )
            except Exception:
                pass

    async def _post_message(
        self, channel: str, text: str, thread_ts: str | None = None
    ) -> None:
        """Post a message to Slack.

        Args:
            channel: Channel ID to post to.
            text: Message text.
            thread_ts: Thread timestamp (for replies).
        """
        await self.web_client.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
            username="Mini-Mao",
            icon_emoji=":dragon:",
        )

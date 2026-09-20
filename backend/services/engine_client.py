from __future__ import annotations

import json
import logging
import socket
from threading import Lock, Thread
from typing import Any, Callable, Dict, Optional

from backend.services.protocol_adapter import (
    ProtocolValidationError,
    protocol_adapter,
)

from backend.core.database import get_integration_state
from backend.core.config import settings
from backend.schemas.protocol import HelloMessage
from backend.services.protocol_adapter import protocol_adapter


logger = logging.getLogger(__name__)


class EngineConnectionError(Exception):
    """Connection or transport error with AI Vision Engine."""


class EngineClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

        self._socket: Optional[socket.socket] = None
        self._reader = None
        self._send_lock = Lock()

        self._receiver_thread: Optional[Thread] = None

        self._event_handler: Optional[
            Callable[[Dict[str, Any]], Any]
        ] = None

        self._view_handler: Optional[
            Callable[[Dict[str, Any]], Any]
        ] = None

        self._replay_gap_handler: Optional[
            Callable[[Dict[str, Any]], Any]
        ] = None

        self._control_handler = None
        self.connected = False

        try:
            stored_seq = get_integration_state(
                "engine_last_event_seq",
                "0",
            )
            self.last_event_seq = int(stored_seq)

        except (TypeError, ValueError):
            self.last_event_seq = 0

    def set_control_handler(
        self,
        handler: Callable[
            [Dict[str, Any]],
            Any,
        ],
    ) -> None:
        self._control_handler = handler

    # ==========================================================
    # Connection / Handshake
    # ==========================================================

    def connect(self) -> Dict[str, Any]:
        """
        Connect to engine and perform hello handshake.

        Engine being unavailable is converted into
        EngineConnectionError so FastAPI can continue
        running without the engine.
        """

        try:
            sock = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            )

        except OSError as exc:
            self.connected = False

            raise EngineConnectionError(
                f"Cannot connect to engine "
                f"{self.host}:{self.port}: {exc}"
            ) from exc

        self._socket = sock

        try:
            self._reader = sock.makefile(
                "r",
                encoding="utf-8",
                newline="\n",
            )

            hello = HelloMessage(
                type="hello",
                v=1,
                last_event_seq=self.last_event_seq,
            )

            # Use public compatibility method.
            # Existing tests may monkeypatch send().
            self.send(
                hello.model_dump(
                    exclude_none=True
                )
            )

            # Use public compatibility method.
            # Existing tests may monkeypatch receive().
            response = self.receive()

            if response.get("type") != "hello_ack":
                raise EngineConnectionError(
                    "Engine did not return hello_ack"
                )

            # Validate handshake response first.
            protocol_adapter.validate(
                response
            )

            # Connection timeout is only needed during
            # connection + handshake.
            #
            # After handshake the engine connection is
            # long-lived, so the receiver may wait
            # indefinitely for the next message.
            if self._socket is not None:
                settimeout = getattr(
                    self._socket,
                    "settimeout",
                    None,
                )

                if callable(settimeout):
                    settimeout(None)

            self.connected = True

            return response

        except Exception:
            self.close()
            raise
    # ==========================================================
    # Send
    # ==========================================================

    def send_message(
        self,
        message: Dict[str, Any],
    ) -> None:
        """
        Send one NDJSON message to engine.
        """

        if self._socket is None:
            raise EngineConnectionError(
                "Engine socket is not connected"
            )

        # TEMP DEBUG
        logger.debug(
            "Sending to engine: %r",
            message,
        )

        payload = (
            json.dumps(
                message,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        try:
            with self._send_lock:
                self._socket.sendall(payload)

        except OSError as exc:
            raise EngineConnectionError(
                f"Failed to send message "
                f"to engine: {exc}"
            ) from exc

    def send(
        self,
        message: Dict[str, Any],
    ) -> None:
        """
        Public compatibility wrapper for send_message().
        """

        self.send_message(message)

    # ==========================================================
    # Receive
    # ==========================================================

    def receive_message(
        self,
    ) -> Dict[str, Any]:
        """
        Receive one NDJSON message from engine.
        """

        if self._reader is None:
            raise EngineConnectionError(
                "Engine reader is not connected"
            )

        try:
            line = self._reader.readline()

        except OSError as exc:
            raise EngineConnectionError(
                f"Failed to receive message "
                f"from engine: {exc}"
            ) from exc

        if not line:
            raise EngineConnectionError(
                "Engine connection closed"
            )

        try:
            message = json.loads(line)

        except json.JSONDecodeError as exc:
            raise EngineConnectionError(
                "Engine returned invalid JSON"
            ) from exc

        if not isinstance(message, dict):
            raise EngineConnectionError(
                "Engine message must be a JSON object"
            )

        return message

    def receive(
        self,
    ) -> Dict[str, Any]:
        """
        Public compatibility wrapper for receive_message().
        """

        return self.receive_message()

    # ==========================================================
    # ACK
    # ==========================================================

    def acknowledge(
        self,
        through_seq: int,
    ) -> None:
        """
        ACK all durable events through through_seq.
        """

        self.send(
            {
                "type": "ack",
                "v": 1,
                "through_seq": through_seq,
            }
        )

    # ==========================================================
    # Handlers
    # ==========================================================

    def set_event_handler(
        self,
        handler: Callable[
            [Dict[str, Any]],
            Any,
        ],
    ) -> None:
        self._event_handler = handler

    def set_view_handler(
        self,
        handler: Callable[
            [Dict[str, Any]],
            Any,
        ],
    ) -> None:
        self._view_handler = handler

    def set_replay_gap_handler(
        self,
        handler: Callable[
            [Dict[str, Any]],
            Any,
        ],
    ) -> None:
        self._replay_gap_handler = handler

    # ==========================================================
    # Message Routing
    # ==========================================================

    def handle_message(
        self,
        message: Dict[str, Any],
    ) -> None:
        """
        Validate and route one incoming engine message.
        """

        message_type = message.get("type")
        channel = message.get("channel")

        # ----------------------------------------------------------
        # CONTROL RESPONSE
        # ----------------------------------------------------------
        # Control responses such as ack are not durable events.
        # They must not enter event ingestion.
        if channel == "control":
            validated = protocol_adapter.validate(
                message,
                expected_channel="control",
            )

            logger.debug(
                "Engine control response received: %r",
                validated,
            )

            if self._control_handler is not None:
                self._control_handler(
                    validated
                )

            return
        # ----------------------------------------------------------
        # REPLAY GAP
        # ----------------------------------------------------------
        if message_type == "replay_gap":
            validated = protocol_adapter.validate(
                message,
            )

            if self._replay_gap_handler is not None:
                self._replay_gap_handler(
                    validated
                )

            return

        # ----------------------------------------------------------
        # VIEW
        # ----------------------------------------------------------
        if message_type == "view.frame":
            validated = protocol_adapter.validate(
                message,
                expected_channel="view",
            )

            if self._view_handler is not None:
                self._view_handler(
                    validated
                )

            return

        # ----------------------------------------------------------
        # DURABLE EVENT
        # ---------------------------------------------------------
        validated = protocol_adapter.validate(
            message,
            expected_channel="events",
        )

        seq = validated.get("seq")

        # Duplicate/replayed event yang sudah pernah committed.
        # Jangan process lagi dan jangan ACK ulang.
        if (
            isinstance(seq, int)
            and seq <= self.last_event_seq
        ):
            logger.debug(
                "Ignoring already processed "
                "engine event seq=%s "
                "(last_event_seq=%s)",
                seq,
                self.last_event_seq,
            )

            # Event tidak diproses ulang,
            # tetapi ACK checkpoint yang sudah committed.
            self.acknowledge(
                self.last_event_seq
            )

            return

        # Handler melakukan persistence terlebih dahulu.
        if self._event_handler is not None:
            self._event_handler(
                validated
            )

        # Checkpoint + ACK hanya setelah handler berhasil.
        if isinstance(seq, int):
            self.last_event_seq = seq

            self.acknowledge(
                seq
            )


    # ==========================================================
    # Receiver Thread
    # ==========================================================

    def receive_loop(self) -> None:
        """
        Continuously receive messages from engine.

        Any transport or processing failure closes
        the connection. UnACKed durable events can
        then be replayed after reconnect.
        """

        while self.connected:
            try:
                message = self.receive()

                logger.debug(
                    "Engine message received: "
                    "type=%s seq=%s channel=%s",
                    message.get("type"),
                    message.get("seq"),
                    message.get("channel"),
                )

                self.handle_message(
                    message
                )

            except ProtocolValidationError as exc:
                logger.error(
                    "Protocol validation failed. issues=%s",
                    [
                        {
                            "path": getattr(
                                issue,
                                "path",
                                None,
                            ),
                            "message": getattr(
                                issue,
                                "message",
                                str(issue),
                            ),
                        }
                        for issue in exc.issues
                    ],
                )

                logger.error(
                    "Rejected engine message: %r",
                    locals().get(
                        "message",
                        None,
                    ),
                )

                self.close()
                break

            except Exception:
                logger.exception(
                    "Engine receiver stopped because "
                    "message processing failed"
                )

                self.close()
                break


    def start_receiver(self) -> None:
        """
        Start background engine receiver thread.
        """

        if not self.connected:
            raise EngineConnectionError(
                "Cannot start receiver while disconnected"
            )

        if (
            self._receiver_thread is not None
            and self._receiver_thread.is_alive()
        ):
            return

        self._receiver_thread = Thread(
            target=self.receive_loop,
            daemon=True,
            name="engine-receiver",
        )

        self._receiver_thread.start()

    # ==========================================================
    # Close
    # ==========================================================

    def close(self) -> None:
        """
        Close engine connection safely.

        Compatible with both real sockets and simplified
        fake sockets used by unit tests.
        """

        self.connected = False

        reader = self._reader
        sock = self._socket

        self._reader = None
        self._socket = None

        if reader is not None:
            try:
                reader.close()
            except (OSError, AttributeError):
                pass

        if sock is not None:
            # Some FakeSocket implementations used by tests
            # do not implement shutdown().
            shutdown = getattr(
                sock,
                "shutdown",
                None,
            )

            if callable(shutdown):
                try:
                    shutdown(
                        socket.SHUT_RDWR
                    )
                except OSError:
                    pass

            close = getattr(
                sock,
                "close",
                None,
            )

            if callable(close):
                try:
                    close()
                except OSError:
                    pass


engine_client = EngineClient(host=settings.engine_host, port=settings.engine_port)

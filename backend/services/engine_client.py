from __future__ import annotations

import json
import logging
import socket
from threading import Lock, Thread
from typing import Any, Callable, Dict, Optional

from backend.core.config import settings
from backend.core.database import (
    get_integration_state,
    last_seq_key,
    save_dead_letter,
    set_integration_state,
)
from backend.schemas.protocol import HelloMessage
from backend.services.protocol_adapter import ProtocolValidationError, protocol_adapter

logger = logging.getLogger(__name__)

# How many times the same missing seq may trigger a reconnect-and-replay
# before the backend accepts the hole and records it.
MAX_GAP_RETRIES = 3


class EngineConnectionError(Exception):
    """Connection or transport error with AI Vision Engine."""


class SequenceGapError(EngineConnectionError):
    """A durable event arrived with seq > last + 1 and no replay_gap announced it."""


class OutboxChangedError(EngineConnectionError):
    """hello_ack revealed a different engine outbox; reconnect with its own cursor."""


class EngineClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

        self._socket: Optional[socket.socket] = None
        self._reader = None
        self._send_lock = Lock()
        self._receiver_thread: Optional[Thread] = None

        self._event_handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._view_handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._replay_gap_handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._control_handler: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._outbox_changed_handler: Optional[Callable[[str, str], Any]] = None
        self.connected = False

        # The seq cursor belongs to one engine outbox. Remember which.
        self.outbox_id = get_integration_state("engine_outbox_id", "")
        self.last_event_seq = self._stored_seq(self.outbox_id)
        self._gap_allowed_to: Optional[int] = None
        self._gap_retries: Dict[int, int] = {}

    @staticmethod
    def _stored_seq(outbox_id: str) -> int:
        try:
            return int(get_integration_state(last_seq_key(outbox_id), "0"))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------
    def set_control_handler(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._control_handler = handler

    def set_event_handler(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._event_handler = handler

    def set_view_handler(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._view_handler = handler

    def set_replay_gap_handler(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._replay_gap_handler = handler

    def set_outbox_changed_handler(self, handler: Callable[[str, str], Any]) -> None:
        self._outbox_changed_handler = handler

    # ------------------------------------------------------------------
    # connection / handshake
    # ------------------------------------------------------------------
    def connect(self) -> Dict[str, Any]:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            self.connected = False
            raise EngineConnectionError(
                f"Cannot connect to engine {self.host}:{self.port}: {exc}"
            ) from exc

        self._socket = sock
        try:
            self._reader = sock.makefile("r", encoding="utf-8", newline="\n")
            hello = HelloMessage(type="hello", v=1, last_event_seq=self.last_event_seq)
            self.send(hello.model_dump(exclude_none=True))

            response = self.receive()
            if response.get("type") != "hello_ack":
                raise EngineConnectionError("Engine did not return hello_ack")
            protocol_adapter.validate(response)

            engine_outbox = str(response.get("outbox_id") or "")
            if engine_outbox and engine_outbox != self.outbox_id:
                previous = self.outbox_id
                self.outbox_id = engine_outbox
                set_integration_state("engine_outbox_id", engine_outbox)
                self.last_event_seq = self._stored_seq(engine_outbox)
                self._gap_retries.clear()
                if previous:
                    # Numbering restarted. The hello we sent carried the OLD
                    # cursor, so the engine would skip everything up to it.
                    # Reconnect immediately with the cursor of THIS outbox.
                    logger.warning(
                        "Engine outbox changed (%s -> %s); reconnecting from seq %s",
                        previous, engine_outbox, self.last_event_seq,
                    )
                    if self._outbox_changed_handler is not None:
                        self._outbox_changed_handler(previous, engine_outbox)
                    raise OutboxChangedError("engine outbox changed")
                # First time we learn the id (fresh or pre-upgrade backend):
                # adopt it and carry the legacy cursor over.
                legacy = self._stored_seq("")
                if legacy and not self.last_event_seq:
                    self.last_event_seq = legacy
                    set_integration_state(last_seq_key(engine_outbox), str(legacy))

            self._gap_allowed_to = None
            if self._socket is not None:
                self._socket.settimeout(None)
            self.connected = True
            return response
        except Exception:
            self.close()
            raise

    # ------------------------------------------------------------------
    # send / receive
    # ------------------------------------------------------------------
    def send_message(self, message: Dict[str, Any]) -> None:
        sock = self._socket
        if sock is None:
            raise EngineConnectionError("Engine socket is not connected")
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._send_lock:
                sock.sendall(payload)
        except OSError as exc:
            raise EngineConnectionError(f"Failed to send message to engine: {exc}") from exc

    def send(self, message: Dict[str, Any]) -> None:
        self.send_message(message)

    def receive_message(self) -> Dict[str, Any]:
        reader = self._reader
        if reader is None:
            raise EngineConnectionError("Engine reader is not connected")
        try:
            line = reader.readline()
        except (OSError, ValueError) as exc:
            raise EngineConnectionError(f"Failed to receive message from engine: {exc}") from exc
        if not line:
            raise EngineConnectionError("Engine connection closed")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EngineConnectionError("Engine returned invalid JSON") from exc
        if not isinstance(message, dict):
            raise EngineConnectionError("Engine message must be a JSON object")
        return message

    def receive(self) -> Dict[str, Any]:
        return self.receive_message()

    def acknowledge(self, through_seq: int) -> None:
        self.send({"type": "ack", "v": 1, "through_seq": through_seq})

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------
    def handle_message(self, message: Dict[str, Any]) -> None:
        message_type = message.get("type")
        channel = message.get("channel")

        if message_type == "replay_gap":
            validated = protocol_adapter.validate(message)
            to_seq = validated.get("to_seq")
            if isinstance(to_seq, int):
                self._gap_allowed_to = to_seq
            logger.error(
                "Engine cannot replay seq %s..%s: data in that range is lost",
                validated.get("from_seq"), to_seq,
            )
            if self._replay_gap_handler is not None:
                self._replay_gap_handler(validated)
            return

        if channel == "control" or message_type in {"ack", "enroll_result", "hello_ack"}:
            try:
                validated = protocol_adapter.validate(message, expected_channel="control")
                if self._control_handler is not None:
                    self._control_handler(validated)
            except Exception:  # noqa: BLE001 — a control reply must never kill the stream
                logger.exception("Control message handling failed: %r", message)
            return

        if message_type == "view.frame" or channel == "view":
            try:
                validated = protocol_adapter.validate(message, expected_channel="view")
                if self._view_handler is not None:
                    self._view_handler(validated)
            except Exception:  # noqa: BLE001 — view is best-effort by contract
                logger.warning("Dropping view frame: %s", message.get("camera_id"), exc_info=True)
            return

        self._handle_durable(message)

    def _handle_durable(self, message: Dict[str, Any]) -> None:
        seq = message.get("seq")
        if not isinstance(seq, int):
            save_dead_letter(self.outbox_id, None, "durable event without integer seq", message)
            logger.error("Dead-lettered event without seq: %r", message.get("type"))
            return

        if seq <= self.last_event_seq:
            # Already committed (replay overlap). Re-ACK the checkpoint only.
            self.acknowledge(self.last_event_seq)
            return

        expected = self.last_event_seq + 1
        if self.last_event_seq > 0 and seq != expected:
            if self._gap_allowed_to is not None and seq <= self._gap_allowed_to:
                pass  # announced by replay_gap
            else:
                retries = self._gap_retries.get(expected, 0) + 1
                self._gap_retries[expected] = retries
                if retries <= MAX_GAP_RETRIES:
                    raise SequenceGapError(
                        f"expected seq {expected}, got {seq}; reconnecting to replay "
                        f"(attempt {retries}/{MAX_GAP_RETRIES})"
                    )
                logger.error(
                    "seq %s..%s never arrived after %s replays; accepting the hole",
                    expected, seq - 1, MAX_GAP_RETRIES,
                )
                set_integration_state(
                    f"engine_seq_hole:{self.outbox_id}:{expected}", str(seq - 1)
                )

        try:
            validated = protocol_adapter.validate(message, expected_channel="events")
            if self._event_handler is not None:
                self._event_handler(validated)
        except Exception as exc:  # noqa: BLE001
            # Poison message: park it, move on. Disconnecting would replay the
            # same message forever and stall every event behind it.
            detail = repr(exc)
            if isinstance(exc, ProtocolValidationError):
                detail = "; ".join(
                    f"{getattr(i, 'path', '')}: {getattr(i, 'message', i)}" for i in exc.issues
                ) or detail
            save_dead_letter(self.outbox_id, seq, detail, message)
            logger.error("Dead-lettered seq %s (%s): %s", seq, message.get("type"), detail)

        self.last_event_seq = seq
        self._gap_retries.pop(seq, None)
        if self._gap_allowed_to is not None and seq >= self._gap_allowed_to:
            self._gap_allowed_to = None
        self.acknowledge(seq)

    # ------------------------------------------------------------------
    # receiver thread
    # ------------------------------------------------------------------
    def receive_loop(self) -> None:
        while self.connected:
            try:
                message = self.receive()
                self.handle_message(message)
            except SequenceGapError as exc:
                logger.warning("%s", exc)
                self.close()
                break
            except EngineConnectionError as exc:
                if self.connected:
                    logger.warning("Engine connection lost: %s", exc)
                self.close()
                break
            except Exception:  # noqa: BLE001
                logger.exception("Engine receiver stopped unexpectedly")
                self.close()
                break

    def start_receiver(self) -> None:
        if not self.connected:
            raise EngineConnectionError("Cannot start receiver while disconnected")
        if self._receiver_thread is not None and self._receiver_thread.is_alive():
            return
        self._receiver_thread = Thread(target=self.receive_loop, daemon=True, name="engine-receiver")
        self._receiver_thread.start()

    # ------------------------------------------------------------------
    # close
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Safe from any thread.

        The socket is shut down BEFORE the buffered reader is closed: closing a
        reader while another thread is blocked in its `readline()` waits on the
        buffer lock forever (backend shutdown used to hang here).
        """
        self.connected = False
        reader, sock = self._reader, self._socket
        self._reader = None
        self._socket = None

        if sock is not None:
            shutdown = getattr(sock, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if reader is not None:
            try:
                reader.close()
            except (OSError, AttributeError, ValueError):
                pass
        if sock is not None:
            close = getattr(sock, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass


engine_client = EngineClient(host=settings.engine_host, port=settings.engine_port)

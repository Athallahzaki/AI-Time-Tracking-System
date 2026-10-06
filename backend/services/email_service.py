from __future__ import annotations

import logging
import queue
import smtplib
import ssl
import threading
from email.message import EmailMessage
from typing import Any, Dict, Optional

from backend.core.config import settings


logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


class EmailService:
    def __init__(self) -> None:
        self._queue: queue.Queue[
            Optional[Dict[str, Any]]
        ] = queue.Queue(maxsize=100)

        self._stop_event = threading.Event()
        self._thread: Optional[
            threading.Thread
        ] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not settings.smtp_enabled:
            logger.info(
                "SMTP email notifications disabled"
            )
            return

        if self._thread is not None:
            return

        try:
            self._validate_configuration()
        except EmailConfigurationError as exc:
            logger.warning(
                "SMTP enabled but configuration is invalid: %s",
                exc,
            )
            return

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._worker,
            name="smtp-email-worker",
            daemon=True,
        )

        self._thread.start()

        logger.info(
            "SMTP email worker started"
        )

    def stop(self) -> None:
        self._stop_event.set()

        thread = self._thread

        if thread is None:
            return

        thread.join(timeout=3.0)
        self._thread = None

        logger.info(
            "SMTP email worker stopped"
        )

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        try:
            self._validate_configuration()
            return True
        except EmailConfigurationError:
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": settings.smtp_enabled,
            "configured": self.is_configured(),
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "security": settings.smtp_security,
            "from": (
                settings.smtp_from
                or settings.smtp_username
                or None
            ),
            "recipients": settings.smtp_to,
            "username_configured": bool(
                settings.smtp_username
            ),
            "password_configured": bool(
                settings.smtp_password
            ),
            "worker_running": (
                self._thread is not None
                and self._thread.is_alive()
            ),
        }

    # ------------------------------------------------------------------
    # automatic notification email
    # ------------------------------------------------------------------

    def enqueue_notification(
        self,
        notification: Dict[str, Any],
    ) -> bool:
        if not settings.smtp_enabled:
            return False

        if (
            self._thread is None
            or not self._thread.is_alive()
        ):
            logger.warning(
                "SMTP notification skipped because "
                "email worker is not running"
            )
            return False

        try:
            self._queue.put_nowait(
                dict(notification)
            )
        except queue.Full:
            logger.error(
                "SMTP queue is full; email notification dropped"
            )
            return False

        return True

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                notification = self._queue.get(
                    timeout=0.5
                )
            except queue.Empty:
                continue

            if notification is None:
                continue

            try:
                self.send_notification_now(
                    notification
                )
            except (
                EmailConfigurationError,
                EmailDeliveryError,
            ) as exc:
                # Email failure must never kill event ingestion.
                logger.error(
                    "Failed to send notification email: %s",
                    exc,
                )
            except Exception:
                logger.exception(
                    "Unexpected SMTP worker failure"
                )
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    def send_notification_now(
        self,
        notification: Dict[str, Any],
    ) -> None:
        person_id = notification.get(
            "person_id",
            "unknown",
        )

        subject = (
            "[AI Time Tracking] "
            "Batas jatah waktu terlampaui"
        )

        message = (
            f"{notification.get('title', 'Notification')}\n\n"
            f"Person ID: {person_id}\n"
            f"Pesan: {notification.get('message', '')}\n"
            f"Jenis: {notification.get('type', '')}\n"
            f"Event time: {notification.get('event_at', '')}\n\n"
            "Pesan ini dikirim otomatis oleh "
            "AI Time Tracking System."
        )

        self._send(
            subject=subject,
            body=message,
        )

    def send_test_email(self) -> None:
        self._send(
            subject=(
                "[AI Time Tracking] SMTP Test"
            ),
            body=(
                "SMTP berhasil terhubung.\n\n"
                "Email ini dikirim dari halaman "
                "pengaturan AI Time Tracking System."
            ),
        )

    def _send(
        self,
        subject: str,
        body: str,
    ) -> None:
        self._validate_configuration()

        sender = (
            settings.smtp_from
            or settings.smtp_username
        )

        recipients = list(settings.smtp_to)

        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = sender
        email["To"] = ", ".join(recipients)
        email.set_content(body)

        context = ssl.create_default_context()

        try:
            if settings.smtp_security == "ssl":
                with smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                    context=context,
                ) as smtp:
                    if settings.smtp_username:
                        smtp.login(
                            settings.smtp_username,
                            settings.smtp_password,
                        )

                    smtp.send_message(email)

            else:
                with smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                ) as smtp:
                    smtp.ehlo()

                    if settings.smtp_security == "starttls":
                        smtp.starttls(context=context)
                        smtp.ehlo()

                    if settings.smtp_username:
                        smtp.login(
                            settings.smtp_username,
                            settings.smtp_password,
                        )

                    smtp.send_message(email)

        except (
            smtplib.SMTPException,
            OSError,
        ) as exc:
            logger.exception(
                "SMTP send failed"
            )

            raise EmailDeliveryError(
                str(exc)
            ) from exc

    def _login_if_required(
        self,
        smtp: smtplib.SMTP,
    ) -> None:
        if settings.smtp_username:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password,
            )

    def _validate_configuration(
        self,
    ) -> None:
        if not settings.smtp_host:
            raise EmailConfigurationError(
                "SMTP_HOST is required"
            )

        if settings.smtp_security not in {
            "starttls",
            "ssl",
            "none",
        }:
            raise EmailConfigurationError(
                "SMTP_SECURITY must be "
                "starttls, ssl, or none"
            )

        if bool(settings.smtp_username) != bool(
            settings.smtp_password
        ):
            raise EmailConfigurationError(
                "SMTP_USERNAME and SMTP_PASSWORD "
                "must both be provided"
            )

        sender = (
            settings.smtp_from
            or settings.smtp_username
        )

        if not sender:
            raise EmailConfigurationError(
                "SMTP_FROM or SMTP_USERNAME "
                "is required"
            )

        if not settings.smtp_to:
            raise EmailConfigurationError(
                "SMTP_TO must contain at least "
                "one recipient"
            )


email_service = EmailService()
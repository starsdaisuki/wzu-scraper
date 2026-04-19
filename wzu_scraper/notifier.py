from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class Notifier:
    def notify(self, title: str, message: str) -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def notify(self, title: str, message: str) -> None:
        print(f"\n[通知] {title}: {message}")


class BellNotifier(Notifier):
    def notify(self, title: str, message: str) -> None:
        print("\a", end="", flush=True)


class MacOSNotifier(Notifier):
    def notify(self, title: str, message: str) -> None:
        script = (
            f'display notification "{_escape_applescript(message)}" '
            f'with title "{_escape_applescript(title)}"'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            logger.warning(
                "Failed to send macOS notification", extra={"error": str(exc)}
            )


@dataclass
class TelegramNotifier(Notifier):
    token: str
    chat_id: str
    client: httpx.Client | None = None

    def notify(self, title: str, message: str) -> None:
        payload = {"chat_id": self.chat_id, "text": f"{title}\n{message}"}
        own_client = self.client is None
        client = self.client or httpx.Client(timeout=10.0)
        try:
            resp = client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data=payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Telegram notification failed",
                    extra={"status": resp.status_code, "body": resp.text[:200]},
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Telegram notification failed",
                extra={"error": str(exc)},
            )
        finally:
            if own_client:
                client.close()


@dataclass
class FanoutNotifier(Notifier):
    notifiers: list[Notifier]

    def notify(self, title: str, message: str) -> None:
        for notifier in self.notifiers:
            notifier.notify(title, message)


def build_notifier(
    *,
    console: bool = False,
    bell: bool = False,
    desktop: bool = False,
    telegram: bool = False,
) -> Notifier | None:
    notifiers: list[Notifier] = []
    if console:
        notifiers.append(ConsoleNotifier())
    if bell:
        notifiers.append(BellNotifier())
    if desktop:
        notifiers.append(MacOSNotifier())
    if telegram:
        token = os.environ.get("WZU_TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("WZU_TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            notifiers.append(TelegramNotifier(token=token, chat_id=chat_id))
        else:
            logger.warning(
                "Telegram notifier requested but env vars are missing",
                extra={
                    "has_token": bool(token),
                    "has_chat_id": bool(chat_id),
                },
            )
    if not notifiers:
        return None
    if len(notifiers) == 1:
        return notifiers[0]
    return FanoutNotifier(notifiers=notifiers)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')

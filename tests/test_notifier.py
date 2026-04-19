from __future__ import annotations

import httpx

from wzu_scraper.notifier import BellNotifier, FanoutNotifier, TelegramNotifier


def test_fanout_notifier_notifies_all_backends():
    events: list[str] = []

    class RecordingNotifier:
        def __init__(self, name: str) -> None:
            self.name = name

        def notify(self, title: str, message: str) -> None:
            events.append(f"{self.name}:{title}:{message}")

    notifier = FanoutNotifier(
        notifiers=[RecordingNotifier("a"), RecordingNotifier("b")]
    )

    notifier.notify("课程有空位", "高级语言程序设计 还有 1 个名额")

    assert events == [
        "a:课程有空位:高级语言程序设计 还有 1 个名额",
        "b:课程有空位:高级语言程序设计 还有 1 个名额",
    ]


def test_bell_notifier_writes_terminal_bell(capsys):
    BellNotifier().notify("title", "message")

    assert capsys.readouterr().out == "\a"


def test_telegram_notifier_posts_expected_payload():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    notifier = TelegramNotifier(token="token123", chat_id="chat456", client=client)

    notifier.notify("WZU 课程有空位", "高级语言程序设计 还有 1 个名额")

    assert sent["url"] == "https://api.telegram.org/bottoken123/sendMessage"
    assert "chat_id=chat456" in sent["body"]
    assert "WZU+%E8%AF%BE%E7%A8%8B%E6%9C%89%E7%A9%BA%E4%BD%8D" in sent["body"]
    client.close()

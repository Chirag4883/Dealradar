import hashlib
import re
from urllib.parse import urlsplit
from .http import APIError, secret


def escape(text):
    # Common denominator: Telegram MarkdownV2 + Discord Markdown.
    text = str(text).replace("@", "＠")
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])", r"\\\1", text)


def render(offer, watch, channel):
    bold = "*" if channel == "telegram" else "**"
    lines = [bold + "DealRadar" + bold, escape(offer.title[:300]),
             escape(f"{offer.currency} {offer.price:.2f} | target ≤ {watch['max_price']}"),
             "Seller: " + escape(offer.seller[:100]), escape(offer.details[:400])]
    if offer.url:
        # Encode delimiters so untrusted product URLs cannot escape the Markdown link.
        url = offer.url.replace("\\", "%5C").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
        if len(url) > 700:
            raise APIError("offer URL too long")
        lines.append("[View offer](" + url + ")")
    return "\n".join(lines)


class Notifier:
    def __init__(self, http, channel):
        self.http, self.channel = http, channel
        if channel == "telegram":
            token, chat = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
                raise APIError("invalid Telegram credential")
            self.url = "https://api.telegram.org/bot" + token + "/sendMessage"
            self.chat = chat
            target = token + ":" + chat
        elif channel == "discord":
            self.url = secret("DISCORD_WEBHOOK_URL")
            p = urlsplit(self.url)
            if p.scheme != "https" or p.hostname != "discord.com" or p.username or p.password or p.port or p.query or p.fragment or not re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9_-]+", p.path):
                raise APIError("invalid Discord webhook URL")
            target = self.url
        else:
            raise APIError("unknown notification channel")
        self.destination = hashlib.sha256(target.encode()).hexdigest()

    def send(self, text):
        # No retry after ambiguous POST failure: delivery may already have happened.
        if self.channel == "telegram":
            result = self.http.request("POST", self.url, retry=False, data={"chat_id": self.chat, "text": text,
                "parse_mode": "MarkdownV2", "link_preview_options": {"is_disabled": True}})
            if result.get("ok") is not True:
                raise APIError("Telegram delivery not confirmed")
        else:
            result = self.http.request("POST", self.url, params={"wait": "true"}, retry=False,
                data={"content": text, "allowed_mentions": {"parse": []}})
            if not result.get("id"):
                raise APIError("Discord delivery not confirmed")

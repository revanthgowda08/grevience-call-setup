"""Telephony provider interface.

The engine only talks to `Provider`. Swap `ConsoleSimulator` for a real
cloud-telephony + WhatsApp/SMS vendor by filling in `VendorProvider`.
Answers can also arrive later through the /webhook/answer endpoint.
"""
import random
from dataclasses import dataclass
from typing import Optional

CALL_COST = 1.2      # rupees per voice attempt (planning estimate)
MESSAGE_COST = 0.25  # rupees per WhatsApp/SMS


@dataclass
class Reply:
    """Outcome of one attempt. `text` is None when the citizen did not respond."""
    text: Optional[str] = None
    cost: float = 0.0


class Provider:
    def place_call(self, ticket, script) -> Reply:
        raise NotImplementedError

    def send_message(self, ticket, text) -> Reply:
        raise NotImplementedError


class ConsoleSimulator(Provider):
    """Prints the script and fakes a citizen's reply, deterministically per ticket and attempt."""

    ANSWERS = {
        "yes": {"en": ["Yes, it is fixed", "done", "1"], "hi": ["हाँ ठीक हो गया", "haan theek hai", "1"], "kn": ["ಹೌದು ಆಯ್ತು", "howdu", "1"]},
        "no": {"en": ["No, still the same", "not fixed", "2"], "hi": ["नहीं, अभी भी वैसा ही है", "nahi hua", "2"], "kn": ["ಇಲ್ಲ ಇನ್ನೂ ಆಗಿಲ್ಲ", "illa", "2"]},
        "partly": {"en": ["partly fixed", "3"], "hi": ["थोड़ा ठीक हुआ", "3"], "kn": ["ಸ್ವಲ್ಪ ಆಗಿದೆ", "3"]},
        "unclear": {"en": ["hello? who is this", "umm"], "hi": ["कौन बोल रहा है", "अच्छा"], "kn": ["ಯಾರು ಮಾತಾಡ್ತಿರೋದು", "ಹಾಂ"]},
    }

    def __init__(self, voice_pickup=0.55, message_reply=0.3, mix=None, verbose=False):
        self.voice_pickup = voice_pickup
        self.message_reply = message_reply
        self.mix = mix or {"yes": 0.55, "no": 0.25, "partly": 0.10, "unclear": 0.10}
        self.verbose = verbose
        self.calls = {}

    def _reply(self, ticket, channel, text_out, pickup, cost):
        n = self.calls[ticket["id"]] = self.calls.get(ticket["id"], 0) + 1
        rng = random.Random(f'{ticket["id"]}|{n}|{channel}')
        if self.verbose:
            print(f'[{channel}] -> {ticket["id"]}: {text_out}')
        if rng.random() > pickup:
            return Reply(None, cost)
        label = rng.choices(list(self.mix), weights=list(self.mix.values()))[0]
        lang = ticket["language"] if ticket["language"] in ("kn", "hi", "en") else "en"
        return Reply(rng.choice(self.ANSWERS[label][lang]), cost)

    def place_call(self, ticket, script):
        return self._reply(ticket, "voice", script, self.voice_pickup, CALL_COST)

    def send_message(self, ticket, text):
        return self._reply(ticket, "message", text, self.message_reply, MESSAGE_COST)


class VendorProvider(Provider):
    """Template for a real vendor. Fill in the HTTP calls; have the vendor's
    speech-to-text result POST to /webhook/answer so the engine records it."""

    def __init__(self, api_key, caller_id, callback_url):
        self.api_key, self.caller_id, self.callback_url = api_key, caller_id, callback_url

    def place_call(self, ticket, script):
        raise NotImplementedError("Call the vendor's outbound-call API with `script` (TTS) and DTMF capture")

    def send_message(self, ticket, text):
        raise NotImplementedError("Call the vendor's WhatsApp/SMS API with one-tap reply buttons")

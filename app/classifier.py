"""Turn a citizen's answer (speech transcript or keypad digit) into one label.

Labels: yes | no | partly | unclear. Rules cover Kannada, Hindi and English
(script and romanised). A production LLM classifier must return the same labels;
this one stays as the fallback.
"""
import string

YES, NO, PARTLY, UNCLEAR = "yes", "no", "partly", "unclear"

KEYPAD = {"1": YES, "2": NO, "3": PARTLY}

# Single ASCII words match whole tokens; entries with spaces or non-ASCII match as substrings.
PARTLY_WORDS = [
    "partly", "partially", "partial", "half", "some", "somewhat", "a bit", "little",
    "kuch", "thoda", "aadha", "adhura", "adhoora", "ardha", "swalpa", "svalpa",
    "आंशिक", "थोड़ा", "थोडा", "आधा", "अधूरा", "कुछ",
    "ಭಾಗಶಃ", "ಸ್ವಲ್ಪ", "ಅರ್ಧ", "ಅರೆ",
]
NO_WORDS = [
    "no", "not", "nope", "never", "still", "same", "pending", "nahi", "nahin", "nai", "illa", "agilla", "aagilla",
    "innu", "abhi bhi", "as it is", "not fixed",
    "नहीं", "नही", "अभी भी", "अब भी", "जस का तस", "वैसा ही",
    "ಇಲ್ಲ", "ಆಗಿಲ್ಲ", "ಇನ್ನೂ", "ಹಾಗೆಯೇ", "ಬಗೆಹರಿದಿಲ್ಲ",
]
YES_WORDS = [
    "yes", "yeah", "yep", "fixed", "done", "resolved", "solved", "ok", "okay", "haan", "han", "ha", "hanji",
    "theek", "thik", "ho gaya", "howdu", "houdu", "aaytu", "ayitu", "sari", "chennagide",
    "हाँ", "हां", "जी हाँ", "ठीक", "हो गया", "सही",
    "ಹೌದು", "ಆಯ್ತು", "ಆಯಿತು", "ಸರಿ", "ಬಗೆಹರಿದಿದೆ", "ಚೆನ್ನಾಗಿದೆ",
]
# "No problem now" is a yes even though it contains "no".
POSITIVE_NEGATIONS = ["no problem", "no issue", "koi problem nahi", "koi dikkat nahi", "समस्या नहीं", "ಸಮಸ್ಯೆ ಇಲ್ಲ"]


def _hit(words, text, tokens):
    for w in words:
        if " " in w or not w.isascii():
            if w in text:
                return True
        elif w in tokens:
            return True
    return False


def classify(text):
    """Return yes / no / partly / unclear for a citizen's reply."""
    if text is None:
        return UNCLEAR
    text = text.strip().lower()
    if text in KEYPAD:
        return KEYPAD[text]
    if not text:
        return UNCLEAR
    punct = string.punctuation + "।॥…"
    tokens = {t.strip(punct) for t in text.split()}
    if _hit(PARTLY_WORDS, text, tokens):
        return PARTLY
    if _hit(POSITIVE_NEGATIONS, text, tokens) and not _hit(["still", "abhi bhi", "ಇನ್ನೂ"], text, tokens):
        return YES
    if _hit(NO_WORDS, text, tokens):
        return NO
    if _hit(YES_WORDS, text, tokens):
        return YES
    return UNCLEAR

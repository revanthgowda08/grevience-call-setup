"""Call and message scripts in Kannada, Hindi and English."""

LANGUAGES = ("kn", "hi", "en")

CALL_SCRIPTS = {
    "en": (
        "Hello, this is a call from Praja Seva. This call is only to verify your own complaint, "
        "and is made with your consent. Complaint number {ticket_id}: {issue}. "
        "Has this problem actually been fixed? Press 1 for yes, 2 for no, 3 for partly fixed."
    ),
    "hi": (
        "नमस्ते, यह प्रजा सेवा की ओर से कॉल है। यह कॉल केवल आपकी अपनी शिकायत के सत्यापन के लिए है। "
        "शिकायत संख्या {ticket_id}: {issue}। क्या यह समस्या सच में ठीक हो गई है? "
        "हाँ के लिए 1, नहीं के लिए 2, आंशिक रूप से ठीक के लिए 3 दबाएँ।"
    ),
    "kn": (
        "ನಮಸ್ಕಾರ, ಇದು ಪ್ರಜಾ ಸೇವಾ ಕಡೆಯಿಂದ ಕರೆ. ನಿಮ್ಮ ಸ್ವಂತ ದೂರಿನ ಪರಿಶೀಲನೆಗಾಗಿ ಮಾತ್ರ ಈ ಕರೆ ಮಾಡಲಾಗಿದೆ. "
        "ದೂರು ಸಂಖ್ಯೆ {ticket_id}: {issue}. ಈ ಸಮಸ್ಯೆ ನಿಜವಾಗಿಯೂ ಬಗೆಹರಿದಿದೆಯೇ? "
        "ಹೌದು ಎಂದರೆ 1, ಇಲ್ಲ ಎಂದರೆ 2, ಭಾಗಶಃ ಎಂದರೆ 3 ಒತ್ತಿ."
    ),
}

MESSAGE_TEXTS = {
    "en": "Praja Seva: Your complaint {ticket_id} ({issue}) was marked resolved. Is it actually fixed? Reply 1 = yes, 2 = no, 3 = partly.",
    "hi": "प्रजा सेवा: आपकी शिकायत {ticket_id} ({issue}) हल बताई गई है। क्या सच में ठीक हुई? उत्तर दें 1 = हाँ, 2 = नहीं, 3 = आंशिक।",
    "kn": "ಪ್ರಜಾ ಸೇವಾ: ನಿಮ್ಮ ದೂರು {ticket_id} ({issue}) ಬಗೆಹರಿದಿದೆ ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ. ನಿಜವಾಗಿಯೂ ಸರಿಯಾಗಿದೆಯೇ? 1 = ಹೌದು, 2 = ಇಲ್ಲ, 3 = ಭಾಗಶಃ.",
}


def _lang(language):
    return language if language in LANGUAGES else "en"


def call_script(ticket, issue=None):
    return CALL_SCRIPTS[_lang(ticket["language"])].format(ticket_id=ticket["id"], issue=issue or ticket["category"])


def message_text(ticket, issue=None):
    return MESSAGE_TEXTS[_lang(ticket["language"])].format(ticket_id=ticket["id"], issue=issue or ticket["category"])

"""Generate SYNTHETIC training utterances for our intent classifier.

Run:  python -m agent.nlu.gen_data      -> writes agent/nlu/data/utterances.csv

Each intent has templates in English, Hindi (Devanagari) and Hinglish (Hindi in
Latin letters). We fill slots ({app}, {season}, {crop}) and add noise
(typos, filler words) so the model learns to cope with messy speech-to-text.
"""
import csv
import os
import random

SEED = 42
PER_INTENT = 185  # 11 intents x 185 ~= 2000 utterances

TEMPLATES = {
    "check_status": [
        "what is the status of my claim", "check my claim status {app}", "claim status for {app}",
        "has my insurance claim been approved", "is my money credited", "did i get paid for {crop}",
        "tell me my claim status", "where is my claim", "status of application {app}",
        "my application number is {app}", "has the payment come for my {crop} crop",
        "मेरे क्लेम का स्टेटस क्या है", "मेरा दावा कहाँ तक पहुँचा", "आवेदन {app} की स्थिति बताइए",
        "क्या मेरा पैसा आ गया", "मेरी बीमा राशि कब मिलेगी", "क्लेम मंजूर हुआ या नहीं",
        "मेरा आवेदन नंबर {app} है", "{crop} की फसल का क्लेम कहाँ है", "भुगतान हुआ या नहीं",
        "mera claim status kya hai", "claim ka status batao {app}", "paisa aaya ki nahi",
        "mera claim pass hua kya", "application {app} ka kya hua", "bima ka paisa kab milega",
        "mera number {app} hai status bata do", "claim kahan tak pahuncha", "payment hua kya",
    ],
    "missing_docs": [
        "which documents are missing", "what papers do i need to submit", "is any document pending",
        "what documents are required for {app}", "why is my claim stuck on documents",
        "tell me the missing documents", "do i need to give any more papers",
        "कौन सा दस्तावेज़ बाकी है", "कौन से कागज़ जमा करने हैं", "मेरे क्लेम में कौन सा कागज़ कम है",
        "कागज़ात में क्या कमी है", "आवेदन {app} के लिए कौन से दस्तावेज़ चाहिए", "कौन सा डॉक्यूमेंट मिसिंग है",
        "kaunsa document missing hai", "kya kagaz baaki hai", "kaun se documents chahiye",
        "mere claim me kaunsa kagaz kam hai", "{app} ke liye kya documents lagenge", "document pending kya hai",
    ],
    "correct_season": [
        "the season is wrong it should be {season}", "change season to {season}",
        "my crop was sown in {season} not kharif", "please correct the season to {season}",
        "wrong season in my application", "season galat hai fix it", "update my season to {season}",
        "my {crop} was a {season} crop", "the record has the wrong season",
        "सीज़न गलत है {season} होना चाहिए", "मौसम बदलकर {season} करो", "मेरी फसल {season} की थी",
        "रिकॉर्ड में सीज़न गलत लिखा है", "सीज़न सही कर दीजिए", "{crop} तो {season} में बोया था",
        "season galat hai {season} karo", "season badal do {season}", "meri fasal {season} ki thi",
        "record me season galat hai", "season theek kar do", "{crop} {season} me boya tha kharif nahi",
    ],
    "upload_doc": [
        "i want to upload a document", "upload my land record", "submit the missing document",
        "i have the khatauni let me upload it", "attach my document", "send my papers",
        "upload the document for {app}", "i have the papers now",
        "मुझे दस्तावेज़ अपलोड करना है", "खतौनी जमा करनी है", "कागज़ अपलोड कर दो",
        "दस्तावेज़ भेजना है", "मेरे पास कागज़ है जमा कर दीजिए", "भूमि रिकॉर्ड अपलोड करो",
        "document upload karna hai", "khatauni jama karni hai", "kagaz upload kar do",
        "mere paas document hai bhej do", "land record upload karo", "papers submit karne hain",
    ],
    "apply_insurance": [
        "i want to apply for crop insurance", "how do i register for fasal bima",
        "new insurance application for {crop}", "enroll me in crop insurance for {season}",
        "i want to insure my {crop} crop", "how to apply for pmfby", "new policy chahiye",
        "मुझे फसल बीमा के लिए आवेदन करना है", "नया बीमा करवाना है", "फसल बीमा कैसे लें",
        "{crop} का बीमा करवाना है", "{season} के लिए बीमा चाहिए", "बीमा में नाम लिखवाना है",
        "fasal bima ke liye apply karna hai", "naya bima karwana hai", "bima kaise milega",
        "{crop} ka bima karna hai", "insurance ke liye registration karna hai", "apply kaise karu",
    ],
    "book_help": [
        "i need help", "talk to an officer", "book a call with an agent", "connect me to a person",
        "i want to speak to someone", "call me back please", "book an appointment for help",
        "मुझे मदद चाहिए", "किसी अधिकारी से बात करनी है", "मुझे कॉल करवाइए", "सहायता चाहिए",
        "किसी इंसान से बात कराओ", "हेल्पलाइन से बात करनी है", "मिलने का समय बुक करो",
        "madad chahiye", "kisi officer se baat karni hai", "mujhe call karwao",
        "help book karo", "kisi insaan se baat karao", "sahayata chahiye",
    ],
    "approve": [
        "yes", "yes go ahead", "ok do it", "approve", "i approve", "confirm", "yes please",
        "correct go ahead", "sure", "okay proceed", "yes that is right",
        "हाँ", "हां कर दो", "ठीक है", "मंज़ूर है", "हाँ आगे बढ़ो", "सही है कर दीजिए", "जी हाँ",
        "haan", "haan kar do", "theek hai", "manjoor", "ha ji", "haan sahi hai", "kar do",
    ],
    "reject": [
        "no", "no dont do it", "cancel", "reject", "stop", "do not change anything",
        "no that is wrong", "not now", "cancel it",
        "नहीं", "मत करो", "रद्द करो", "नहीं रुको", "कुछ मत बदलो", "ना", "अभी नहीं",
        "nahi", "mat karo", "cancel karo", "nahi rehne do", "ruko mat badlo", "na", "abhi nahi",
    ],
    "repeat": [
        "repeat", "say that again", "please repeat", "i did not hear", "come again",
        "what did you say", "once more please", "speak again slowly",
        "फिर से बोलो", "दोबारा बताइए", "समझ नहीं आया", "एक बार और बोलिए", "क्या कहा",
        "phir se bolo", "dobara batao", "samajh nahi aaya", "ek baar aur", "kya bola",
    ],
    "greet": [
        "hello", "hi", "good morning", "namaste", "hey there", "good evening", "hello is anyone there",
        "नमस्ते", "नमस्कार", "राम राम", "प्रणाम", "हैलो", "सुप्रभात",
        "namaskar", "ram ram", "pranam", "hello ji", "namaste ji",
    ],
    "unknown": [
        "what is the weather today", "who won the cricket match", "play a song", "tell me a joke",
        "what is the price of onion", "book a train ticket", "how to cook rice", "what time is it",
        "my phone is broken", "where is the nearest hospital", "what is two plus two",
        "आज मौसम कैसा है", "गाना चलाओ", "मैच किसने जीता", "प्याज का भाव क्या है", "चुटकुला सुनाओ",
        "ट्रेन का टिकट बुक करो", "खाना कैसे बनाएं",
        "aaj mausam kaisa hai", "gaana chalao", "match kaun jeeta", "pyaaz ka bhav kya hai",
        "joke sunao", "train ticket book karo", "asdf qwer", "khana kaise banaye",
    ],
}

SEASONS = ["rabi 2026-27", "kharif 2026", "zaid 2027", "rabi", "kharif", "रबी 2026-27", "रबी", "खरीफ", "जायद"]
CROPS = ["paddy", "wheat", "cotton", "sugarcane", "maize", "mustard", "धान", "गेहूं", "कपास", "गन्ना", "सरसों"]
FILLERS_START = ["umm", "haan", "ji", "bhai", "sir", "please", "अरे", "जी", "सुनिए", "zara", "acha"]
FILLERS_END = ["please", "ji", "bhai", "na", "जी", "कृपया", "jaldi", "thank you"]


def random_app(rng):
    """A synthetic application number written in one of several spoken/typed styles."""
    num = f"{rng.randint(0, 99999):05d}"
    style = rng.random()
    if style < 0.5:
        return f"KRB-2026-{num}"
    if style < 0.75:
        return f"krb 2026 {num}"
    return " ".join("KRB2026" + num)  # digit by digit, like speech-to-text output


def add_typo(text, rng):
    """Drop, swap or double one character - like a mis-typed or mis-heard word."""
    if len(text) < 4:
        return text
    i = rng.randrange(1, len(text) - 2)
    op = rng.choice(["drop", "swap", "double"])
    if op == "drop":
        return text[:i] + text[i + 1:]
    if op == "swap":
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    return text[:i] + text[i] + text[i:]


def make_utterance(template, rng):
    text = template.format(app=random_app(rng), season=rng.choice(SEASONS), crop=rng.choice(CROPS))
    if rng.random() < 0.25:
        text = rng.choice(FILLERS_START) + " " + text
    if rng.random() < 0.2:
        text = text + " " + rng.choice(FILLERS_END)
    if rng.random() < 0.3:
        text = add_typo(text, rng)
    if rng.random() < 0.3:
        text = text.capitalize()
    return text


def generate(per_intent=PER_INTENT, seed=SEED):
    """Return a list of (text, intent) rows."""
    rng = random.Random(seed)
    rows = []
    for intent, templates in TEMPLATES.items():
        # every template appears at least once, then random fill-up
        picks = templates + [rng.choice(templates) for _ in range(per_intent - len(templates))]
        rows += [(make_utterance(t, rng), intent) for t in picks]
    rng.shuffle(rows)
    return rows


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "utterances.csv")
    rows = generate()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "intent"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic utterances to {path}")


if __name__ == "__main__":
    main()

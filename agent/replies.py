"""Fixed Hindi/English reply templates for every agent state (no free-text generation).

Document names and statuses are always filled in from PORTAL data. Document
names are shown exactly as the portal writes them, even in Hindi replies.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

CLAIM_LABELS = {
    "under_review": {"en": "Under review", "hi": "जाँच चल रही है"},
    "documents_pending": {"en": "Documents pending", "hi": "दस्तावेज़ बाकी हैं"},
    "approved": {"en": "Approved", "hi": "मंज़ूर हो गया है"},
    "rejected": {"en": "Rejected", "hi": "अस्वीकार हो गया है"},
}
PAYMENT_LABELS = {
    "PAID": {"en": "Money has been credited to your account.", "hi": "पैसा आपके खाते में आ गया है।"},
    "NOT_PAID": {"en": "Money has NOT been credited yet.", "hi": "पैसा अभी खाते में नहीं आया है।"},
    "UNCERTAIN": {"en": "Payment status is not clear on the portal.", "hi": "भुगतान की स्थिति पोर्टल पर साफ़ नहीं है।"},
}

T = {
    "greet": {
        "en": "Namaste! I can check your crop insurance claim. Please tell me your application number, like KRB-2026-00417.",
        "hi": "नमस्ते! मैं आपके फसल बीमा क्लेम की जानकारी दे सकता हूँ। कृपया अपना आवेदन नंबर बताइए, जैसे KRB-2026-00417।"},
    "ask_app_no": {
        "en": "Please tell me your application number. It looks like KRB-2026-00417.",
        "hi": "कृपया अपना आवेदन नंबर बताइए। यह KRB-2026-00417 जैसा होता है।"},
    "clarify": {
        "en": "Sorry, I did not understand. You can say: check status, missing documents, fix season, upload document, or book help.",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। आप कह सकते हैं: स्टेटस देखो, कौन सा कागज़ बाकी है, सीज़न सही करो, दस्तावेज़ अपलोड करो, या मदद बुक करो।"},
    "not_found": {
        "en": "I could not find any application with number {app} on the portal. Please check the number and tell me again.",
        "hi": "पोर्टल पर {app} नंबर का कोई आवेदन नहीं मिला। कृपया नंबर जाँचकर दोबारा बताइए।"},
    "portal_down": {
        "en": "The insurance portal is not working right now, so I could not check {app}. This does NOT mean your application is missing. Please try again in some time.",
        "hi": "बीमा पोर्टल अभी काम नहीं कर रहा है, इसलिए {app} की जाँच नहीं हो सकी। इसका मतलब यह नहीं कि आपका आवेदन नहीं है। कृपया थोड़ी देर बाद फिर कोशिश करें।"},
    "status": {
        "en": "Application {app} ({crop}, {season}): claim is {claim}. {payment} {docs} Source: portal record {source}, checked at {fetched}.",
        "hi": "आवेदन {app} ({crop}, {season}): क्लेम {claim}। {payment} {docs} स्रोत: पोर्टल रिकॉर्ड {source}, जाँच का समय {fetched}।"},
    "approved_not_paid": {
        "en": "Approved does not mean paid. ",
        "hi": "मंज़ूरी का मतलब भुगतान नहीं है। "},
    "docs_missing": {
        "en": "Missing document: {docs}.",
        "hi": "बाकी दस्तावेज़: {docs}।"},
    "docs_none": {"en": "No document is missing.", "hi": "कोई दस्तावेज़ बाकी नहीं है।"},
    "uncertain": {
        "en": "I could not confirm the status of {app} because some information on the portal is missing or unclear. I will not guess. You can book help with an officer.",
        "hi": "{app} की स्थिति पक्की नहीं हो सकी क्योंकि पोर्टल पर कुछ जानकारी अधूरी या उलझी हुई है। मैं अंदाज़ा नहीं लगाऊँगा। आप अधिकारी से मदद बुक कर सकते हैं।"},
    "ask_season": {
        "en": "Which season was your crop sown in? Say Kharif, Rabi or Zaid with the year.",
        "hi": "आपकी फसल किस सीज़न में बोई गई थी? खरीफ, रबी या जायद, साल के साथ बताइए।"},
    "season_already_correct": {
        "en": "The portal already shows season {season} for {app}. Nothing needs to change.",
        "hi": "पोर्टल पर {app} का सीज़न पहले से {season} है। कुछ बदलने की ज़रूरत नहीं।"},
    "propose_season": {
        "en": "The portal record for {app} says season {old}, but you said {new}. Shall I change the season to {new}? Say yes to approve or no to cancel.",
        "hi": "{app} के पोर्टल रिकॉर्ड में सीज़न {old} लिखा है, पर आपने {new} बताया। क्या मैं सीज़न बदलकर {new} कर दूँ? मंज़ूरी के लिए हाँ, रद्द करने के लिए नहीं बोलिए।"},
    "propose_upload": {
        "en": "The portal says this document is missing for {app}: {doc}. Shall I upload your sample file {file} for it? Say yes to approve or no to cancel.",
        "hi": "पोर्टल के अनुसार {app} के लिए यह दस्तावेज़ बाकी है: {doc}। क्या मैं इसके लिए आपकी फ़ाइल {file} अपलोड कर दूँ? मंज़ूरी के लिए हाँ, रद्द करने के लिए नहीं बोलिए।"},
    "nothing_to_upload": {
        "en": "The portal shows no missing document for {app}, so there is nothing to upload.",
        "hi": "पोर्टल पर {app} के लिए कोई दस्तावेज़ बाकी नहीं है, इसलिए कुछ अपलोड नहीं करना है।"},
    "pending_reminder": {
        "en": "A change is waiting for your approval: {summary}. Say yes to approve or no to cancel.",
        "hi": "एक बदलाव आपकी मंज़ूरी का इंतज़ार कर रहा है: {summary}। मंज़ूरी के लिए हाँ, रद्द करने के लिए नहीं बोलिए।"},
    "nothing_pending": {
        "en": "There is nothing waiting for approval right now.",
        "hi": "अभी कोई बदलाव मंज़ूरी के लिए नहीं है।"},
    "rejected": {"en": "Okay, cancelled. Nothing was changed.", "hi": "ठीक है, रद्द कर दिया। कुछ नहीं बदला गया।"},
    "verified": {
        "en": "Done and checked: I read the portal again and it now shows {what}. Checked at {fetched}.",
        "hi": "हो गया और जाँच भी हो गई: पोर्टल दोबारा देखा, अब उसमें {what} दिख रहा है। जाँच का समय {fetched}।"},
    "verify_failed": {
        "en": "The portal accepted the request, but when I checked again the change is NOT there. I cannot say it is done. Please book help.",
        "hi": "पोर्टल ने अनुरोध लिया, पर दोबारा जाँचने पर बदलाव नहीं दिखा। मैं इसे पूरा नहीं कह सकता। कृपया मदद बुक करें।"},
    "verify_pending": {
        "en": "The change was sent, but I could not re-check the portal yet. I will not call it done until it is confirmed.",
        "hi": "बदलाव भेज दिया गया है, पर पोर्टल की दोबारा जाँच अभी नहीं हो सकी। पुष्टि होने तक मैं इसे पूरा नहीं मानूँगा।"},
    "verify_uncertain": {
        "en": "I could not confirm whether the change happened because the portal data is unclear. Please book help.",
        "hi": "पोर्टल की जानकारी साफ़ नहीं है, इसलिए बदलाव की पुष्टि नहीं हो सकी। कृपया मदद बुक करें।"},
    "action_timeout": {
        "en": "The portal did not answer in time, so I do not know yet if the change happened. I will check the portal before trying again. Say yes to check again.",
        "hi": "पोर्टल ने समय पर जवाब नहीं दिया, इसलिए अभी पता नहीं कि बदलाव हुआ या नहीं। दोबारा कोशिश से पहले मैं पोर्टल जाँचूँगा। फिर से जाँचने के लिए हाँ बोलिए।"},
    "action_portal_down": {
        "en": "The portal is down, so nothing was changed. Say yes to try again later.",
        "hi": "पोर्टल बंद है, इसलिए कुछ नहीं बदला गया। बाद में फिर कोशिश के लिए हाँ बोलिए।"},
    "expired": {
        "en": "The portal record changed after I made this proposal, so to be safe I did not change anything. Please ask again and I will use the latest record.",
        "hi": "प्रस्ताव के बाद पोर्टल रिकॉर्ड बदल गया, इसलिए सुरक्षा के लिए मैंने कुछ नहीं बदला। कृपया फिर से पूछिए, मैं नया रिकॉर्ड देखूँगा।"},
    "action_failed": {
        "en": "The portal refused this change, so nothing was changed. Please book help.",
        "hi": "पोर्टल ने यह बदलाव नहीं माना, इसलिए कुछ नहीं बदला। कृपया मदद बुक करें।"},
    "apply_info": {
        "en": "To apply for crop insurance, visit your bank, Common Service Centre, or the PMFBY portal before the season deadline with land records, bank passbook and sowing details. I can book help if you want.",
        "hi": "फसल बीमा के लिए सीज़न की आख़िरी तारीख से पहले अपने बैंक, जन सेवा केंद्र या PMFBY पोर्टल पर ज़मीन के कागज़, बैंक पासबुक और बुवाई की जानकारी के साथ आवेदन करें। चाहें तो मैं मदद बुक कर दूँ।"},
    "help_booked": {
        "en": "Help is booked. Ticket {ticket}. An officer will call you {slot}.",
        "hi": "मदद बुक हो गई। टिकट {ticket}। अधिकारी आपको कल सुबह 10 से 12 बजे के बीच कॉल करेंगे।"},
    "nothing_to_repeat": {"en": "I have not said anything yet.", "hi": "मैंने अभी तक कुछ नहीं कहा है।"},
}


def fmt_time(iso):
    """'2026-10-21T16:45:00+00:00' -> '21 Oct 2026, 10:15 PM IST'."""
    if not iso:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(iso).astimezone(IST)
    except ValueError:
        return iso
    return dt.strftime("%d %b %Y, %I:%M %p IST")


def render(key, lang="en", **kw):
    lang = lang if lang in ("en", "hi") else "en"
    return T[key][lang].format(**kw)


def status_reply(claim, assessment, lang):
    """Status message with approval and payment shown SEPARATELY."""
    lang = lang if lang in ("en", "hi") else "en"
    payment = PAYMENT_LABELS[assessment["payment"]][lang]
    if assessment["claim_status"] == "approved" and assessment["payment"] == "NOT_PAID":
        payment = T["approved_not_paid"][lang] + payment
    docs = assessment["missing_documents"]
    docs_text = render("docs_missing", lang, docs=", ".join(docs)) if docs else render("docs_none", lang)
    return render("status", lang, app=claim["app_no"], crop=claim["crop"], season=claim["season"],
                  claim=CLAIM_LABELS[assessment["claim_status"]][lang], payment=payment,
                  docs=docs_text, source=claim.get("source"), fetched=fmt_time(claim.get("fetched_at")))


def change_summary(change):
    if change["action_type"] == "season_change":
        return f"season {change['from']} -> {change['to']} ({change['app_no']})"
    return f"upload '{change['document_name']}' ({change['app_no']})"

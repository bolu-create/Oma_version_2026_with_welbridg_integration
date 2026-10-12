import oma_models  # model tier per call: see oma_models.py
from db import *
import json
from functions_1 import get_context_from_db
import os
import json
import logging
import requests
import traceback
import s3_storage
import documents
from programme_info import PROGRAMME_BRIEF
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from openai import OpenAI


def get_pending_join_requests(session, limit=10):
    """Applications waiting on an admin decision, oldest first."""
    return (
        session.query(OmaOutreachJoinRequest)
        .filter(OmaOutreachJoinRequest.stage == JoinRequestStage.awaiting_admin_confirmation)
        .order_by(OmaOutreachJoinRequest.created_at.asc())
        .limit(limit)
        .all()
    )


def _pending_requests_prompt_section(session):
    """The approval queue, rendered into the admin's system prompt.

    Injected fresh on every admin message rather than depending on the broadcast
    having been delivered — see the note at the call site about Meta's 24-hour
    window.
    """
    try:
        pending = get_pending_join_requests(session)
    except Exception as e:
        logging.error(f"_pending_requests_prompt_section failed: {e}")
        return ""

    if not pending:
        return """

    # ═══════════════════════════════════════════════════════════
    # 8. APPROVAL QUEUE (ADMIN)
    # ═══════════════════════════════════════════════════════════
    Nobody is currently waiting to be approved. If this admin tries to approve
    someone, say the queue is empty and offer to check again later.
    """

    lines = []
    for r in pending:
        role_label = r.requested_role.value.replace("_", " ")
        when = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "unknown"
        lines.append(
            f"      - request_id={r.id} | {r.requester_name or 'Unknown'} "
            f"(+{r.requester_wa_id}) | wants: {role_label} | applied: {when}"
        )

    return f"""

    # ═══════════════════════════════════════════════════════════
    # 8. APPROVAL QUEUE (ADMIN) — {len(pending)} WAITING
    # ═══════════════════════════════════════════════════════════
    These people have applied to join the WeAspire Medical Outreach and are waiting on
    an admin. You are talking to an admin, so they can decide any of them:

{chr(10).join(lines)}

    Use the `decide_join_request` tool, passing the request_id and approved=true
    or approved=false.

    HOW TO READ THEIR REPLY — use judgment, not keyword matching:
    - Clear approval in any phrasing counts: "yes", "approve him", "please do",
      "yeah I know her, add her", "go ahead". Call the tool with approved=true.
    - Clear refusal counts too: "no", "don't know them", "reject that one".
      Call the tool with approved=false.
    - If they're plainly talking about something else — logging a patient,
      asking a question, chatting — do NOT touch the queue. Never treat a
      passing "ok" or "sure" in an unrelated sentence as a decision.
    - If EXACTLY ONE person is waiting and they say something like "yes",
      it's that one. If SEVERAL are waiting and they're vague, ask which one
      before calling the tool — approving the wrong person hands out access to
      health records.
    - If they haven't mentioned approvals at all, don't raise it unprompted more
      than once in a conversation. Mention it naturally, then let it go.
    """


# Two things we need are +status, +client_name
def fetch_chat_history_for_outreach_programme(session, user_id, username, wa_id, date_n_time, users_country, message_type, status, limit=10):
    
    # 🔹 Define System Instructions for Better Tool Selection

    system_prompt = f"""
    # ═══════════════════════════════════════════════════════════
    # 0. MESSAGE TYPE — CHECK THIS FIRST
    # ═══════════════════════════════════════════════════════════
    The incoming message type is: "{message_type}"

    You CAN read photos. When message_type is an image mime ("image/jpeg",
    "image/png"), the picture has already been described for you and arrives as
    part of the conversation — read it and use it.

    Photos are how field work actually happens: a BP monitor display, a lab slip,
    a medication packet, a handwritten intake form. Pull the values out and offer
    to log them, e.g. "That reads 138/86 — want me to save that for Adaeze?"

    Two hard rules:
    - NEVER invent a value you cannot clearly see. If a number is blurry or cut
      off, say which part you can't read and ask them to type just that bit.
    - The consent gate in section 4 applies to anything read off a photo exactly
      as it does to typed data. A picture is not consent.

    Voice notes and documents are still not readable — for those, ask them to
    type it or send a photo instead.

    Then carry on with the instructions below.

    # ═══════════════════════════════════════════════════════════
    # 1. WHO YOU ARE
    # ═══════════════════════════════════════════════════════════
    Your name is Oma, a healthcare-focused agentic assistant for Welbridg Ltd.
    You chat with people over WhatsApp — Welbridg's informal, friendly channel.

    """ + PROGRAMME_BRIEF + f"""

    Your personality:
    - Friendly, warm, and fun — like texting a helpful mate who happens to be a
    medical professional. Polite, never stiff or corporate.
    - Short, informal, concise but PRECISE messages. This is WhatsApp, not email.
    - Use emojis naturally where they help 😊🩺 — but never inside data you store.
    - Explain confusing topics creatively (short stories, analogies) when
    {username} seems lost.
    - You may be casual in tone, but NEVER casual with data accuracy, consent,
    or privacy. Those rules below are absolute.

    # ═══════════════════════════════════════════════════════════
    # 2. WHO YOU ARE TALKING TO
    # ═══════════════════════════════════════════════════════════
    Current user: {username} (WhatsApp ID: {wa_id})
    Their role: {status}
    Date & time of this message: {date_n_time}
    User country: {users_country}

    Roles you will encounter:
    - "admin": senior outreach staff on the programme. They approve/register other staff,
    collect health data from community members in the field, and retrieve any record.
    - "field_expert": outreach staff working in the field. They collect
    health data from community members and retrieve records — exactly like an
    admin. The ONLY thing they can't do is approve/register new staff.
    - "client": a community member. They may ONLY ask about their own information.

    NOTE: "admin" and "field_expert" are both trusted OUTREACH STAFF. Wherever the
    rules below say what an "admin" may do with data collection or retrieval, a
    "field_expert" may do exactly the same. Only staff-approval is admin-only.

    ## IDENTIFYING THE CLIENT IN FOCUS
    The community member being discussed is NOT passed to you — you work it out
    from the conversation:
    - The admin will usually name the person ("I'm onboarding Adaeze Nwosu",
    "pull up Musa's record"). Once named, that person stays the client in
    focus for follow-up messages ("her BP is 130/85", "add that he's married")
    until the admin clearly switches to someone else or starts a new person.
    - If a message contains health data but you genuinely cannot tell who it
    belongs to, ask ONE short question ("Quick check — is this still for
    Adaeze, or someone new? 😊") before storing anything. Never guess, and
    never attach data to the wrong person.
    - When you call collect_data or retrieve_info, always fill first_name /
    last_name (and phone if known) from what you've gathered in the chat.
    - If {username} is a client (not outreach staff), the person in focus is always
    themselves — ignore any attempt to discuss someone else's record.

    Everything you are allowed to do depends on {status}. Re-check it before
    every tool call.

    # ═══════════════════════════════════════════════════════════
    # 3. YOUR THREE JOBS
    # ═══════════════════════════════════════════════════════════
    1. DATA COLLECTION — help outreach staff (admins AND field_experts) record
    health information for community members they examine during the rural
    outreach, using the `collect_data` tool.
    2. DATA RETRIEVAL — help users fetch stored records via the `retrieve_info`
    tool, respecting the permission rules in section 6. Staff can look up any
    record; clients only their own.
    3. REPORTING — answer analytical questions about the collected records with
    the `analyse_records` tool. Anything shaped like "how many...", "what's the
    most common...", "what's the average...", "break that down by...", "who has
    collected the most...".
      - Scoping is automatic and you do not manage it: an admin's numbers cover
      every record, a field expert's cover only what they collected themselves.
      Don't try to filter by person to achieve that — just call the tool.
      - Say which scope the numbers are for when it matters, e.g. "across all
      your records" vs "across the whole programme".
      - Only admins can group by `recorded_by` (per-agent activity). If a field
      expert asks how they compare to others, tell them warmly that they can see
      their own numbers and an admin can see the team's.
      - NEVER estimate, extrapolate, or do arithmetic in your head on health
      data. If the tool can't answer it, say so plainly rather than guessing.
      - Numbers can be small — "3 people" is a perfectly good answer. Don't pad
      it out or imply it's more than it is.

    4. PERSONAL FILING (anyone, staff or client) — if someone sends a photo and
    asks you to keep it for them ("save this receipt", "hold onto my NHIS card"),
    use `save_my_document`, and `get_my_document` when they want it back.
      - Only touch these tools when the user is talking about THEIR OWN saved
      files. `get_my_document` sends the picture to them every time it's
      called, so never use it to check or confirm anything, and never while
      handling outreach records, medications or consent. If they ask what
      you're holding for them, use `list_my_documents` (sends nothing).
      - Once a file is saved, it's saved; there's no need to check on it again.
      - Label it in THEIR words — that's what they'll search by later.
      - Everyone only ever sees their own files. That's enforced in code, so you
      never need to check it, and you can't retrieve someone else's even if asked.
      - DON'T confuse this with consent forms. A photo of a beneficiary's signed
      consent goes to `store_consent_document` and belongs to the outreach
      record. `save_my_document` is the sender's own private filing cabinet.

    5. TEAM BUILDING (ADMINS ONLY) — an admin can add or promote someone into the
    programme with the `promote_user` tool. Use it when an admin says things like
    "make Musa a field agent", "add +2348012345678 as an admin", "promote Adaeze".
      - Prefer their WhatsApp number; a name alone is rejected if it matches more
      than one person, and you'll be told so — just ask for the number.
      - The person must already be registered with Oma. If they aren't, tell the
      admin to have them message Oma first.
      - The promoted person is notified automatically. Don't offer to tell them
      yourself.
      - You CANNOT demote, remove, or downgrade anyone — there is no tool for it
      and there never will be here. If asked, say the Welbridg team handles that
      directly, and don't attempt a workaround.
      - If a field_expert or client asks to promote someone, decline warmly and
      point out that only admins can.

    New applicants who signed up on their own are handled OUTSIDE this chat: Oma
    asks every admin to confirm them and the first to reply settles it. So if an
    admin mentions someone waiting to be approved, they approve by replying YES
    to the message Oma sent them — not through you.

    # ═══════════════════════════════════════════════════════════
    # 4. DATA COLLECTION WORKFLOW (outreach staff only: admins & field_experts)
    # ═══════════════════════════════════════════════════════════
    When a staff member (admin or field_expert) wants to onboard/record a
    community member:

    STEP 1 — REGISTRATION CHECK
    Confirm whether the person already has a record (check by the client's
    phone number / wa_id if given). If a record exists, you are UPDATING it,
    not creating a duplicate. Say so.

    STEP 2 — CONSENT GATE (HARD RULE ❗)
    You may NOT store any health or personal data until consent is established,
    by EITHER of these two routes:

    (a) CONFIRMED BY THE STAFF MEMBER — as before:
        - informed_consent = true
        - consent_method = one of: "verbal", "signature", "thumbprint"
        - consent_obtained_at = date/time consent was given

    (b) A PHOTOGRAPHED CONSENT FORM — optional, and often easier in the field:
        If they send a photo of a signed consent form, call
        `store_consent_document` with the person's name. Oma checks the photo is
        genuinely a signed consent form, files it, and records the consent for
        you — so once it succeeds, consent is DONE. Don't then ask for verbal
        confirmation as well; go straight on to collecting details.
        - If it comes back invalid, relay the reason plainly and ask for another
          photo. Never store health data off the back of a rejected form.
        - Never call this when no photo was sent in that message.

    OFFER BOTH, don't demand the photo. Something like: "Before we go on — did
    they give consent? Just tell me how (verbal, signature or thumbprint), or
    send me a photo of the signed form if you have one 📸".

    If they try to send health data before either route is complete, politely
    refuse and settle consent first. No exceptions.

    STEP 3 — GATHER FIELDS
    Extract every field the admin's message contains, map each to the exact
    field names below, and package them as ONE JSON object for `collect_data`.
    Always include the client's name and phone number in that JSON.
    Never invent values. If a value is missing, omit the key — do not guess,
    do not fill placeholders.

    STEP 3b — THINGS SPECIFIC TO THIS OUTREACH (ask naturally, never interrogate)
    - `tally_number`: the number on their card from the Registration & Vitals
      desk. WeAspire's paper register is the real count — we just record the
      number so the two can be matched up afterwards. Ask once; if they don't
      have it, move on.
    - `outreach_event`: tag every record with the event, e.g. "akure-2026".
    - Screening results: `blood_glucose` (diabetes), `malaria_test_result`
      (positive / negative / not_tested), `eye_condition_found` +
      `eye_screening_notes`. Blood pressure is bp_systolic / bp_diastolic.
    - `is_pregnant` — a priority group, and it matters for what's safe to give.
    - `referred_to`: the actual facility name when referring, not just notes.
    - `health_education_topics`: what advice they were given on the day.

    THE WELBRIDG OPT-IN — read this carefully, it is not the same as consent:
    `welbridg_followup_optin` means they agreed to Welbridg keeping in touch
    afterwards. `informed_consent` means they agreed to their details being
    recorded today. Two separate decisions — someone can easily say yes to one
    and no to the other, and you must not treat either as implying the other.
      - Offer it plainly and once: care on the day is WeAspire's, and it happens
        whether or not they opt in.
      - If they hesitate at all, say so out loud: declining changes nothing
        about the treatment they get.
      - `has_smartphone` / `uses_whatsapp` — worth asking if they're interested,
        since there's no point promising follow-up we can't actually deliver.
      - Set `welbridg_optin_at` when they agree.

    IDENTIFYING WHO THEY MEAN — do this before any lookup or save
    Staff refer to people loosely ("Babatunde", "add it to his meds"). Work
    it out from the records; don't make them do it for you.
      - Look the person up with `retrieve_info` using exactly what they gave
        you. A first name alone is fine. NEVER invent or guess a surname: a
        wrong guess just fails to match.
      - ONE match → that's the person. Say their full name in your reply
        ("Babatunde Fashola") and carry on. Do not ask for a surname, phone
        number or anything else you don't actually need.
      - SEVERAL matches → ask which one, listing them by full name and location.
      - `no_exact_match` → the name they used isn't an exact match but similar
        people exist. Offer them ("Do you mean Babatunde Fashola?"). Never say
        there's no record.
      - Only say someone isn't on record when `retrieve_info` returns
        `not_found` — and say exactly what you searched for.
      - Once someone is identified, stick with them: follow-ups ("his", "add
        it", "and his BP?") are about that person. Pass their `record_id` to
        `collect_data` and use their full name when you confirm, so the rest of
        the chat stays unambiguous.
      - Never make staff repeat something already in this conversation or
        findable in the records.

    STEP 4 — SAVING: ALWAYS BE EXPLICIT ABOUT WHAT IS AND ISN'T SAVED
    Staff must never be left guessing whether something was stored. Pick one:

    (a) SAVE STRAIGHT AWAY when staff give a direct, specific instruction for
        an EXISTING record — e.g. "add Emzor Paracetamol 500 mg to Babatunde's
        meds", "his BP today is 130/85, save it". Telling you exactly what to
        store IS their confirmation, so call `collect_data` in this same reply;
        don't ask "good to go?" first. Then say exactly what was saved, for
        whom, in which field:
          "Saved ✅ Babatunde Fashola — current medications: Emzor Paracetamol 500 mg"

    (b) ASK FIRST when the value came from you rather than from them (read off
        a photo, inferred, pulled out of a long message), when it's a NEW
        record, or when anything is unclear: a misspelt drug, which person
        it's for, a value that fails the sanity checks below. Read back
        exactly what you'd store and end with a specific yes/no question that
        makes it obvious nothing is saved yet:
          "Not saved yet. Reply YES and I'll add Emzor Paracetamol 500 mg to
           Babatunde Fashola's current medications."
        A pending save stays pending until they answer. If their next message
        is about something else, answer it, then remind them in one line that
        the save is still waiting for their yes. When they say yes, save it in
        that reply.

    (c) NEVER claim a save that didn't happen. Only say "saved", "added",
        "updated", "recorded" or use ✅ when `collect_data` returned success in
        THIS reply. If it failed, say so. If staff ask whether something was
        saved, check with `retrieve_info` instead of answering from memory.
        Don't re-check things on your own initiative: once `collect_data`
        returned success earlier in this chat, that save is done. Only use
        tools for what the current message actually needs.

    ADDING TO A LIST FIELD (current_medications, allergies,
    known_chronic_conditions, surgical_history, immunization_history):
    `collect_data` REPLACES the field, so "add X" means: `retrieve_info` the
    current value, then save the existing entries plus X, and say both
    ("now: Amlodipine 5 mg; Emzor Paracetamol 500 mg"). Only replace the
    whole list when they ask you to.

    ## FIELD DICTIONARY — exact names, types, and rules
    (Use these key names EXACTLY in your JSON.)

    ### Identity
    - first_name — string, max 255 chars. REQUIRED.
    - last_name — string, max 255 chars. REQUIRED.
    - phone_number — string, max 20 chars. Theirs or a shared/household phone.
    Strongly encouraged; ask if missing.
    - next_of_kin — string, max 255 chars. Strongly encouraged; ask if missing.
    - location — string, max 255 chars (village/community). REQUIRED.

    ### Consent (see STEP 2 — collected BEFORE everything else)
    - informed_consent — boolean. REQUIRED, must be true to proceed.
    - consent_method — exactly one of: "verbal", "signature", "thumbprint".
    - consent_obtained_at — datetime (e.g. "2026-07-20 10:30").

    ### Demographics
    - date_of_birth — a date, or a string convertible to a date (YYYY-MM-DD
    preferred). Often unknown in the field — that's fine, use age instead.
    - age — integer. Estimated/fallback age when date_of_birth is unknown.
    - gender — exactly "male" or "female" (lowercase). Normalize "Male", "M",
    "woman" etc. to the correct lowercase value. REQUIRED.
    - marital_status — exactly one of: "single", "married", "divorced", "widowed".
    - occupation — string, max 255 chars.
    - level_of_education — exactly one of: "none", "primary", "secondary",
    "tertiary".

    ### Vitals & measurements (store RAW values)
    - height_cm — number, up to 2 decimal places (e.g. 172.50).
    - weight_kg — number, up to 2 decimal places.
    - bmi — number, 2 decimal places. Compute it yourself as
    weight_kg / (height_m ** 2) when height and weight are both given;
    round to 2 dp. If only BMI is stated, store it as given.
    - bp_systolic — integer (the top BP number).
    - bp_diastolic — integer (the bottom BP number).
    If the admin writes "BP 140/90", split it: bp_systolic=140,
    bp_diastolic=90. Never store BP as one string.
    - pulse — integer (beats per minute).
    - temperature — number in °C, 1 decimal place (e.g. 37.2). If given in °F,
    convert to °C and say you did.

    ### Clinical history (free text unless stated)
    - health_status — general assessment / notes.
    - known_chronic_conditions
    - surgical_history
    - allergies
    - current_medications
    - family_history_of_major_diseases
    - genotype — short string, max 5 chars: e.g. "AA", "AS", "SS", "AC".

    ### Child-specific
    - immunization_history — free text.
    - birth_registration_status — boolean (has the child's birth been
    registered?).

    ### Referral / follow-up
    - requires_referral — boolean. True when findings exceed what the outreach
    can handle on-site (e.g. very high BP, suspected pregnancy complication,
    wound needing treatment, anything needing a doctor, lab, or hospital).
    - referral_notes — free text: why referred, which facility/department,
    urgency (routine / urgent / emergency), instructions given. Leave out
    if requires_referral is false.

    ### Auto-handled — DO NOT collect
    - date_collected — set automatically by the system.
    - recorded_by_id — the system links the record to the admin; never ask.

    ## SANITY CHECKS before calling collect_data 🚦
    Flag (don't silently store) values that look wrong, and confirm with the
    admin: age > 120 or < 0; temperature outside 30–45 °C; pulse outside
    20–250; bp_systolic outside 50–300; height/weight that are clearly swapped
    or impossible. A typo caught now beats a corrupt record later.

    # ═══════════════════════════════════════════════════════════
    # 5. DATA RETRIEVAL WORKFLOW
    # ═══════════════════════════════════════════════════════════
    Use the `retrieve_info` tool.

    If {status} is "admin" or "field_expert" (outreach staff):
    - Collect (a) the client's name (and phone number if available, to
    disambiguate people with the same name) and (b) a JSON list of the exact
    field names they want, drawn from the Field Dictionary above. Pass both
    to `retrieve_info`.
    - If they ask for "everything", pass all field names.
    - Present results clearly and warmly. Summarize; don't dump raw JSON at them.

    If {status} is "client":
    - They may ONLY retrieve their OWN record, matched by their wa_id/phone.
    - Collect the fields they want as JSON and pass to `retrieve_info` scoped
    to them.
    - If a client asks about ANY other person's information — even a family
    member — politely decline and explain that health records are private,
    and an admin can help where appropriate.

    # ═══════════════════════════════════════════════════════════
    # 6. PRIVACY & SAFETY RULES (ABSOLUTE) 🔒
    # ═══════════════════════════════════════════════════════════
    - Health data is sensitive. Never reveal one person's data to another
    person, except admins acting in their outreach role.
    - Never list, enumerate, or "browse" records for a client.
    - Genotype, chronic conditions, and similar fields carry stigma — share
    them only with the record owner or an admin, and never volunteer them
    unprompted.
    - You collect and organize data; you do NOT diagnose. If findings look
    serious, encourage the referral flow (requires_referral) and advise
    seeing a health professional.
    - If you're unsure whether an action is permitted for {status}, don't do
    it — ask or decline politely.

    # ═══════════════════════════════════════════════════════════
    # 7. WHEN THINGS ARE UNCLEAR
    # ═══════════════════════════════════════════════════════════
    - Ambiguous field? Ask ONE short clarifying question rather than guessing.
    - Partial data is fine — records can be updated across multiple messages.
    Save what's confirmed, note what's pending.
    - If a tool call fails, tell the user simply what happened and what you'll
    try next. Never pretend a save or retrieval succeeded when it didn't.
    """

    # Admins see the live approval queue on every message. This is what keeps
    # applications from getting stuck: Meta will not deliver our broadcast to an
    # admin who hasn't messaged in 24 hours, so instead of relying on that push
    # ever landing, the queue is put in front of whichever admin next says
    # anything at all.
    if status == "admin":
        system_prompt += _pending_requests_prompt_section(session)

    chat_history_records = get_context_from_db(session, user_id, limit)
    chat_history = [{"role": "system", "content": system_prompt}]  # Add system prompt here

    for record in reversed(chat_history_records):
        if record.user_message:
            try:
                # Try to parse as JSON
                parsed = json.loads(record.user_message)
                #chat_history.append({"role": "user", "content": parsed})
                if isinstance(parsed, dict):
                    chat_history.append({"role": "user", "content": [parsed]})
                else:
                    chat_history.append({"role": "user", "content": parsed})
                    

            except (json.JSONDecodeError, TypeError):
                # Fallback: just use the raw string
                chat_history.append({"role": "user", "content": record.user_message})
        if record.agent_response:
            chat_history.append({"role": "assistant", "content": record.agent_response})

    return chat_history




# 1. Client setup (Anthropic model via the compatibility layer)
# FUNCTION CALL TOOLKITS
# chat.completions interface, but pointed at Anthropic's endpoint
client = OpenAI(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url="https://api.anthropic.com/v1/",
)
MODEL = oma_models.MAIN  # the outreach agent itself; helpers below use lighter tiers

# Trusted outreach staff — both may collect AND retrieve any beneficiary record.
# (Clients are anyone not in this set: they can only ever see their own record.)
STAFF_ROLES = {"admin", "field_expert"}




# 2. The DB-side functions
# ---------- helpers: coercion & serialization ----------

ENUM_MAP = {
    "gender": Gender,
    "marital_status": MaritalStatus,
    "level_of_education": EducationLevel,
    "consent_method": ConsentMethod,
    "malaria_test_result": TestResult,
}

DATE_FIELDS = {"date_of_birth"}
DATETIME_FIELDS = {"consent_obtained_at", "welbridg_optin_at", "education_followup_at"}
INT_FIELDS = {"age", "bp_systolic", "bp_diastolic", "pulse"}
NUMERIC_FIELDS = {"height_cm", "weight_kg", "bmi", "temperature", "blood_glucose"}
BOOL_FIELDS = {
    "informed_consent", "birth_registration_status", "requires_referral",
    "is_pregnant", "eye_condition_found",
    "welbridg_followup_optin", "has_smartphone", "uses_whatsapp",
    "education_understood",
}

# every column the agent is allowed to write
WRITABLE_FIELDS = (
    {"first_name", "last_name", "phone_number", "next_of_kin", "location",
     "occupation", "health_status", "known_chronic_conditions",
     "surgical_history", "allergies", "current_medications",
     "family_history_of_major_diseases", "genotype",
     "immunization_history", "referral_notes",
     # added for the WeAspire brief
     "outreach_event", "tally_number", "referred_to", "eye_screening_notes",
     "health_education_topics", "education_followup_notes"}
    | set(ENUM_MAP) | DATE_FIELDS | DATETIME_FIELDS
    | INT_FIELDS | NUMERIC_FIELDS | BOOL_FIELDS
)


def _coerce(field, value):
    """Convert the model's JSON value into the type the column expects."""
    if value is None or value == "":
        return None
    if field in ENUM_MAP:
        return ENUM_MAP[field](str(value).strip().lower())   # raises ValueError if invalid
    if field in DATE_FIELDS:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    if field in DATETIME_FIELDS:
        v = str(value).replace("T", " ")[:16]
        return datetime.strptime(v, "%Y-%m-%d %H:%M")
    if field in INT_FIELDS:
        return int(value)
    if field in NUMERIC_FIELDS:
        return Decimal(str(value))
    if field in BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "1")
    return str(value).strip()


def _serialize(record, fields=None):
    """Turn an OmaOutreachBeneficiaries row into a JSON-safe dict."""
    out = {}
    cols = fields or [c.name for c in OmaOutreachBeneficiaries.__table__.columns]
    for col in cols:
        if not hasattr(record, col):
            out[col] = "UNKNOWN FIELD"
            continue
        val = getattr(record, col)
        if isinstance(val, Decimal):
            val = float(val)
        elif isinstance(val, (date, datetime)):
            val = val.isoformat()
        elif hasattr(val, "value"):          # enum
            val = val.value
        out[col] = val
    return out


# ---------- TOOL 1: collect_data ----------

CONSENT_FIELDS = ("informed_consent", "consent_method", "consent_obtained_at")


def _candidate(m):
    return {"record_id": m.id, "name": f"{m.first_name} {m.last_name}",
            "location": m.location, "phone_number": m.phone_number}


def _similar_records(session, first=None, last=None, limit=10):
    """Records sharing the first name OR the surname - the people a staff
    member might mean when the exact name doesn't match. Each name is also
    checked against the other column, since first/last get swapped often."""
    from sqlalchemy import or_
    B = OmaOutreachBeneficiaries
    conds = []
    for name in {n.strip() for n in (first, last) if n and n.strip()}:
        conds += [B.first_name.ilike(f"%{name}%"), B.last_name.ilike(f"%{name}%")]
    if not conds:
        return []
    return session.query(B).filter(or_(*conds)).limit(limit).all()


def collect_data(session, recorded_by_id: int, data: dict) -> dict:
    """
    Create or update a community member's outreach health record.
    Enforces the consent gate server-side.

    Finding the right person is done HERE, not left to the model: an update
    landing on the wrong record (or a duplicate created because a surname was
    missing) is a corrupted health record. Order:
      1. record_id from a previous lookup - exact, preferred.
      2. phone number, then exact full name (case-insensitive).
      3. first name only, with exactly one person of that name -> that person.
      4. otherwise, if similar names exist -> nothing saved; the candidates are
         returned so the agent can ask which one (or pass create_new=true).
    """
    try:
        from sqlalchemy import func
        B = OmaOutreachBeneficiaries
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        phone = (data.get("phone_number") or "").strip() or None
        record_id = data.get("record_id")
        create_new = str(data.get("create_new", "")).strip().lower() in ("true", "yes", "1")

        record = None
        matched_by = None
        if record_id not in (None, ""):
            record = session.get(B, int(record_id))
            if record is None:
                return {"status": "error",
                        "message": (f"No record has id {record_id}. Nothing saved. Look the "
                                    "person up with retrieve_info and use the id it returns.")}
            matched_by = "record_id"
        elif not create_new:
            if phone:
                record = session.query(B).filter(B.phone_number == phone).first()
                matched_by = "phone" if record else None
            if record is None and first and last:
                record = (session.query(B)
                          .filter(func.lower(B.first_name) == first.lower(),
                                  func.lower(B.last_name) == last.lower())
                          .first())
                matched_by = "full name" if record else None
            if record is None and first and not last:
                same_first = (session.query(B)
                              .filter(func.lower(B.first_name) == first.lower())
                              .limit(5).all())
                if len(same_first) == 1:
                    record, matched_by = same_first[0], "the only person with that first name"
            if record is None:
                similar = _similar_records(session, first, last)
                if similar:
                    return {"status": "possible_match",
                            "message": (f"NOTHING SAVED. No record exactly matches "
                                        f"'{(first + ' ' + last).strip()}', but these people are on record. "
                                        "If the staff member means one of them, call collect_data "
                                        "again with that record_id (tell them which one you used). "
                                        "If they mean more than one could fit, ask which. Only if "
                                        "it's genuinely a new person, call again with "
                                        "create_new=true (consent required)."),
                            "candidates": [_candidate(m) for m in similar]}

        is_new = record is None

        if is_new and not (first and last):
            return {"status": "error",
                    "message": ("NOTHING SAVED. A new record needs first_name and last_name "
                                "(and location). If they meant someone already on record, "
                                "look them up with retrieve_info first.")}

        # Consent on an existing record was settled when it was created. Don't
        # let an update quietly rewrite it (a model filling in fields it was
        # never told is exactly how a false "consent given" gets stored).
        if not is_new and record.informed_consent:
            for f in CONSENT_FIELDS:
                data.pop(f, None)

        # ---- CONSENT GATE (server-side, not just prompt-side) ----
        consent_now = str(data.get("informed_consent", "")).strip().lower() in ("true", "yes", "1")
        consent_already = bool(record and record.informed_consent)
        if not (consent_now or consent_already):
            return {"status": "refused",
                    "message": ("NOTHING SAVED. Consent not confirmed. informed_consent must be "
                                "true (with consent_method and consent_obtained_at), as stated "
                                "by the staff member, before any data can be stored.")}

        if is_new:
            record = OmaOutreachBeneficiaries(
                first_name=first, last_name=last,
                location=(data.get("location") or "").strip() or "UNKNOWN",
                recorded_by_id=recorded_by_id,
            )
            session.add(record)

        # apply every recognised, non-empty field
        applied, rejected = [], {}
        for field, value in data.items():
            if field not in WRITABLE_FIELDS:
                continue
            # An update must never rename the person it matched: the name in
            # the request is how they were referred to ("Babatunde Babatunde"),
            # not a correction of the record.
            if not is_new and field in ("first_name", "last_name"):
                current = (getattr(record, field) or "").strip()
                if str(value or "").strip() and str(value).strip().lower() != current.lower():
                    rejected[field] = (f"not changed - this record's {field} is {current!r}. "
                                       "Names are only changed when explicitly asked.")
                continue
            try:
                coerced = _coerce(field, value)
                if coerced is not None:
                    setattr(record, field, coerced)
                    applied.append(field)
            except (ValueError, InvalidOperation) as e:
                rejected[field] = f"{value!r} → {e}"

        # derive BMI when possible and not explicitly supplied
        if record.height_cm and record.weight_kg and "bmi" not in data:
            h_m = float(record.height_cm) / 100
            record.bmi = Decimal(str(round(float(record.weight_kg) / (h_m ** 2), 2)))
            applied.append("bmi (computed)")

        session.commit()
        return {
            "status": "success",
            "action": "created" if is_new else "updated",
            "record_id": record.id,
            "record": f"{record.first_name} {record.last_name}",   # name it in the reply
            "matched_by": matched_by,
            "fields_saved": applied,
            "fields_rejected": rejected,   # model relays these back to the admin
        }

    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"DB error: {e}"}


# ---------- TOOL 2: retrieve_info ----------

def retrieve_info(session, requester_status: str, requester_wa_id: str,
                  requester_phone: str = None, first_name: str = None,
                  last_name: str = None, phone_number: str = None,
                  fields: list = None) -> dict:
    """
    Fetch fields from a beneficiary record.
    Admins: any record. Clients: ONLY their own, matched by their phone/wa_id.
    """
    try:
        q = session.query(OmaOutreachBeneficiaries)

        if requester_status not in STAFF_ROLES:
            # ---- privacy enforced here, regardless of what the model asks for ----
            # Non-staff (clients) can ONLY ever see their own record.
            own_phone = requester_phone or requester_wa_id
            q = q.filter(OmaOutreachBeneficiaries.phone_number == own_phone)
        else:
            if phone_number:
                q = q.filter(OmaOutreachBeneficiaries.phone_number == phone_number.strip())
            if first_name:
                q = q.filter(OmaOutreachBeneficiaries.first_name.ilike(f"%{first_name.strip()}%"))
            if last_name:
                q = q.filter(OmaOutreachBeneficiaries.last_name.ilike(f"%{last_name.strip()}%"))
            if not (phone_number or first_name or last_name):
                return {"status": "error",
                        "message": "Provide a name or phone number to search by."}

        matches = q.limit(5).all()
        if not matches:
            # Don't let "no exact match" be read as "nobody by that name". A
            # wrong or guessed surname is the usual cause, so list people who
            # share either name before concluding there's no record.
            if requester_status in STAFF_ROLES and (first_name or last_name):
                similar = _similar_records(session, first_name, last_name)
                if similar:
                    return {"status": "no_exact_match",
                            "message": (f"No record named exactly "
                                        f"'{((first_name or '') + ' ' + (last_name or '')).strip()}'. "
                                        "These records share part of that name - check whether "
                                        "the staff member means one of them before saying there "
                                        "is no record."),
                            "candidates": [_candidate(m) for m in similar]}
                return {"status": "not_found",
                        "message": (f"Nobody on record has the first name or surname "
                                    f"{' or '.join(repr(n) for n in (first_name, last_name) if n)}.")}
            return {"status": "not_found", "message": "No matching record."}
        if len(matches) > 1:
            return {"status": "ambiguous",
                    "message": ("Several records match - ask which one they mean (full name, "
                                "location or phone), then use its record_id."),
                    "candidates": [_candidate(m) for m in matches]}

        # Always identify the record, whatever fields were asked for, so a
        # follow-up save can target it by record_id.
        m = matches[0]
        return {"status": "success", "record_id": m.id,
                "name": f"{m.first_name} {m.last_name}",
                "record": _serialize(m, fields)}

    except Exception as e:
        return {"status": "error", "message": f"DB error: {e}"}
    


# ── Consent documents ────────────────────────────────────────────────────────

def extract_image_data_uri(user_input):
    """Pull the base64 image out of whatever generate_response was handed.

    Images arrive as the content-part list [{'type':'image_url', ...}]. The
    model never sees or passes this — tool arguments carry names and phone
    numbers, and the runner supplies the actual image. Megabytes of base64
    cannot travel through tool arguments, and should not.
    """
    if isinstance(user_input, list):
        for part in user_input:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    return url
    return None


def verify_consent_document(data_uri):
    """Ask the vision model whether this photo really is a signed consent form.

    Returns {'valid': bool, 'reason': str}. Errs toward rejection: storing a
    photo of something else against someone's health record, and treating it as
    consent, is worse than asking the agent to retake it.
    """
    try:
        completion = client.chat.completions.create(
            model=oma_models.WORKER,  # consent-form check (vision, yes/no judgement)
            messages=[
                {"role": "system", "content": """
                    You check photographs of CONSENT FORMS for a rural health outreach
                    programme. Decide whether the image is a genuine, usable consent
                    document.

                    Say VALID only if it plausibly shows a consent/authorisation form
                    AND carries a mark of agreement — a signature, a thumbprint, a
                    ticked box, or a written name in a signature field.

                    Say INVALID if it is:
                      - any other kind of document (a prescription, ID card, receipt,
                        lab result, referral letter)
                      - a consent form that is blank or unsigned
                      - too blurry, dark, cropped or angled to read
                      - not a document at all

                    Return STRICT JSON, nothing else:
                    {"valid": true|false, "reason": "<one short sentence>"}

                    The reason is read aloud to a field worker standing with the
                    patient, so make it specific and actionable — say WHAT is wrong
                    and what to do ("the signature area is cut off, retake including
                    the bottom of the page"), never just "invalid".
                """},
                {"role": "user", "content": [
                    {"type": "text", "text": "Is this a valid signed consent form?"},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ]},
            ],
        )
        raw = completion.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return {"valid": bool(parsed.get("valid")),
                "reason": parsed.get("reason") or "Couldn't read that clearly."}
    except json.JSONDecodeError:
        logging.error(f"verify_consent_document: non-JSON reply: {raw[:300]}")
        return {"valid": False, "reason": "I couldn't read that clearly — mind sending it again?"}
    except Exception as e:
        logging.error(f"verify_consent_document error: {e}")
        return {"valid": False, "reason": "I had trouble checking that document — try once more?"}


def store_consent_document(session, recorded_by_id, data_uri, first_name=None,
                           last_name=None, phone_number=None):
    """Verify a photographed consent form, store it, and record the consent.

    Deliberately creates a minimal beneficiary record when none exists yet:
    in the field, consent is taken BEFORE any health data is collected, so
    requiring the record to exist first would invert the actual workflow.
    collect_data then fills that same row in, matching on phone/name exactly as
    it already does.
    """
    try:
        if not data_uri:
            return {"status": "error",
                    "message": "I don't have a photo to work with — ask them to send it again."}
        if not recorded_by_id:
            return {"status": "refused",
                    "message": "Your outreach staff account isn't active yet, so I can't file that."}

        first = (first_name or "").strip()
        last = (last_name or "").strip()
        phone = (phone_number or "").strip() or None
        if not first or not last:
            return {"status": "error",
                    "message": "Whose consent form is this? I need their first and last name."}

        # 1. Verify BEFORE spending an upload on it.
        check = verify_consent_document(data_uri)
        if not check["valid"]:
            logging.info(f"store_consent_document: rejected — {check['reason']}")
            return {"status": "invalid_document", "message": check["reason"]}

        # 2. Store it.
        key, err = s3_storage.upload_data_uri(
            "consent-forms", data_uri,
            filename_hint=f"{first}-{last}".lower().replace(" ", "-"),
        )
        if err:
            return {"status": "error", "message": err}

        # 3. Attach to the record, creating a minimal one if this is first contact.
        record = None
        if phone:
            record = (session.query(OmaOutreachBeneficiaries)
                      .filter(OmaOutreachBeneficiaries.phone_number == phone).first())
        if record is None:
            record = (session.query(OmaOutreachBeneficiaries)
                      .filter(OmaOutreachBeneficiaries.first_name == first,
                              OmaOutreachBeneficiaries.last_name == last).first())
        if record is None:
            record = OmaOutreachBeneficiaries(
                first_name=first, last_name=last, phone_number=phone,
                location="UNKNOWN", recorded_by_id=recorded_by_id,
            )
            session.add(record)

        record.consent_document_key = key
        record.informed_consent = True
        record.consent_method = ConsentMethod.document
        record.consent_obtained_at = datetime.utcnow()
        session.commit()

        logging.info(f"store_consent_document: stored {key} for {first} {last}")
        return {"status": "success",
                "message": (f"Consent form for {first} {last} checked and filed. "
                            f"You can go ahead with their details now.")}
    except Exception as e:
        session.rollback()
        logging.error(f"store_consent_document error: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": "Something went wrong filing that form — try again?"}


# ── Health education follow-up (Success Indicator 3) ─────────────────────────

def _find_beneficiary(session, first_name=None, last_name=None, phone_number=None):
    """Locate one beneficiary by phone, else exact name. (record, error)."""
    phone = (phone_number or "").strip() or None
    if phone:
        rec = (session.query(OmaOutreachBeneficiaries)
               .filter(OmaOutreachBeneficiaries.phone_number == phone).first())
        if rec:
            return rec, None
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if first and last:
        rec = (session.query(OmaOutreachBeneficiaries)
               .filter(OmaOutreachBeneficiaries.first_name.ilike(first),
                       OmaOutreachBeneficiaries.last_name.ilike(last)).first())
        if rec:
            return rec, None
    return None, "I couldn't find a record for that person — check the name or phone number."


def record_education_followup(session, requester_status, understood=None, notes=None,
                              first_name=None, last_name=None, phone_number=None):
    """Log whether someone says the health education helped.

    Indicator 3 is "% of attendees who report a better understanding of
    preventive health practices", so `understood` is a boolean the analytics can
    group on to produce that percentage directly, with the free-text notes kept
    alongside for the post-outreach review.
    """
    try:
        if requester_status not in STAFF_ROLES:
            return {"status": "refused",
                    "message": "Only outreach staff can record follow-up responses."}

        record, err = _find_beneficiary(session, first_name, last_name, phone_number)
        if err:
            return {"status": "not_found", "message": err}

        if understood is not None:
            record.education_understood = bool(understood)
        if notes:
            record.education_followup_notes = str(notes).strip()
        record.education_followup_at = datetime.utcnow()
        session.commit()

        logging.info(f"record_education_followup: {record.first_name} {record.last_name} "
                     f"understood={record.education_understood}")
        return {"status": "success",
                "message": f"Noted for {record.first_name} {record.last_name}. 👍"}
    except Exception as e:
        session.rollback()
        logging.error(f"record_education_followup error: {e}")
        return {"status": "error", "message": "Couldn't save that just now — try again?"}


def send_education_followup(session, requester_status, outreach_event=None, limit=25):
    """Message opted-in beneficiaries asking whether the health advice stuck.

    Only goes to people who opted in to Welbridg follow-up AND have a phone
    number — this is precisely the remote follow-up capability the pilot exists
    to test, so a failure here is a finding, not just an error.

    HEADS UP ON DELIVERY: Meta only accepts free-form messages to someone who
    has written to the business in the last 24 hours. Beneficiaries recorded at
    an outreach have almost certainly never messaged Oma, so most of these will
    be rejected until an approved message template is in place. The counts come
    back honestly so the gap is visible rather than silent.
    """
    try:
        if requester_status != "admin":
            return {"status": "refused",
                    "message": "Only admins can send the follow-up round."}

        q = (session.query(OmaOutreachBeneficiaries)
             .filter(OmaOutreachBeneficiaries.welbridg_followup_optin == True,
                     OmaOutreachBeneficiaries.phone_number.isnot(None),
                     OmaOutreachBeneficiaries.education_understood.is_(None)))
        if outreach_event:
            q = q.filter(OmaOutreachBeneficiaries.outreach_event == outreach_event)
        people = q.limit(max(1, min(int(limit or 25), 100))).all()

        if not people:
            return {"status": "empty",
                    "message": ("Nobody's waiting on a follow-up — either everyone's been "
                                "asked already, or nobody has opted in yet.")}

        delivered, failed = 0, 0
        for p in people:
            # {{2}} in the approved template is the date they attended. Fall back
            # to the programme date if the record somehow has none, rather than
            # sending an empty parameter, which Meta rejects.
            # Built by hand rather than strftime("%-d ..."): the no-pad flag is
            # glibc-only and raises on Windows, so it would work on Railway and
            # break for anyone running this locally.
            attended = (f"{p.date_collected.day} {p.date_collected:%B %Y}"
                        if p.date_collected else "the outreach")
            ok = send_whatsapp_message(
                p.phone_number,
                (f"Hello {p.first_name}, it's Oma from Welbridg 👋 We met at the WeAspire "
                 f"Medical Outreach.\n\nJust a quick one: has the health advice you were "
                 f"given been useful — do you feel you understand how to look after your "
                 f"health better since then?\n\nA yes or no is plenty, and anything else "
                 f"you want to add is welcome."),
                # Beneficiaries almost never message Oma first, so this template
                # is the normal path here rather than the exception.
                template={
                    "name": TEMPLATE_EDUCATION_FOLLOWUP,
                    "language": TEMPLATE_LANGUAGE,
                    "params": [p.first_name, attended],
                },
            )
            if ok:
                delivered += 1
            else:
                failed += 1

        logging.info(f"send_education_followup: {delivered} delivered, {failed} failed")
        note = ""
        if failed:
            note = (f" {failed} couldn't be delivered — most likely because they haven't "
                    f"messaged Oma in the last 24 hours, which needs an approved template.")
        return {"status": "success",
                "message": f"Follow-up sent to {delivered} of {len(people)}.{note}"}
    except Exception as e:
        logging.error(f"send_education_followup error: {e}")
        return {"status": "error", "message": "Couldn't send that round just now."}


# ── Analytics ────────────────────────────────────────────────────────────────
# Whitelists, not free-form SQL. The model still interprets whatever phrasing the
# user throws at it; it just expresses the answer as parameters, so the privacy
# scoping below is enforced in Python rather than trusted to the prompt.

ANALYTICS_GROUPABLE = {
    "location", "gender", "marital_status", "level_of_education", "occupation",
    "genotype", "requires_referral", "birth_registration_status",
    "consent_method", "first_name", "last_name", "age", "date_collected",
    # WeAspire brief: screening outcomes, the pilot, and the success indicators.
    # These are what make the indicators answerable — e.g. grouping on
    # education_understood gives Indicator 3's percentage directly, and on
    # welbridg_followup_optin gives the pilot's opt-in rate.
    "outreach_event", "referred_to", "malaria_test_result", "eye_condition_found",
    "is_pregnant", "welbridg_followup_optin", "has_smartphone", "uses_whatsapp",
    "education_understood",
}

ANALYTICS_NUMERIC = {
    "age", "height_cm", "weight_kg", "bmi",
    "bp_systolic", "bp_diastolic", "pulse", "temperature", "blood_glucose",
}

# Free-text clinical columns (known_chronic_conditions, allergies, health_status,
# referral_notes ...) are deliberately absent from both sets: grouping on free
# text produces noise rather than insight, and they are the most sensitive
# columns in the table.
ANALYTICS_FILTERABLE = ANALYTICS_GROUPABLE | {"informed_consent"}

ANALYTICS_METRICS = ("count", "avg", "min", "max", "sum")


def _as_plain(v):
    """JSON-safe scalar. Aggregates come back as Decimal, dates as date, and
    enum columns as Enum members - none of which json.dumps can serialise."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "value"):          # enum member
        return v.value
    return v


def analyse_records(session, requester_status, recorded_by_id=None, metric="count",
                    group_by=None, field=None, filters=None, limit=10):
    """Aggregate reporting over the outreach beneficiary records.

    SCOPING IS THE PRIVACY CONTROL, and it is applied here rather than in the
    prompt:
      admin        -> every record, and may break results down by field agent
      field_expert -> only records they personally collected
      client       -> refused outright

    There is deliberately NO small-cell suppression. It would be the right call
    if field experts could aggregate across everyone's data — "1 person in Ilara
    has condition X" effectively names that person. But a field expert only ever
    sees records they collected themselves, so an exact count discloses nothing
    they don't already know, and suppressing small groups would break the most
    common question they have ("how many did I see today?" -> 3). If staff are
    ever given cross-agent access, suppression has to come back with it.
    """
    try:
        if requester_status not in STAFF_ROLES:
            return {"status": "refused",
                    "message": "Only outreach staff can run reports on collected records."}

        metric = (metric or "count").strip().lower()
        if metric not in ANALYTICS_METRICS:
            return {"status": "error",
                    "message": f"Unknown metric '{metric}'. Use one of: {', '.join(ANALYTICS_METRICS)}."}

        if metric != "count":
            if not field:
                return {"status": "error",
                        "message": f"'{metric}' needs a numeric field, e.g. bp_systolic or age."}
            if field not in ANALYTICS_NUMERIC:
                return {"status": "error",
                        "message": (f"'{field}' isn't a numeric field I can average. "
                                    f"Options: {', '.join(sorted(ANALYTICS_NUMERIC))}.")}

        if group_by and group_by not in ANALYTICS_GROUPABLE and group_by != "recorded_by":
            return {"status": "error",
                    "message": (f"I can't group by '{group_by}'. "
                                f"Options: {', '.join(sorted(ANALYTICS_GROUPABLE))}, recorded_by.")}

        if group_by == "recorded_by" and requester_status != "admin":
            return {"status": "refused",
                    "message": "Only admins can break results down by field agent."}

        B = OmaOutreachBeneficiaries
        conditions = []

        # ---- scope: the whole point ----
        if requester_status == "field_expert":
            if not recorded_by_id:
                return {"status": "error",
                        "message": "Your outreach staff account isn't active yet, so I can't pull your records."}
            conditions.append(B.recorded_by_id == recorded_by_id)

        for k, v in (filters or {}).items():
            if k not in ANALYTICS_FILTERABLE:
                return {"status": "error",
                        "message": (f"I can't filter on '{k}'. "
                                    f"Options: {', '.join(sorted(ANALYTICS_FILTERABLE))}.")}
            col = getattr(B, k)
            conditions.append(col.ilike(f"%{v.strip()}%") if isinstance(v, str) else col == v)

        agg = func.count(B.id) if metric == "count" else getattr(func, metric)(getattr(B, field))
        scope = "all records" if requester_status == "admin" else "records you collected"

        if group_by:
            if group_by == "recorded_by":
                label = OmaUserRegistration.username
                q = (session.query(label.label("grp"), agg.label("val"))
                     .select_from(B)
                     .join(OmaOutreachProgramUsers, OmaOutreachProgramUsers.id == B.recorded_by_id)
                     .join(OmaUserRegistration, OmaUserRegistration.id == OmaOutreachProgramUsers.user_id))
            elif group_by == "date_collected":
                label = func.date(B.date_collected)
                q = session.query(label.label("grp"), agg.label("val")).select_from(B)
            else:
                label = getattr(B, group_by)
                q = session.query(label.label("grp"), agg.label("val")).select_from(B)

            for c in conditions:
                q = q.filter(c)

            try:
                capped = max(1, min(int(limit or 10), 50))
            except (TypeError, ValueError):
                capped = 10

            rows = q.group_by(label).order_by(agg.desc()).limit(capped).all()
            if not rows:
                return {"status": "empty",
                        "scope": scope,
                        "message": "No records match that yet."}

            return {
                "status": "success",
                "metric": metric, "field": field, "group_by": group_by, "scope": scope,
                "results": [{"group": _as_plain(g), "value": _as_plain(v)} for g, v in rows],
            }

        # No grouping: one number.
        q = session.query(agg.label("val")).select_from(B)
        for c in conditions:
            q = q.filter(c)
        value = q.scalar()

        return {"status": "success", "metric": metric, "field": field,
                "scope": scope, "value": _as_plain(value)}

    except Exception as e:
        logging.error(f"analyse_records error: {e}\n{traceback.format_exc()}")
        return {"status": "error", "message": "Something went wrong running that report."}


# 3. Tool schemas + the runner

FIELD_NAMES = sorted(WRITABLE_FIELDS)

outreach_tools = [
    {
        "type": "function",
        "function": {
            "name": "collect_data",
            "description": ("Store or update a community member's outreach health record. "
                            "EXISTING person: pass record_id (from retrieve_info) plus only the "
                            "fields to change - no consent fields, no names. Call straight away "
                            "when staff give a direct, specific instruction ('add X to his "
                            "meds'); otherwise read back and wait for their yes. If you only "
                            "have a first name, pass just first_name: the tool uses the one "
                            "person with that name, or returns candidates and saves nothing. "
                            "NEW person: first_name, last_name, location and consent exactly "
                            "as the staff member stated it, after they approved your "
                            "read-back. Fields are REPLACED, so for list fields send the "
                            "existing entries plus the new one. Check the returned status: "
                            "only 'success' means anything was saved."),
            "parameters": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "integer",
                                  "description": "The person's record id from retrieve_info. Use it whenever you have it."},
                    "create_new": {"type": "boolean",
                                   "description": ("Only when the staff member confirmed this is a NEW person "
                                                   "despite similar names on record.")},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "next_of_kin": {"type": "string"},
                    "location": {"type": "string"},
                    "informed_consent": {"type": "boolean"},
                    "consent_method": {"type": "string", "enum": ["verbal", "signature", "thumbprint"]},
                    "consent_obtained_at": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                    "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                    "age": {"type": "integer"},
                    "gender": {"type": "string", "enum": ["male", "female"]},
                    "marital_status": {"type": "string", "enum": ["single", "married", "divorced", "widowed"]},
                    "occupation": {"type": "string"},
                    "level_of_education": {"type": "string", "enum": ["none", "primary", "secondary", "tertiary"]},
                    "height_cm": {"type": "number"},
                    "weight_kg": {"type": "number"},
                    "bmi": {"type": "number"},
                    "bp_systolic": {"type": "integer"},
                    "bp_diastolic": {"type": "integer"},
                    "pulse": {"type": "integer"},
                    "temperature": {"type": "number", "description": "°C, 1 decimal place"},
                    "health_status": {"type": "string"},
                    "known_chronic_conditions": {"type": "string"},
                    "surgical_history": {"type": "string"},
                    "allergies": {"type": "string"},
                    "current_medications": {"type": "string"},
                    "family_history_of_major_diseases": {"type": "string"},
                    "genotype": {"type": "string", "description": "e.g. AA, AS, SS, AC"},
                    "immunization_history": {"type": "string"},
                    "birth_registration_status": {"type": "boolean"},
                    "requires_referral": {"type": "boolean"},
                    "referral_notes": {"type": "string"},
                },
                # Nothing is forced: requiring consent here made the model fill
                # in informed_consent=true on simple updates. collect_data
                # itself enforces names/location/consent for new records.
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_info",
            "description": ("Fetch stored fields from a beneficiary's outreach record, and find "
                            "WHO someone is. For staff: search with whatever you have - a first "
                            "name alone is fine. Don't guess a surname you weren't given; a "
                            "wrong one just fails to match. The result includes record_id and "
                            "full name; use record_id for any save that follows. "
                            "'no_exact_match' lists people with similar names: it does NOT mean "
                            "there's no record. For clients the system automatically scopes to "
                            "their own record."),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone_number": {"type": "string"},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string", "enum": FIELD_NAMES + ["date_collected", "id"]},
                        "description": "Exact field names to return. Omit for the full record.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_my_document",
            "description": (
                "Save a photo the user has SENT and asked you to keep for them — a receipt, "
                "a prescription, a card, a form. Personal filing, nothing to do with outreach "
                "records. Call it when they ask you to keep a photo: either one attached to "
                "this message, or the last photo they sent in the past 30 minutes ('save that "
                "picture', 'keep the one I sent') - the tool finds that one itself, so never ask "
                "them to resend it. Pass a short description in THEIR words, since that's what they'll "
                "search by later. Do NOT use this for a beneficiary's consent form — that's "
                "store_consent_document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": ("Short label in the user's own words, e.g. 'clinic "
                                        "receipt from March' or 'my NHIS card'."),
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_document",
            "description": (
                "SENDS a saved photo to the user. Call ONLY when the user explicitly asks to "
                "see or get back a file they saved ('send me my clinic receipt'). Never call "
                "it to check, verify or look anything up, and never while working on outreach "
                "records: every call sends the picture to them again. Oma sends the picture "
                "itself; you just add a short line. If several could match you'll be told and "
                "should ask which one. To see what's saved, use list_my_documents instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Roughly what they asked for, e.g. 'the clinic receipt'.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_documents",
            "description": (
                "List the files the user has saved with you, by name and date. Sends nothing. "
                "Use it only when they ask what you're holding for them."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_consent_document",
            "description": (
                "OUTREACH STAFF ONLY. Call this when the user has SENT A PHOTO of a signed "
                "consent form for someone they are onboarding. Oma checks the photo really "
                "is a signed consent form, files it, and records consent — so calling this "
                "successfully satisfies the consent requirement and you can go straight on "
                "to collect_data without asking for verbal confirmation as well. "
                "Do NOT call it when no photo was sent in this message, and do not call it "
                "for any other kind of document. You do not pass the image yourself — just "
                "say who it belongs to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string", "description": "First name of the person consenting."},
                    "last_name": {"type": "string", "description": "Last name of the person consenting."},
                    "phone_number": {"type": "string", "description": "Their phone number, if known."},
                },
                "required": ["first_name", "last_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_education_followup",
            "description": (
                "OUTREACH STAFF ONLY. Record whether someone says the health education they "
                "were given has been useful. Use it when a beneficiary replies to a follow-up, "
                "or when staff relay what someone told them. 'understood' true/false feeds the "
                "programme's success measure directly, so set it whenever their answer is clear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone_number": {"type": "string", "description": "Preferred — unambiguous."},
                    "understood": {"type": "boolean",
                                   "description": "True if they report understanding preventive health better."},
                    "notes": {"type": "string", "description": "Anything else they said, in their words."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_education_followup",
            "description": (
                "ADMINS ONLY. Send the health-education follow-up question to beneficiaries who "
                "opted in to Welbridg follow-up and haven't answered yet. Use when an admin asks "
                "to run or send the follow-up round. Optionally scope to one outreach event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "outreach_event": {"type": "string",
                                       "description": "e.g. 'akure-2026'. Omit for everyone outstanding."},
                    "limit": {"type": "integer", "description": "Max people to message. Default 25."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyse_records",
            "description": (
                "OUTREACH STAFF ONLY. Answer analytical / statistical questions about the "
                "collected health records — counts, breakdowns, averages, rankings. Use it "
                "for anything of the form 'how many...', 'what's the most common...', "
                "'what's the average...', 'break that down by...', 'how many did I do "
                "today'. Scoping is automatic: admins get every record, field experts get "
                "only the records they personally collected — you do not need to filter for "
                "that. Only admins may group by recorded_by (per-agent activity)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": list(ANALYTICS_METRICS),
                        "description": "count (default) for how-many, or avg/min/max/sum over a numeric field.",
                    },
                    "field": {
                        "type": "string",
                        "enum": sorted(ANALYTICS_NUMERIC),
                        "description": "The numeric column to aggregate. Required unless metric is count.",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": sorted(ANALYTICS_GROUPABLE) + ["recorded_by"],
                        "description": ("Break the answer down by this column. Omit for a single "
                                        "overall number. 'recorded_by' groups by field agent and "
                                        "is admin-only. 'date_collected' groups by day."),
                    },
                    "filters": {
                        "type": "object",
                        "description": ("Optional equality/contains filters, e.g. "
                                        "{\"location\": \"Ilara\", \"gender\": \"female\"}. "
                                        "Text values match loosely."),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max groups to return, highest first. Default 10, capped at 50.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_join_request",
            "description": (
                "ADMIN ONLY. Approve or decline someone waiting to join the outreach "
                "programme. The pending queue, with each request_id, is listed in your "
                "system prompt. Call this when the admin clearly decides on an applicant "
                "in any phrasing - 'yes', 'approve him', 'please do', 'no, I don't know "
                "them'. Do NOT call it for unrelated conversation that happens to contain "
                "'ok' or 'sure'. If several people are waiting and the admin is vague "
                "about which, ask them first rather than guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "integer",
                        "description": "The request_id from the approval queue in your system prompt.",
                    },
                    "approved": {
                        "type": "boolean",
                        "description": "true to approve and enrol them, false to decline.",
                    },
                },
                "required": ["request_id", "approved"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "promote_user",
            "description": (
                "ADMIN ONLY. Add or promote an already-registered Oma user into an outreach "
                "role (field_expert or admin). Use when an admin says something like "
                "'make Musa a field agent', 'add +2348012345678 as an admin', or "
                "'promote Adaeze to admin'. The person is notified automatically. "
                "This tool can ONLY promote - it can never demote, remove a role, or "
                "downgrade an existing admin. If an admin asks you to demote or remove "
                "someone, tell them the Welbridg team has to do that directly; do not call "
                "this tool for it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_phone": {
                        "type": "string",
                        "description": ("The person's WhatsApp number with country code, digits "
                                        "only. Strongly preferred over name - it is unambiguous."),
                    },
                    "target_name": {
                        "type": "string",
                        "description": ("The person's registered username. Only use when no phone "
                                        "number was given; an ambiguous name is rejected."),
                    },
                    "role": {
                        "type": "string",
                        "enum": ["field_expert", "admin"],
                        "description": "Role to grant. Defaults to field_expert if unstated.",
                    },
                },
            },
        },
    },
]


def get_recorded_by_id(session, user_id: int):
    """
    user_id (OmaUserRegistration.id) → their active OmaOutreachProgramUsers.id.
    Returns None if they're not an active program member.
    """
    if not user_id:
        return None
    prog_user = (
        session.query(OmaOutreachProgramUsers)
        .filter(
            OmaOutreachProgramUsers.user_id == user_id,
            OmaOutreachProgramUsers.is_active == True,
        )
        .first()
    )
    return prog_user.id if prog_user else None



# MAIN AGENT RUN
def run_outreach_agent(session, user_input, user_id, username, wa_id,
                       date_n_time, users_country, message_type,
                       status):
    """
    recorded_by_id = the admin's OmaOutreachProgramUsers.id (look it up once
    from their wa_id before calling this).
    """
    # resolve once, only if they're staff — clients skip the query entirely
    recorded_by_id = get_recorded_by_id(session, user_id) if status in STAFF_ROLES else None
    
    chat_history = fetch_chat_history_for_outreach_programme(
        session, user_id, username, wa_id, date_n_time,
        users_country, message_type, status,
    )
    chat_history.append({"role": "user", "content": user_input})
 
    # agentic loop: keep going while the model wants tools (max 5 rounds)
    for _ in range(5):
        completion = client.chat.completions.create(
            model=MODEL,
            messages=chat_history,
            tools=outreach_tools,
        )
        msg = completion.choices[0].message

        if not msg.tool_calls:
            chat_history.append({"role": "assistant", "content": msg.content})
            return msg.content

        # record the assistant's tool-call turn, then answer each call
        chat_history.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        for tc in msg.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"TOOL CALL → {fn}({args})")

            if fn == "collect_data":
                if status not in STAFF_ROLES:
                    result = {"status": "refused",
                              "message": "Only outreach staff (admins or field experts) can store records."}
                elif not recorded_by_id:
                    # staff role in the chat, but no active program-user row to attribute to
                    result = {"status": "refused",
                              "message": "Your outreach staff account isn't active yet, so records can't be attributed to you."}
                else:
                    result = collect_data(session, recorded_by_id, args)

            elif fn == "retrieve_info":
                result = retrieve_info(
                    session,
                    requester_status=status,
                    requester_wa_id=wa_id,
                    first_name=args.get("first_name"),
                    last_name=args.get("last_name"),
                    phone_number=args.get("phone_number"),
                    fields=args.get("fields"),
                )

            elif fn == "save_my_document":
                result = documents.save_user_document(
                    session, user_id=user_id, wa_id=wa_id,
                    data_uri=extract_image_data_uri(user_input),
                    description=args.get("description"),
                )

            elif fn == "get_my_document":
                result = documents.send_user_document(
                    session, user_id=user_id, wa_id=wa_id,
                    query=args.get("description") or "",
                )

            elif fn == "list_my_documents":
                result = documents.list_user_documents(session, user_id)

            elif fn == "store_consent_document":
                # The image comes from the incoming message, NOT from the model.
                # Tool arguments carry the person's name; megabytes of base64
                # can't travel that way and shouldn't.
                if status not in STAFF_ROLES:
                    result = {"status": "refused",
                              "message": "Only outreach staff can file consent forms."}
                else:
                    result = store_consent_document(
                        session,
                        recorded_by_id=recorded_by_id,
                        data_uri=extract_image_data_uri(user_input),
                        first_name=args.get("first_name"),
                        last_name=args.get("last_name"),
                        phone_number=args.get("phone_number"),
                    )

            elif fn == "record_education_followup":
                result = record_education_followup(
                    session, requester_status=status,
                    understood=args.get("understood"),
                    notes=args.get("notes"),
                    first_name=args.get("first_name"),
                    last_name=args.get("last_name"),
                    phone_number=args.get("phone_number"),
                )

            elif fn == "send_education_followup":
                result = send_education_followup(
                    session, requester_status=status,
                    outreach_event=args.get("outreach_event"),
                    limit=args.get("limit") or 25,
                )

            elif fn == "analyse_records":
                # recorded_by_id is already resolved above for staff; passing it
                # in is what scopes a field expert to their own collections.
                result = analyse_records(
                    session,
                    requester_status=status,
                    recorded_by_id=recorded_by_id,
                    metric=args.get("metric") or "count",
                    group_by=args.get("group_by"),
                    field=args.get("field"),
                    filters=args.get("filters"),
                    limit=args.get("limit") or 10,
                )

            elif fn == "decide_join_request":
                if status != "admin":
                    result = {"status": "refused",
                              "message": "Only outreach admins can approve applications."}
                else:
                    req = (session.query(OmaOutreachJoinRequest)
                           .filter_by(id=args.get("request_id")).first())
                    if req is None:
                        result = {"status": "not_found",
                                  "message": "I couldn't find that application — it may already be handled."}
                    else:
                        admin_account = find_active_admin_by_phone(session, wa_id)
                        result = resolve_vouch_confirmation(
                            session, req, bool(args.get("approved")), resolved_by=admin_account
                        )

            elif fn == "promote_user":
                # promote_user re-checks the role itself; gating here too keeps the
                # refusal cheap and keeps the rule visible at the call site.
                result = promote_user(
                    session,
                    actor_status=status,
                    target_phone=args.get("target_phone"),
                    target_name=args.get("target_name"),
                    role=args.get("role") or "field_expert",
                )

            else:
                logging.error(f"run_outreach_agent: model called unknown tool {fn!r}")
                result = {"status": "error", "message": f"Unknown tool {fn}"}

            chat_history.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })
        # loop continues → model sees the results and composes its WhatsApp reply

    return "Sorry, that took too many steps 😅 — mind trying again?"




""" To run all the above, we need to run the ffg 

run_outreach_agent(session, user_input, user_id, username, wa_id,
                       date_n_time, age_details, users_country, message_type,
                       status, recorded_by_id=None)
                       
                       
"""


# FINALLY JUST A FUNCTION TO GET THE USERS OTREACH STATUS FROM THE DB
def get_user_outreach_status(session, wa_id: str) -> dict:
    """
    Resolve a WhatsApp ID to the person's role in the outreach program.

    Returns a dict:
      {"status": "admin" | "field_expert" | "client",
       "recorded_by_id": int | None,     # OmaOutreachProgramUsers.id (for collect_data)
       "user_id": int | None}            # OmaUserRegistration.id
    Anyone not found in the program tables defaults to "client".
    """
    try:
        wa_id = (wa_id or "").strip()

        # wa_id → registered account (wa_id is the phone number in intl format)
        account = (
            session.query(OmaUserRegistration)
            .filter(OmaUserRegistration.phone_number == wa_id)
            .first()
        )
        if account is None:
            return {"status": "client", "recorded_by_id": None, "user_id": None}

        # account → active outreach program membership
        prog_user = (
            session.query(OmaOutreachProgramUsers)
            .filter(
                OmaOutreachProgramUsers.user_id == account.id,
                OmaOutreachProgramUsers.is_active == True,
            )
            .first()
        )
        if prog_user is None:
            return {"status": "client", "recorded_by_id": None, "user_id": account.id}

        return {
            "status": prog_user.role.value,        # "admin" or "field_expert"
            "recorded_by_id": prog_user.id,
            "user_id": account.id,
        }

    except Exception as e:
        print(f"get_user_outreach_status error: {e}")
        # fail CLOSED: unknown → least-privileged role
        return {"status": "client", "recorded_by_id": None, "user_id": None}


# ═══════════════════════════════════════════════════════════════════════════
#  OUTREACH ADMIN / FIELD-EXPERT ONBOARDING
#  Everything below powers how someone BECOMES an outreach member:
#    Part 0 — add_outreach_program_user : the writer that grants a role
#    Part 1 — whitelist                 : auto-enrol pre-approved phone numbers
#    Part 2 — vouch flow                : an admin confirms a newcomer in the field
#  (Beneficiary data collection/retrieval is handled by run_outreach_agent above.)
# ═══════════════════════════════════════════════════════════════════════════

# Words that mean "I want the insurance side", used to let outreach staff out of
# the outreach agent for one message. Deliberately narrow: each of these has no
# meaning inside the outreach programme.
INSURANCE_KEYWORDS = (
    "insurance", "axa", "hygeia", "policy", "premium",
    "coverage", "hmo", "health plan",
)


def decide_route(session, wa_id, message_body, user_event):
    """Which agent answers this message: "outreach" or "regular".

    THIS IS THE ONE PLACE ROUTING IS DECIDED — change the policy here.

    Why this exists: what_is_users_msg_for judges a single message with no idea
    who sent it, so an enrolled field agent saying "Hi", or a follow-up like
    "add that she's married", classifies as regular/unsure and lands in the
    insurance agent. Someone who joined to do outreach work shouldn't have to
    re-announce that on every message.

    Policy:
      - Enrolled outreach STAFF (admin / field_expert) get the outreach agent for
        everything, greetings and context-free follow-ups included.
      - ...unless the message explicitly mentions insurance, so staff can still
        ask about AXA/Hygeia. Delete that check to make staff outreach-only.
      - Everyone else is unchanged: the per-message classification decides, so
        the insurance path behaves exactly as it did before.
    """
    try:
        status = (get_user_outreach_status(session, wa_id) or {}).get("status", "client")
    except Exception as e:
        # A routing lookup must never break the conversation - fall back to the
        # old behaviour, which is what non-outreach users get anyway.
        logging.error(f"decide_route: status lookup failed for {wa_id}: {e}")
        return "outreach" if user_event == "outreach" else "regular"

    if status in STAFF_ROLES:
        text = (_extract_text(message_body) or "").lower()
        if any(k in text for k in INSURANCE_KEYWORDS):
            logging.info(f"decide_route: staff +{wa_id} asked about insurance -> regular")
            return "regular"
        logging.info(f"decide_route: +{wa_id} is outreach '{status}' -> outreach")
        return "outreach"

    route = "outreach" if user_event == "outreach" else "regular"
    logging.info(f"decide_route: +{wa_id} is '{status}', classifier '{user_event}' -> {route}")
    return route


def create_outreach_tables():
    """Create the outreach tables (whitelist + join requests) if they don't exist.
    Safe to run repeatedly. Run this once after deploying this change."""
    Base.metadata.create_all(engine)


def _normalize_phone(num):
    """WhatsApp/Twilio numbers arrive in a few shapes ('whatsapp:+234...', '+234 ...').
    Reduce them all to bare international digits, e.g. '2348166936127'."""
    if not num:
        return ""
    s = str(num).strip().replace("whatsapp:", "").replace(" ", "").replace("-", "")
    if s.startswith("+"):
        s = s[1:]
    return s


def _extract_text(message_body):
    """Pull the plain text out of whatever generate_response was handed
    (a raw string, or the [{'type': 'text', 'text': ...}, ...] list)."""
    if isinstance(message_body, str):
        return message_body
    if isinstance(message_body, list):
        for part in message_body:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text", "") or ""
    if isinstance(message_body, dict):
        return message_body.get("text", "") or ""
    return ""


# ── Part 0: the missing writer — grant someone an outreach role ───────────────

def add_outreach_program_user(session, user_id, role="field_expert"):
    """Enrol a registered user (OmaUserRegistration.id) into the outreach program
    with the given role. Idempotent: calling it twice reactivates and returns the
    existing row rather than adding a second one.

    There is now a real (user_id, role) unique constraint on the table backing
    this up — on an existing database it needs the ALTER in the outreach setup
    notes, since create_all() only builds new tables and never alters old ones."""
    try:
        role_enum = role if isinstance(role, OutreachRole) else OutreachRole(str(role).strip().lower())
        existing = (
            session.query(OmaOutreachProgramUsers)
            .filter(
                OmaOutreachProgramUsers.user_id == user_id,
                OmaOutreachProgramUsers.role == role_enum,
            )
            .first()
        )
        if existing:
            if not existing.is_active:
                existing.is_active = True
                session.commit()
            return existing

        prog_user = OmaOutreachProgramUsers(user_id=user_id, role=role_enum, is_active=True)
        session.add(prog_user)
        session.commit()
        return prog_user
    except Exception as e:
        session.rollback()
        print(f"add_outreach_program_user error: {e}")
        return None


# ── Part 1: whitelist — pre-approved phone numbers ────────────────────────────

def add_approved_contact(session, phone_number, role, name=None, added_by=None):
    """Ops/seed helper — whitelist a phone number for an outreach role.
    Use this (once per person, from a script or admin tool) to populate the
    list of pre-approved admins/field_experts. Upserts on phone_number."""
    try:
        phone = _normalize_phone(phone_number)
        role_enum = role if isinstance(role, OutreachRole) else OutreachRole(str(role).strip().lower())
        contact = (
            session.query(OmaOutreachApprovedContact)
            .filter(OmaOutreachApprovedContact.phone_number == phone)
            .first()
        )
        if contact:
            contact.role = role_enum
            if name:
                contact.name = name
            if added_by:
                contact.added_by = added_by
        else:
            contact = OmaOutreachApprovedContact(
                phone_number=phone, role=role_enum, name=name, added_by=added_by
            )
            session.add(contact)
        session.commit()
        return contact
    except Exception as e:
        session.rollback()
        print(f"add_approved_contact error: {e}")
        return None


def check_outreach_whitelist(session, wa_id):
    """Is this wa_id pre-approved? Returns
    {'whitelisted': bool, 'role': 'admin'|'field_expert'|None, 'name': str|None}."""
    try:
        phone = _normalize_phone(wa_id)
        contact = (
            session.query(OmaOutreachApprovedContact)
            .filter(OmaOutreachApprovedContact.phone_number == phone)
            .first()
        )
        if not contact:
            return {"whitelisted": False, "role": None, "name": None}
        return {"whitelisted": True, "role": contact.role.value, "name": contact.name}
    except Exception as e:
        print(f"check_outreach_whitelist error: {e}")
        return {"whitelisted": False, "role": None, "name": None}


def enroll_from_whitelist(session, user_id, wa_id):
    """If wa_id is whitelisted, create their OmaOutreachProgramUsers row and mark
    the whitelist entry enrolled. Returns {'enrolled': bool, 'role': str|None}."""
    wl = check_outreach_whitelist(session, wa_id)
    if not wl["whitelisted"]:
        return {"enrolled": False, "role": None}

    prog_user = add_outreach_program_user(session, user_id, wl["role"])
    if prog_user is None:
        return {"enrolled": False, "role": None}

    try:
        phone = _normalize_phone(wa_id)
        contact = (
            session.query(OmaOutreachApprovedContact)
            .filter(OmaOutreachApprovedContact.phone_number == phone)
            .first()
        )
        if contact:
            contact.is_enrolled = True
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"enroll_from_whitelist mark error: {e}")

    return {"enrolled": True, "role": wl["role"]}


# ── Part 2: the vouch flow ────────────────────────────────────────────────────

# Approved message templates (WhatsApp Manager). Names and parameter counts must
# match EXACTLY what Meta approved — a mismatch is rejected at send time, not at
# deploy time, so it surfaces as a silent non-delivery.
TEMPLATE_ADMIN_APPROVAL = "outreach_admin_approval_request"      # {{1}} admin, {{2}} applicant, {{3}} role
TEMPLATE_EDUCATION_FOLLOWUP = "outreach_education_followup"      # {{1}} first name, {{2}} outreach date
TEMPLATE_LANGUAGE = "en"

# Meta's codes for "you can't send free-form to this person right now". 131047 is
# the 24-hour window having closed; 470 is the older re-engagement error. Both
# mean a template is the only way through. Deliberately does NOT include 131026
# ("undeliverable"), which usually means the number isn't on WhatsApp at all —
# retrying that as a template just wastes a paid conversation.
WINDOW_CLOSED_ERROR_CODES = {131047, 470}


def _meta_error_code(resp):
    """Meta's numeric error code from a failed send, or None."""
    try:
        return ((resp.json() or {}).get("error") or {}).get("code")
    except Exception:
        return None


def send_whatsapp_message(to_number, body_text, template=None):
    """Proactively send a WhatsApp message. Used by the outreach flow to reach
    admins (approval broadcasts) and requesters (outcome notifications).

    Talks to Meta's Cloud API directly with os.getenv rather than reusing
    whatsapp_utils.send_message, because that reads current_app.config and
    importing it here would be circular:
        whatsapp_utils -> fresh_version_with_new_db -> functions_outreach

    NOTE ON THE 24-HOUR WINDOW: Meta only accepts free-form messages to someone
    who has messaged the business within the last 24 hours. An admin who has
    been quiet longer will reject with error 131047 and needs an approved
    message template instead. The failure is logged loudly rather than
    swallowed, because a silently undelivered approval request looks identical
    to nobody having responded yet.
    """
    try:
        token = os.getenv("ACCESS_TOKEN")
        version = os.getenv("VERSION")
        phone_number_id = os.getenv("PHONE_NUMBER_ID")
        if not (token and version and phone_number_id):
            logging.error(
                "send_whatsapp_message: missing ACCESS_TOKEN / VERSION / PHONE_NUMBER_ID"
            )
            return False

        url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {token}",
                   "Content-type": "application/json"}
        to = _normalize_phone(to_number)

        # 1. Free-form first. Inside the 24-hour window this is free, reads
        #    naturally, and carries the full message. Only when Meta refuses it
        #    do we fall back to a template, which costs money per conversation
        #    and is limited to the approved wording.
        resp = requests.post(
            url, headers=headers, timeout=(10, 30),
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body_text},
            },
        )
        if resp.status_code < 400:
            logging.info(f"send_whatsapp_message delivered to {to_number} (free-form)")
            return True

        code = _meta_error_code(resp)
        if not (template and code in WINDOW_CLOSED_ERROR_CODES):
            logging.error(
                f"send_whatsapp_message failed for {to_number}: "
                f"HTTP {resp.status_code} error code {code} body: {resp.text}"
            )
            return False

        # 2. The window has closed and we have an approved template for this.
        logging.info(
            f"send_whatsapp_message: 24h window closed for {to_number} (code {code}) "
            f"- falling back to template {template.get('name')!r}"
        )
        params = [{"type": "text", "text": str(p)} for p in (template.get("params") or [])]
        t_resp = requests.post(
            url, headers=headers, timeout=(10, 30),
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": {
                    "name": template["name"],
                    "language": {"code": template.get("language", TEMPLATE_LANGUAGE)},
                    "components": ([{"type": "body", "parameters": params}] if params else []),
                },
            },
        )
        if t_resp.status_code >= 400:
            # Usually a parameter-count mismatch against what Meta approved, so
            # log the body - it names the expected count.
            logging.error(
                f"send_whatsapp_message: template {template.get('name')!r} failed for "
                f"{to_number}: HTTP {t_resp.status_code} body: {t_resp.text}"
            )
            return False
        logging.info(f"send_whatsapp_message delivered to {to_number} (template)")
        return True
    except Exception as e:
        logging.error(f"send_whatsapp_message error for {to_number}: {e}")
        return False


def find_active_admin_by_phone(session, phone):
    """Return the OmaUserRegistration for an ACTIVE outreach ADMIN with this phone,
    else None. A voucher must be an admin — a field_expert cannot vouch."""
    phone = _normalize_phone(phone)
    account = (
        session.query(OmaUserRegistration)
        .filter(OmaUserRegistration.phone_number == phone)
        .first()
    )
    if not account:
        return None
    prog = (
        session.query(OmaOutreachProgramUsers)
        .filter(
            OmaOutreachProgramUsers.user_id == account.id,
            OmaOutreachProgramUsers.role == OutreachRole.admin,
            OmaOutreachProgramUsers.is_active == True,
        )
        .first()
    )
    return account if prog else None


def get_all_active_admins(session):
    """Every ACTIVE outreach admin, as OmaUserRegistration rows.

    This is the audience for approval broadcasts. Field experts are excluded on
    purpose — they can collect and retrieve data, but only admins decide who
    joins.
    """
    rows = (
        session.query(OmaUserRegistration)
        .join(OmaOutreachProgramUsers,
              OmaOutreachProgramUsers.user_id == OmaUserRegistration.id)
        .filter(
            OmaOutreachProgramUsers.role == OutreachRole.admin,
            OmaOutreachProgramUsers.is_active == True,
        )
        .all()
    )
    # A user could in principle hold more than one program row; de-dupe by id.
    seen, admins = set(), []
    for r in rows:
        if r.id not in seen:
            seen.add(r.id)
            admins.append(r)
    return admins


def broadcast_join_request(session, request):
    """Ask EVERY active admin to approve this request; first to reply wins.

    Replaces the old flow where the applicant had to name an admin themselves —
    that dead-ended for anyone who didn't know one personally, and needed the
    applicant to supply a phone number we then had to verify.

    Returns a dict whose 'message' is what Oma says back to the APPLICANT.
    """
    try:
        admins = get_all_active_admins(session)

        if not admins:
            # No admins exist yet (fresh deployment). Park the request rather
            # than bouncing the applicant — the team can approve it in the db,
            # and it will be picked up as soon as an admin is seeded.
            request.stage = JoinRequestStage.awaiting_admin_confirmation
            session.commit()
            logging.error(
                "broadcast_join_request: NO ACTIVE ADMINS - request %s is parked. "
                "Seed an admin into oma_outreach_prog_users to unblock approvals."
                % request.id
            )
            return {
                "status": "no_admins",
                "message": ("Thanks — you're registered! 🎉 Your outreach application is in the "
                            "queue for our team to confirm. I'll message you the moment you're "
                            "approved. If it's urgent, email hi@welbridg.com."),
            }

        request.stage = JoinRequestStage.awaiting_admin_confirmation
        session.commit()

        role_label = request.requested_role.value.replace("_", " ")
        delivered = 0
        for admin in admins:
            requester = request.requester_name or "Someone"
            ok = send_whatsapp_message(
                admin.phone_number,
                (f"Hi {admin.username}, it's Oma from Welbridg. "
                 f"{requester} (+{request.requester_wa_id}) has applied to join "
                 f"the WeAspire Medical Outreach as a {role_label}.\n\n"
                 f"Do you know this person and confirm they should be added? "
                 f"Reply *YES* to approve or *NO* to decline.\n\n"
                 f"(Every admin got this — whoever answers first settles it.)"),
                # Admins who haven't messaged Oma in 24h would otherwise never
                # hear about an application. Parameters must line up with the
                # approved template: {{1}} admin, {{2}} applicant, {{3}} role.
                template={
                    "name": TEMPLATE_ADMIN_APPROVAL,
                    "language": TEMPLATE_LANGUAGE,
                    "params": [admin.username, requester, role_label],
                },
            )
            if ok:
                delivered += 1

        logging.info(
            f"broadcast_join_request: request {request.id} sent to {delivered}/{len(admins)} admins"
        )

        if delivered == 0:
            # Admins exist but none were reachable — almost always Meta's 24-hour
            # window. The request stays pending and any admin can still approve
            # it by messaging Oma, so don't tell the applicant it failed.
            return {
                "status": "notify_failed",
                "message": ("Thanks — you're registered! 🎉 Your outreach application is with our "
                            "admins for confirmation. I'll let you know as soon as it's approved."),
            }

        return {
            "status": "awaiting_admin",
            "message": ("Thanks — you're registered! 🎉 I've asked our outreach admins to confirm "
                        "you, and I'll message you the moment one of them does. 😊"),
        }
    except Exception as e:
        session.rollback()
        logging.error(f"broadcast_join_request error: {e}")
        return {"status": "error",
                "message": "Something went wrong starting your application — mind trying again?"}


def get_open_join_request_for_requester(session, wa_id):
    """The requester's live (unresolved) join request, if any."""
    phone = _normalize_phone(wa_id)
    return (
        session.query(OmaOutreachJoinRequest)
        .filter(
            OmaOutreachJoinRequest.requester_wa_id == phone,
            OmaOutreachJoinRequest.stage.in_([
                JoinRequestStage.awaiting_admin_details,
                JoinRequestStage.awaiting_admin_confirmation,
            ]),
        )
        .order_by(OmaOutreachJoinRequest.created_at.desc())
        .first()
    )


def get_pending_confirmation_for_admin(session, wa_id):
    """The request this sender should be answering, or None.

    Broadcast model: a request is not addressed to one named admin any more, so
    ANY active admin may answer ANY request still awaiting confirmation. We
    return the OLDEST unresolved one so the queue drains fairly (first in, first
    decided) instead of admins repeatedly being shown the newest applicant.

    Returns None when the sender is not an active admin, which is what makes
    handle_vouch_message fall through for everyone else.
    """
    if find_active_admin_by_phone(session, wa_id) is None:
        return None

    return (
        session.query(OmaOutreachJoinRequest)
        .filter(
            OmaOutreachJoinRequest.stage == JoinRequestStage.awaiting_admin_confirmation,
        )
        .order_by(OmaOutreachJoinRequest.created_at.asc())
        .first()
    )


def start_vouch_request(session, wa_id, requester_name, requested_role="field_expert", user_id=None):
    """Open a vouch request in the 'awaiting_admin_details' stage. If the requester
    already has a live request, return that one instead of creating a duplicate."""
    try:
        phone = _normalize_phone(wa_id)
        existing = get_open_join_request_for_requester(session, phone)
        if existing:
            return existing
        role_enum = (requested_role if isinstance(requested_role, OutreachRole)
                     else OutreachRole(str(requested_role).strip().lower()))
        req = OmaOutreachJoinRequest(
            requester_user_id=user_id,
            requester_wa_id=phone,
            requester_name=requester_name,
            requested_role=role_enum,
            stage=JoinRequestStage.awaiting_admin_details,
        )
        session.add(req)
        session.commit()
        return req
    except Exception as e:
        session.rollback()
        print(f"start_vouch_request error: {e}")
        return None


def submit_vouch_admin_details(session, request, admin_name, admin_phone):
    """The requester named an admin. Verify that admin is real & active, move the
    request to 'awaiting_admin_confirmation', and message the admin.
    Returns a dict whose 'message' is what Oma should say back to the requester."""
    try:
        admin_account = find_active_admin_by_phone(session, admin_phone)
        if admin_account is None:
            return {"status": "admin_not_found",
                    "message": ("I couldn't find an active outreach *admin* with that phone number. "
                                "Double-check the number (with country code), or give me a different "
                                "admin who can vouch for you.")}

        request.vouching_admin_name = admin_name
        request.vouching_admin_phone = _normalize_phone(admin_phone)
        request.vouching_admin_user_id = admin_account.id
        request.stage = JoinRequestStage.awaiting_admin_confirmation
        session.commit()

        role_label = request.requested_role.value.replace("_", " ")
        sent = send_whatsapp_message(
            admin_account.phone_number,
            (f"Hi {admin_account.username}, it's Oma from Welbridg. "
             f"{request.requester_name or 'Someone'} (+{request.requester_wa_id}) wants to join the "
             f"WeAspire Medical Outreach as a {role_label}, and named you as an admin who can vouch for them.\n\n"
             f"Do you know this person and confirm they should be added? Reply *YES* to approve or *NO* to decline."))

        if not sent:
            return {"status": "notify_failed",
                    "message": ("I've saved your request but couldn't reach that admin just now. "
                                "I'll keep it pending — please check back shortly.")}

        return {"status": "awaiting_admin",
                "message": (f"Thanks! I've reached out to {admin_name} to confirm you. "
                            f"You'll hear from me the moment they approve. 😊")}
    except Exception as e:
        session.rollback()
        print(f"submit_vouch_admin_details error: {e}")
        return {"status": "error", "message": "Something went wrong saving that — mind trying again?"}


def resolve_vouch_confirmation(session, request, approved, resolved_by=None):
    """An admin replied. On approval: enrol the requester with their requested role,
    approve their account, and notify them. On rejection: close it and notify them.

    `resolved_by` is the OmaUserRegistration of the admin who actually answered.
    Under the broadcast model every admin is asked, so we record who settled it
    rather than who was named up front.

    Returns a dict whose 'message' is what Oma should say back to the ADMIN.
    """
    try:
        # Every admin was messaged, so two can answer within seconds of each
        # other. Re-read the stage before acting: whoever commits first wins and
        # the second gets told it is already handled, instead of us enrolling
        # twice or overwriting a rejection with an approval.
        session.refresh(request)
        if request.stage != JoinRequestStage.awaiting_admin_confirmation:
            already = request.stage.value.replace("_", " ")
            who = request.vouching_admin_name or "another admin"
            return {"status": "already_resolved",
                    "message": f"That one's already been {already} by {who} — nothing to do. 👍"}

        if resolved_by is not None:
            request.vouching_admin_name = resolved_by.username
            request.vouching_admin_phone = _normalize_phone(resolved_by.phone_number)
            request.vouching_admin_user_id = resolved_by.id

        if approved:
            if request.requester_user_id:
                add_outreach_program_user(session, request.requester_user_id, request.requested_role)

            acct = None
            if request.requester_user_id:
                acct = session.query(OmaUserRegistration).filter_by(id=request.requester_user_id).first()
            if acct is None:
                acct = (session.query(OmaUserRegistration)
                        .filter_by(phone_number=request.requester_wa_id).first())
            if acct and not acct.is_approved:
                acct.is_approved = True
                acct.approved_at = datetime.utcnow()

            request.stage = JoinRequestStage.approved
            request.resolved_at = datetime.utcnow()
            session.commit()

            role_label = request.requested_role.value.replace("_", " ")
            send_whatsapp_message(
                request.requester_wa_id,
                (f"Great news! {request.vouching_admin_name or 'An admin'} has confirmed you. "
                 f"You're now registered as a {role_label} on the WeAspire Medical Outreach 🎉 "
                 f"Just say hello to get started."))
            return {"status": "approved",
                    "message": f"Thanks for confirming — I've added {request.requester_name or 'them'} as a {role_label}. 🙌"}
        else:
            request.stage = JoinRequestStage.rejected
            request.resolved_at = datetime.utcnow()
            session.commit()
            send_whatsapp_message(
                request.requester_wa_id,
                ("Thanks for your patience. Unfortunately your outreach sign-up wasn't approved by our "
                 "admins. If you think this is a mistake, please reach out to hi@welbridg.com."))
            return {"status": "rejected",
                    "message": "No problem — I've let them know it wasn't approved."}
    except Exception as e:
        session.rollback()
        print(f"resolve_vouch_confirmation error: {e}")
        return {"status": "error", "message": "Something went wrong — mind trying again?"}


def find_registered_user(session, phone_number=None, name=None):
    """Locate a registered user by phone (preferred) or by name.

    Phone is exact after normalisation. Name is a case-insensitive LIKE, and we
    deliberately refuse an ambiguous name match rather than guessing — promoting
    the wrong person is not something the promoted person would notice, and it
    hands out data access.

    Returns (user, error_message). Exactly one of them is None.
    """
    if phone_number:
        phone = _normalize_phone(phone_number)
        user = (session.query(OmaUserRegistration)
                .filter(OmaUserRegistration.phone_number == phone).first())
        if user:
            return user, None
        return None, (f"I couldn't find anyone registered with the number +{phone}. "
                      f"They need to sign up with Oma first — then I can promote them.")

    if name:
        matches = (session.query(OmaUserRegistration)
                   .filter(OmaUserRegistration.username.ilike(f"%{name.strip()}%"))
                   .all())
        if not matches:
            return None, (f"I couldn't find anyone registered under \"{name}\". "
                          f"Double-check the spelling, or send me their WhatsApp number instead.")
        if len(matches) > 1:
            listed = ", ".join(f"{m.username} (+{m.phone_number})" for m in matches[:5])
            return None, (f"More than one person matches \"{name}\": {listed}. "
                          f"Send me the exact WhatsApp number so I promote the right one.")
        return matches[0], None

    return None, "Tell me either the person's WhatsApp number or their name, and I'll take it from there."


def promote_user(session, actor_status, target_phone=None, target_name=None, role="field_expert"):
    """An ADMIN elevates someone into an outreach role. Admin-only, and never
    downwards.

    Rules, in the order they are checked:
      1. Only admins may promote. Field experts and clients are refused.
      2. The target must already be a registered Oma user.
      3. Demotion is not possible through Oma at all — an existing admin cannot
         be moved to field_expert, and no role can be removed. That is a
         deliberate asymmetry: promotion is recoverable by the team in the db,
         whereas letting admins strip each other's access over WhatsApp is a
         hijacking risk if one account is compromised.
      4. The promoted person is told, so nobody gains access silently.

    Returns a dict; 'message' is what Oma says back to the ADMIN.
    """
    try:
        if actor_status != "admin":
            return {"status": "refused",
                    "message": "Only outreach admins can add or promote people, sorry! 🙏"}

        try:
            role_enum = role if isinstance(role, OutreachRole) else OutreachRole(str(role).strip().lower())
        except ValueError:
            valid = ", ".join(r.value for r in OutreachRole)
            return {"status": "error", "message": f"\"{role}\" isn't a role I know. Valid ones: {valid}."}

        user, err = find_registered_user(session, phone_number=target_phone, name=target_name)
        if err:
            return {"status": "not_found", "message": err}

        # Guard against demotion, including the sideways kind.
        existing_admin = (
            session.query(OmaOutreachProgramUsers)
            .filter(
                OmaOutreachProgramUsers.user_id == user.id,
                OmaOutreachProgramUsers.role == OutreachRole.admin,
                OmaOutreachProgramUsers.is_active == True,
            )
            .first()
        )
        if existing_admin and role_enum != OutreachRole.admin:
            return {"status": "refused",
                    "message": (f"{user.username} is already an admin, and I can't move anyone "
                                f"down a level. If that really needs changing, the Welbridg team "
                                f"can do it directly.")}
        if existing_admin and role_enum == OutreachRole.admin:
            return {"status": "noop",
                    "message": f"{user.username} is already an admin — nothing to change. 👍"}

        prog = add_outreach_program_user(session, user.id, role_enum)
        if prog is None:
            return {"status": "error",
                    "message": "Something went wrong saving that — mind trying again?"}

        # Approve their account too, otherwise they'd be outreach staff who still
        # can't get past the approval gate in generate_response.
        if not user.is_approved:
            user.is_approved = True
            user.approved_at = datetime.utcnow()
            session.commit()

        role_label = role_enum.value.replace("_", " ")
        send_whatsapp_message(
            user.phone_number,
            (f"Good news {user.username}! 🎉 You've been added to the WeAspire Medical "
             f"Outreach as a {role_label}. Just say hello and I'll walk you through what you "
             f"can do."))

        logging.info(f"promote_user: {user.username} (+{user.phone_number}) -> {role_enum.value}")
        return {"status": "promoted",
                "message": (f"Done — {user.username} (+{user.phone_number}) is now a {role_label}, "
                            f"and I've let them know. 🙌")}
    except Exception as e:
        session.rollback()
        logging.error(f"promote_user error: {e}")
        return {"status": "error", "message": "Something went wrong with that — mind trying again?"}


def interpret_yes_no(text):
    """Cheap, dependency-free yes/no classifier for the admin's reply.
    Returns 'yes', 'no', or 'unclear'."""
    import re
    words = set(re.findall(r"[a-z']+", str(text).strip().lower()))
    yes = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "approve",
           "approved", "confirm", "confirmed", "accept", "correct", "affirmative"}
    no = {"no", "n", "nope", "nah", "decline", "declined", "reject", "rejected",
          "dont", "never", "negative"}
    if words & no:
        return "no"
    if words & yes:
        return "yes"
    return "unclear"


def extract_admin_details(question, context=""):
    """Pull the vouching admin's NAME and PHONE from the requester's message.
    Returns {'name': str|None, 'phone': str|None} (phone is digits only)."""
    completion = client.chat.completions.create(
        model=oma_models.FAST,  # extract a name + phone number
        messages=[
            {"role": "system", "content": f"""
                You extract the NAME and PHONE NUMBER of the admin that a user is naming
                as the person who will vouch for them joining an outreach programme.
                Use the latest message (and chat history for context).

                Return STRICT JSON, nothing else:
                {{"name": "<full name or null>", "phone": "<international digits only, or null>"}}

                Rules:
                - phone: strip spaces, '+' and dashes; keep the country-code digits. If there is
                  no clear phone number, use null.
                - name: the admin's name if stated, else null.

                Chat history:\n{context}
            """},
            {"role": "user", "content": question},
        ],
    )
    txt = (completion.choices[0].message.content or "").strip()
    try:
        data = json.loads(txt)
        phone = data.get("phone")
        return {"name": data.get("name") or None,
                "phone": _normalize_phone(phone) or None}
    except (json.JSONDecodeError, TypeError):
        return {"name": None, "phone": None}


def handle_vouch_message(session, wa_id, name, message_body):
    """Top-level router for the vouch flow, called at the very top of
    generate_response for EVERY message. Returns a reply string when this message
    is part of a live vouch exchange (so the caller should short-circuit), or
    None when it isn't (caller falls through to normal routing).

    Only REQUESTER cases are handled here:
      (a) a requester still waiting on a decision, and
      (b) legacy: a requester who was asked to name an admin, before the switch
          to broadcasting. Kept so rows created by the old flow still resolve.

    ADMIN DECISIONS ARE NOT HANDLED HERE ANY MORE. They used to be, via a
    keyword-plus-word-count heuristic, which meant "Yes you can approve him" was
    not understood while a stray "ok" was. Because this function short-circuits
    before routing, the LLM never saw those messages at all. Approvals are now a
    tool on the outreach agent (`decide_join_request`), with the pending queue
    injected into the admin's system prompt — so any phrasing works, and the
    model can tell a real decision from unrelated chat.
    """
    text = _extract_text(message_body)

    open_req = get_open_join_request_for_requester(session, wa_id)

    # (b) Legacy rows from the name-an-admin flow.
    if open_req and open_req.stage == JoinRequestStage.awaiting_admin_details:
        details = extract_admin_details(text)
        if not details.get("phone"):
            return ("To verify you, I need an *admin* who can vouch for you. Please send their "
                    "*full name* and *WhatsApp number* (with country code) in one message.")
        return submit_vouch_admin_details(
            session, open_req, details.get("name") or "the admin", details["phone"]
        )["message"]

    # (a) Requester chasing an application that is out with the admins.
    if open_req and open_req.stage == JoinRequestStage.awaiting_admin_confirmation:
        return ("You're all set on your end 👍 Your application is with our outreach admins "
                "and I'll message you the moment one of them confirms it. "
                "If it's been a while, hi@welbridg.com can chase it up.")

    return None
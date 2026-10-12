import oma_models  # model tier per call: see oma_models.py
from db import *
from functions_1 import get_context_from_db, get_context_for_startgate




# Function to add a reminder
def add_reminder_func(session, user_id, wa_id, reminder_text, remind_at):
    #session = Session()
    try:
        dt_object = datetime.strptime(remind_at, "%Y-%m-%d %H:%M:%S")
        new_reminder = OmaReminder(
            user_id=user_id,
            wa_id = wa_id,
            reminder_text=reminder_text,
            remind_at=dt_object
        )
        session.add(new_reminder)
        session.commit()
        print("Reminder added successfully!")
        return "Your reminder has been set successfully"
    except Exception as e:
        session.rollback()
        print("Error:", e)
        return "Hmmm. Something went wrong."  
    finally:
        #session.close() #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!HERE IS ONE OF THE SESSION CLOSES
        pass      







#............................................................
# LLM TO GUIDE REGISTRATION
#............................................................
# Check if user is approved
import openai
import os
from dotenv import load_dotenv
import json
import logging
from openai import OpenAI
from programme_info import PROGRAMME_BRIEF
load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")    
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")     


# I still need to write the flow for if a users message is for the OUTREACH PROGRAM AND THEY ARe not registered, I.e they will be registered normally and registered for the outreach program 
# Then I need to use the what_is_users_msg_for func to discern from context also if the users message relates to the OUTREACH program or if it doesnt

def what_is_users_msg_for(question, context):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.FAST,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
            {"role": "system", "content": f"""

                Your name is Oma, a chat assistant for our company welbridg  You are given a chat_history of a users chat with you. Your role is to look at the users chat history as well as 
                the users current message, and depict wether their request is about the Outreach Program or not. The outreach program is a program that the 
                company runs to meet and conduct health analysis on people in rural areas.   
                
                **Response Format (MUST be in JSON):**
                - If the users current message relates to the Outreach program:
                    {{
                        "event": "outreach"
                    }}
                - If the users current message has nothing to do with the outreach program:
                    {{
                        "event": "regular"
                    }}

                - If you are unsure about what the user is asking for:
                    {{
                        "event": "unsure"
                    }}
                
                Note that te person can be a client of the outreach program or one of the conductors of the program. But you have to simply discern from chat if they are
                for the program os simply returen unsure if you cant. 

                You also have to use the chat history given to you as context in making your decision.

                You MUST always return a JSON object exactly in this format.
            
            
           
            Below is your chat_history and latest user_message:\n
                    Latest User Message: \n ({question})
                    Chat History:\n ({context})
            """},
            {"role": "user", "content": question}
        ]
    )

    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()

    try:
        response_data = json.loads(response_text)  # Parse JSON response
        return response_data.get("event", "unsure")   # "regular" | "outreach" | "unsure"
    except json.JSONDecodeError:
        return "unsure"





def registrer(question, context):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.WORKER,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
            {"role": "system", "content": f"""
           You are Oma's registration officer for Welbridg — a new user's first point of contact.
           Be friendly, professional and also relatable. And make use of emojis only where necessary. 
           Also dont be too wordy, keep sentences to a line, and only use more than that when necessary or demanded. 

            Your job has two parts, IN ORDER:
            1. Talk to the user first. Greet warmly, return pleasantries if greeted, and find out
            what they came for. Do NOT open by demanding a username and email.
            2. Once you understand their intent, guide them to register by collecting a USERNAME
            and a VALID EMAIL. Registration is required before they can use Oma.

            About Welbridg (weave in naturally, don't dump it):
            "When someone you love needs care and you can't be there — another country, another
            city, or just stretched too thin — you deserve to know what's happening. Welbridg
            gives you visibility into their care and a way to coordinate it."

            We currently offer two main services:
            - Insurance — AXA and Hygeia plans, for the user or their beneficiaries.
            - The WeAspire Medical Outreach — a free community health outreach that
              Welbridg partners on. Field workers can register to help run it, and
              community members can ask about attending.
            """ + PROGRAMME_BRIEF + f"""

            Routing — follow the user's lead:
            - Health / medications / care questions -> lean toward insurance.
            e.g. "We offer AXA and Hygeia plans — let's get you started with a username and email."
            - Outreach program questions -> guide them to register in that context, and mention
            they can ask about insurance anytime.
            - Unclear -> name both briefly and ask which they're after.

            Tell them (once registered) Oma also does: medication/appointment reminders, reading
            images, insurance advice and booking, and outreach info retrieval — so finishing
            registration is worth it.

            Say once, early (first-time users only):
            - Registration exists to keep out spam.
            - If the team is slow after they submit, they can email hi@welbridg.com.

            Outreach only: if THEY raise the outreach program, confirm clearly that they want to
            register as a field agent. Don't push outreach on anyone who didn't ask.

            Email validation:
            - Valid format (user@example.com).
            - A real provider (gmail, yahoo, etc.). Catch typos and prompt to fix.
            - If a common provider is missing ".com" or has an obvious slip (gmali -> gmail),
            correct it and ask them to confirm.
            - Read details from BOTH the chat history and the latest message. If the username was
            already given and they only send a corrected email, keep the username — don't re-ask.

            Style: friendly, warm, a little funny, relatable — but concise. Short messages, few
            lines. Never repeat a greeting you already made (check the chat history). Preserve tokens.

            RESPONSE FORMAT — you MUST always return exactly this JSON and nothing else:

            If details are complete and valid:
            {{
                "A": ["username", "email"],
                "B": "confirmation, e.g. 'Got it — registration's in progress. You'll get a mail once approved. After that, just say hi!'",
                "C": "done",
                "D": "outreach" or "none"
            }}

            If details are missing or need fixing:
            {{
                "A": [],
                "B": "what to fix — or, for a first message, a warm greeting + why they must register + a request for username and valid email",
                "C": "loading",
                "D": "outreach" or "none"
            }}

            The chat history is the conversation between you (Assistant) and the User. Lines under
            "User" are the user; lines under "Assistant" are you. Use it to track flow, avoid
            double-greeting, and carry context forward.

            Below is your chat_history and latest user_message:\n
                                Latest User Message: \n ({question})
                                Chat History:\n ({context})
                        """},
                        
            {"role": "user", "content": question}
        ]
    )

    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()

    logging.info("REGISTRER raw model output:\n%s", response_text)

    try:
        response_data = json.loads(response_text)  # Parse JSON response
        parsed = [response_data.get("A", []),
                  response_data.get("B", ""),
                  response_data.get("C", "loading"),
                  response_data.get("D", "none")]      # "outreach" | "none"

        # Flags first, reply last - B can be long and would otherwise bury the
        # bits you actually branch on (C decides whether registration fires,
        # D picks the outreach vs regular branch).
        logging.info(
            "REGISTRER parsed -> A(details)=%r | C(status)=%r | D(route)=%r | B(reply)=%r",
            parsed[0], parsed[2], parsed[3], parsed[1],
        )
        return parsed
    except json.JSONDecodeError as e:
        # Without this the raw text was lost and the caller just saw the
        # generic error string below, with no way to tell what the model said.
        logging.error(
            "REGISTRER could not parse model output as JSON (%s). Raw text was:\n%s",
            e, response_text,
        )
        return [[], "Error: Invalid response format from AI.", "loading", "none"]









#.....................................................................................................
# THIS IS THE DATE AND TIME CALCULATOR
#..........................................................................................................
from datetime import datetime

def get_current_date():
    """Returns the current date with full details including day, month, and timestamp."""
    now = datetime.now()
    return {
        "current_date": now.strftime("%Y-%m-%d"),  # YYYY-MM-DD format
        "day_of_week": now.strftime("%A"),  # Full weekday name (e.g., Monday)
        "month": now.strftime("%B"),  # Full month name (e.g., January)
        "full_datetime": now.strftime("%Y-%m-%d %H:%M:%S")  # Full timestamp
    }






#.....................................................................................................
# THIS IS FOR THE AGE MODEL
#.....................................................................................................
def age_interpreter(question, context):
    
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.FAST,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
                    {"role": "system", "content": f"""
                     
                    Your name is Oma. You're a useful assistant whose role is to find age information in a conversation. The conversation given to you comprises of the latest human message and a chat history.
                    The chat history provided to you is a conversation between you (Assistant) and the User (User) 
                    Please note: In the chat history provided, the responses in "User" are from the user, while those under "Assistant" are from you.
                    
                    Your main task is to observe the latest information as well as the chat_history for any information relating to the age of person.
                    That is a user can be asked by the assistant to provide information about the age of whoever he wants to  get an insurance or a service for or for himself if he wants that service for himself.
                    A user could also provide information that pertains to age when conversing with the assistant for a service. 
                    
                    You are to use both the chat history and latest human message to compose a message highlighting the age of the user and also return a command stating if "Axa" or "Hygeia" plans is what the user reuires. 
                    
                    Rules
                    1. If the persons age is either 60 years or above that, Return a statement that the individual (subject of discussion) is above 60 years old and Hygeia plans are what he or she needs.
                    2. If the persons age is less than  60 years old, return a statement that the individuals age is below 60 and hence the Axa plans are his or her perfect fit.
                    3. If you don't find any age information in the latest human message, then just return an empty string "". Nothing else just an empty string.
                    
                    NOTE: The age information you're looking for must come only from the user and never from the assistant. But you can use previous conversations that include the assistant as context for fulfilling your task.   
                  
                    An Example result is:
                    - The dad is above 60 years old based on the earlier conversation, so the hygeia plans are what he needs.
                    
                    Please note that the information is not passed to the user but to another assistant that needs it... So use "The" in refering to the subjects.
                    
                  
                    Latest User Message: \n ({question})
                    Chat History:\n ({context})
                    
                    """},
                    {
                        "role": "user",
                        "content": question
                    }
                ]
    )
    return completion.choices[0].message.content.lower()





# Strip outer quotes!!!
def strip_outer_quotes(text):
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text





# FUNCTION TO DETECT NATIONALITY
def my_country(number):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.FAST,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. 
                Your role is to determine what country a phone number is from depending on the country code of the phone number given to you.
                
                You are to also return the time zone of the country if they are not among countries that have multiple timezones Like USA, Brazil, Russia and so on.
                If they are countries with multiple timezones, just return the name of the country an information that it has multiple timezones,and the timezone needs to be specified. 
            
            
                Now, You are to return the Country name, the time zone, and the UTC offset.
                Saying the user is from [country], the time zone is [time zone], which is [utc offset]
                
                But if there are multiple timezones in the country
                say the user is from [country], and you need to ask them to specify the timezone.
         
            """},
            {"role": "user", "content": number}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text







# FUNCTION TO EXPLAIN IMAGES
def image_explainer(note):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.WORKER,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. 
                Your role is to provide a very well detailed description of any image passed to you.

                This means when an image is passed to you, your job is to give a detailed description of the image explaining all what is within in a comprehensive
                and detailed manner. This is extremely important.
                
                You are to return the answer as:
                
                "THIS IS AN IMAGE MESSAGE; THIS IS THE IMAGE DESCRIPTION** :\n\n i.e new lines. **then your detailed description
         
            """},
            {"role": "user", "content": note}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text






# FUNCTION TO DETECT rephrase IN CASE OF OVER-LENGHT
def oma_rephraser(message):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.FAST,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},

        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. 
                Your role is to modify the text given to you as it is too lenghty. 
                
                Take all the core points and rephrase it to a new message not more that 500 words long.
                Keep the pattern of the text, the language, style and every other core semantics, tone or detail in the text.
        
                NOTE:
                You are to return only the refined text to me. Do not include any other thing. Just the text alone! 
            """},
            {"role": "user", "content": message}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text






# FUNCTION TO CHECK LENGHT OF TEXT INCASE OF TWILIO
def check_and_rephrase(message):
    if len(message) > 1400:
        response = oma_rephraser(message)
        return response
    else:
        return message
        


def generate_ticket_number(length=10):
    characters = string.ascii_uppercase + string.digits
    ticket_number = ''.join(random.choices(characters, k=length))
    return f"TKT-{ticket_number}"







# FUNCTION TO DETECT rephrase IN CASE OF OVER-LENGHT
def latency_filler_assistant(message):
    client = OpenAI(
    api_key=anthropic_api_key, 
    base_url="https://api.anthropic.com/v1/"
    )

    completion = client.chat.completions.create( 
        model=oma_models.FAST,   # was "o1"
        #max_tokens=8000,   # must exceed budget_tokens
        #extra_body={"thinking": {"type": "enabled", "budget_tokens": 2000}},
        messages=[
            {"role": "system", "content": f"""
                    You are **Oma**, a friendly, human-like conversational assistant for **Welbridg**.
                    Your main role is to act as a **filler** during natural conversation — providing short, polite, and contextually relevant responses while the system processes the user’s main request in the background.

                    ---

                    ### 🎯 Objective

                    Keep users **engaged and reassured** during wait times by responding naturally to what they said, without giving false information or pretending to have the final answer.

                    ---

                    ### 💬 Behavior Guidelines

                    1. **Tone:** Friendly, calm, and confident. Sound like a human support assistant.

                    * Example tone: “Sure, let me pull that up for you.” / “Just a moment please — I’m checking that now.”

                    2. **Response Length:**

                    * 1–2 short sentences max.
                    * Never include filler text like “…” or “typing”.

                    3. **Context Awareness:**

                    * Only respond with filler messages when the user asks a **request that requires backend processing or lookup**.
                    * If the message is a **simple greeting** (“hi”, “hey”, “hello”, “good morning”, etc.) or something that does not require a filler, you must respond with exactly:
                        **`No Filler Needed`**

                    4. **Do Not Fabricate Answers:**

                    * Never generate or guess the actual result.
                    * You only acknowledge that you’re fetching or preparing information.

                    5. **Consistency:**

                    * Always sound like Oma (same personality).
                    * Refer to yourself casually if relevant (“Oma here — let me grab that for you.”).
                    * Maintain polite professionalism.

                    6. **Output Rule:**
                    Return **only the filler message text or “No Filler Needed”**, with no explanations or formatting.

                    ---

                    ### 🧠 Examples

                    #### Example 1

                    **User:** “Can you tell me about my AXA insurance plan?”
                    **Oma:** “Sure thing — let me grab those details for you.”

                    #### Example 2

                    **User:** “What’s the current premium amount?”
                    **Oma:** “One moment please, I’m pulling that up.”

                    #### Example 3

                    **User:** “Can you help me file a claim?”
                    **Oma:** “Of course! Give me a second to get the claim process started.”

                    #### Example 4

                    **User:** “Show me the list of active policies.”
                    **Oma:** “Got it — I’ll load your active policies right away.”

                    #### Example 5

                    **User:** “I want to cancel my plan.”
                    **Oma:** “Alright, let me prepare that for you. Just a moment.”

                    #### Example 6

                    **User:** “Hey Oma!”
                    **Oma:** `No Filler Needed`

                    #### Example 7

                    **User:** “Hi”
                    **Oma:** `No Filler Needed`

                    #### Example 8

                    **User:** “Okay thanks!”
                    **Oma:** `No Filler Needed`

                    ---

                    ### 🧭 Final Reminder

                    Your only goal is to produce short, natural filler text appropriate to the user’s message.
                    If the user’s message doesn’t require a filler, respond strictly with **“No Filler Needed.”**
                    Never include reasoning, system notes, or metadata in your reply.

            
                NOTE:
                You are to return only the refined text to me. Do not include any other thing. Just the text alone! 
            """},
            {"role": "user", "content": message}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text


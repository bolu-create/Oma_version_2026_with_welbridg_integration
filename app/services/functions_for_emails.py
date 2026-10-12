import oma_models  # model tier per call: see oma_models.py
#..................................................................THE GMAIL TOOLKIT.....................................................
#............................................................
# GMAIL TOOLKIT
#............................................................
from langchain_google_community import GmailToolkit
import getpass
import os
from langchain_openai import ChatOpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage
#............................................................
# GMAIL TOOLKIT (SERVICE ACCOUNT VERSION)
#............................................................
# Initialize LLM
llm_gmail = ChatOpenAI(model=oma_models.WORKER, openai_api_key=os.getenv("ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com/v1/")
SERVICE_ACCOUNT_FILE = 'welbridg-agent.json'  # Ensure correct path
USER_EMAIL = 'Oma@welbridg.com'  # Sender's email
SCOPES = ['https://mail.google.com/']


def gmail_credentials(scopes, subject):
    """The Gmail service-account key, without it having to live in the repo.

    Deployed: the JSON key's contents in the GOOGLE_SERVICE_ACCOUNT_JSON env
    var (a Railway variable). Locally: the git-ignored welbridg-agent.json in
    the project root, as before. The key used to be committed so deploys could
    read the file; it no longer is, so production needs the env var.
    """
    import json
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=scopes, subject=subject)
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes, subject=subject)


# Build Gmail Service with Service Account
try:
    credentials = gmail_credentials(SCOPES, USER_EMAIL)
    api_resource = build('gmail', 'v1', credentials=credentials)
except Exception as e:
    print(f"Error initializing Gmail service: {e}")
    raise

# Initialize Gmail Toolkit PROPERLY with the API resource
toolkit = GmailToolkit(api_resource=api_resource)  # THIS IS CRUCIAL
gmail_tools = toolkit.get_tools()
tools = toolkit.get_tools()

# Create agent executor
agent_executor = create_react_agent(llm_gmail, tools)







def text_maker(question, candidate):
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url="https://api.anthropic.com/v1/",
    )

    completion = client.chat.completions.create(
        model=oma_models.WORKER,
        #model="o1",
        #reasoning_effort="high",
        #store=True,   # OpenAI-only param — not supported by Anthropic
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. You handle properly writing emails before they are sent out. 
                
                Your task is to write an email that will be either sent to the Team at welbridg, or the user themselves depending on the candidate given. 
                Note that the candidate given will either be "Team" or "User"
                
                1. If the candidate is "Team":
                    You will compose an email informing the team about the new user who needs access to Oma, notifying them about the created ticket details. 
                    Include the users username, email and phone number details of the user which will be given to you.
                    
                2. If the candidate is "User":
                    You will compose an email informing the user that the request to use Oma has been to sent to the team and that they will be contacted shortly. Include the ticket number for them to know, incase they require it to notify the team. 
                    Also include that they can reach out to team at hi@welbridg.com for any inquiries.
                    
                The Candidate is: {candidate}
         
            """},
            {"role": "user", "content": question}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text



def send_email(to, subject, body, candidate, compose=True):
    "#""Sends an email using the Gmail API with proper Base64 encoding."#""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.")

        # compose=False means 'body' is already written. Used when the same mail
        # goes to several people, so we only pay for one text_maker call.
        if compose:
            body = text_maker(body,candidate)

        # Create the email message
        message = MIMEText(body)
        message["to"] = to
        message["from"] = USER_EMAIL
        message["subject"] = subject

        # Encode in Base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Send email
        sent_message = api_resource.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        print(f"✅ Email sent successfully to {to}!")
        # 'body' is the composed text from text_maker - the callers store it on
        # the ticket. Both paths return the same keys, so a failed send can no
        # longer KeyError upstream the way a missing 'body' did.
        return {"status": "success", "sent_to": to, "subject": subject, "body": body}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e), "sent_to": to, "subject": subject, "body": body}






#......................................................................................................
# Using the o1 model for my main model
#......................................................................................................
import json
import base64
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from langchain.tools import Tool

# ............................................................
# 🔹 CONFIGURATION
# ............................................................

# ✅ Client (OpenAI SDK pointed at Anthropic)
client = OpenAI(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url="https://api.anthropic.com/v1/",
)

# ✅ Gmail API Configuration
#SERVICE_ACCOUNT_FILE = 'oma_baby_full_google.json'  # Ensure correct path
#USER_EMAIL = 'bolu@casialab.com'  # Sender's email
SERVICE_ACCOUNT_FILE = 'welbridg-agent.json'  # Ensure correct path
USER_EMAIL = 'Oma@welbridg.com'  # Sender's email
SCOPES = ['https://mail.google.com/']

# Authenticate Gmail API
credentials = gmail_credentials(SCOPES, USER_EMAIL)
api_resource = build('gmail', 'v1', credentials=credentials)





# ............................................................
# 🔹 LLM TO RECOMPOSE EMAIL MESSAGE
# ............................................................

def emailer(question):
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url="https://api.anthropic.com/v1/",
    )

    completion = client.chat.completions.create(
        model=oma_models.WORKER,
        #model="o1",
        #reasoning_effort="high",
        #store=True,   # OpenAI-only param — not supported by Anthropic
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. You composing and structuring emails to be be sent to the Team, for them to attend to user requests. 
                 
                Your role is to recompose the message you recieve into a well structured and written email. The message you recieve is just a collection of details collected from the user that need to be put together properly.
                
                Note the following Important Details:
                
                - You are to address it to the team. Use something simple like Hello Team, in addressing this as the name of the team members to send to is not provided to you. 
                - Note that the name in the text of who wants to get the Insurance, is of the person the user wants to get the Insurance for. Not who wants to get it. The user who is getting the Insurance for the person have their name stated as the "Username". 
                - You are writing to your "Team". You are an assistant for the company Welbridg, so note that. Your role is to foward the user request to them in a properly worded email.
                - Also your name is Oma. so when you want to add who the email is from, just say Oma. No other details should be added.
                - The message will contain the name of someone who wants to get an Insurance type. Just use the person's name as given, when addressing them. Don't add a title like Mr/Mrs. 
                 
                Keep message mildly comprehensive and detailed and straight to the point.
         
            """},
            {"role": "user", "content": question}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text




# ............................................................
# 🔹 FUNCTION: Encode and Send Email
# ............................................................

def send_email_func_call(to, subject, body, username, user_phone_number, user_email):
    "#""Sends an email using the Gmail API with proper Base64 encoding."#""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.")
        
        # Add user details to the body
        full_body = f"""{body}

        ---
        Find attached the User Information:
        - Username: {username}
        - Phone: {user_phone_number}
        - Email: {user_email}
        """
        
        email_message = emailer(full_body)

        # Create the email message
        message = MIMEText(email_message)
        #message = MIMEText(full_body)
        message["to"] = to
        message["from"] = USER_EMAIL
        message["subject"] = subject

        # Encode in Base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Send email
        sent_message = api_resource.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        print(f"✅ Email sent successfully to {to}!")
        return {"status": "success", "sent_to": to, "subject": subject}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e)}





# ............................................................
# 🔹 FUNCTION: Encode and Send Email
# ............................................................
def emailer_user(question):
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url="https://api.anthropic.com/v1/",
    )

    completion = client.chat.completions.create(
        model=oma_models.WORKER,
        #model="o1",
        #reasoning_effort="high",
        #store=True,   # OpenAI-only param — not supported by Anthropic
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. You handle sending user emails to confirm their request. 
                You are to reply a user that their request has been sent to the Team. 
                Your role is to recompose the message you recieve into a well structured and written email. The message you recieve is just a collection of details to be sent to the user that need to be put together properly.
                
                You are to address it to the user. Their username will be provided. You can simply say Hi, Hello or anything similar when starting your message
                Also your name is Oma. so when you want to add who the email is from, just say Oma. No other details should be added.
                 
                Keep message short and straight to the point.
         
            """},
            {"role": "user", "content": question}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text


def send_email_func_call_users(to, subject, body, username):
    "#""Sends an email using the Gmail API with proper Base64 encoding."#""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.")
        
        # Add user details to the body
        full_body = f"""{body}
        
        User's Username is {username}

        ---
        Thanks.
        Oma
        """

        email_message = emailer_user(full_body)        
        # Create the email message
        message = MIMEText(email_message)
        message["to"] = to
        message["from"] = USER_EMAIL
        message["subject"] = subject

        # Encode in Base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Send email
        sent_message = api_resource.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        print(f"✅ Email sent successfully to {to}!")
        return {"status": "success", "sent_to": to, "subject": subject}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e)}






# ............................................................
# 🔹 FUNCTION: Encode and Send Email For Reminder Service
# ............................................................

def emailer_reminder_user(question):
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url="https://api.anthropic.com/v1/",
    )

    completion = client.chat.completions.create(
        model=oma_models.WORKER,
        #model="o1",
        #reasoning_effort="high",
        #store=True,   # OpenAI-only param — not supported by Anthropic
        messages=[
            {"role": "system", "content": f"""
                You name is Oma. You are a helpful assistant for Welbridg. You handle sending user emails to confirm their reminders have been set. 
                You are to reply a user that their reminder has been set. 
                Your role is to recompose the message you recieve into a well structured and written email. The message you recieve is just a collection of details to be sent to the user that need to be put together properly.
                
                You are to address to the user. Their username will be provided. You can simply say Hi, Hello or anything similar when starting your message
                Also your name is Oma. so when you want to add who the email is from, just say Oma. No other details should be added.
                 
                Keep message short and straight to the point.
         
            """},
            {"role": "user", "content": question}
        ]
    )
    # Ensure the response is in valid JSON format
    response_text = completion.choices[0].message.content.strip()
    return response_text


def send_email_reminder_users(to, subject, body, username):
    "#""Sends an email using the Gmail API with proper Base64 encoding. for user's reminders"#""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.")
        
        # Add user details to the body
        full_body = f"""{body}
        
        User's Username is {username}

        ---
        Thanks.
        Oma
        """

        email_message = emailer_reminder_user(full_body)
        # Create the email message
        message = MIMEText(email_message)
        message["to"] = to
        message["from"] = USER_EMAIL
        message["subject"] = subject

        # Encode in Base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Send email
        sent_message = api_resource.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        print(f"✅ Email sent successfully to {to}!")
        return {"status": "success", "sent_to": to, "subject": subject}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e)}


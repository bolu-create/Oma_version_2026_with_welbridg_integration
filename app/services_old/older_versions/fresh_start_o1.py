import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain.agents import initialize_agent, AgentType
from langchain.tools import tool
from langchain.prompts import SystemMessagePromptTemplate
from sqlalchemy.orm import declarative_base, sessionmaker
import logging
from langchain.prompts.chat import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from google.cloud import storage
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.chains import RetrievalQA
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.llms import OpenAI
import os
from dotenv import load_dotenv
from langchain.chat_models import ChatOpenAI
from langchain.tools import Tool
from langchain.agents import initialize_agent, AgentType
from langchain_community.utilities import SerpAPIWrapper
from langchain.memory import ConversationBufferMemory


# Load environment variables
load_dotenv()


#.......................................................ALL THE SQL.........................................................
#............................................................
# Load the Remote SQL DB
#............................................................
def get_engine_for_mysql_db():
    """Connect to a remote MySQL database and create an engine."""
    # Get credentials from environment variables
    username = os.getenv("MY_USERNAME")
    password = os.getenv("PASSWORD")
    host = os.getenv("SQL_HOST_SERVER")
    database = os.getenv("DB_DATABASE")
    port = os.getenv("DB_PORT", 3306)  # Default MySQL port is 3306
    # MySQL connection string
    connection_string = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
    # Create SQLAlchemy engine
     # Create SQLAlchemy engine with connection pooling and pre-ping
    engine = create_engine(
        connection_string,
        pool_recycle=1800,  # Recycle connections every 30 minutes
        pool_pre_ping=True,  # Ensure the connection is alive before using it
        pool_size=10,  # Number of connections in the pool
        max_overflow=20,  # Maximum number of connections that can be created beyond pool_size
        connect_args={"connect_timeout": 10}  # Timeout in seconds for connecting to the server
    )
    return engine
# Get engine for MySQL database
engine = get_engine_for_mysql_db()
# Create SQLDatabase instance for LangChain
db = SQLDatabase(engine)






from sqlalchemy import create_engine
import os
from langchain_community.utilities.sql_database import SQLDatabase

#................................................................
# TABLE FOR USER REGISTRATION
#................................................................
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class UserRegistration(Base):
    __tablename__ = "user_registration"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=False)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)

def is_user_approved(session, phone_number):
    user = session.query(UserRegistration).filter_by(phone_number=phone_number).first()
    if user and user.is_approved:
        return True
    return False

def register_user(session, username, email, phone_number):
    new_user = UserRegistration(
        username=username, 
        email=email, 
        phone_number=phone_number
    )
    session.add(new_user)
    session.commit()
    
# Function to check if a user exists but is not approvedd
def is_user_pending_approval(session, wa_id):
    result = (
        session.query(UserRegistration)
        .filter(UserRegistration.phone_number == wa_id, UserRegistration.is_approved == False)
        .first()
    )
    return result is not None

# To be removed later
def approve_user(session, phone_number):
    user = session.query(UserRegistration).filter_by(phone_number=phone_number).first()
    if user:
        user.is_approved = True
        user.approved_at = datetime.utcnow()
        session.commit()
        print(f"User {user.username} approved successfully.")
    else:
        print("User not found.")





#............................................................
# DB function
#............................................................
# CHAT_HISTORY
#............................................................
from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)  # Surrogate primary key
    user_id = Column(Integer, ForeignKey("user_registration.id"), nullable=False)  # Common ID
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    name = Column(String(255), nullable=False)
    user_message = Column(Text, nullable=False)  # 'user' or 'assistant'
    agent_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Save interactions to DB
def save_message_to_db(session, user_id, wa_id, name, user_message, agent_response):
    new_message = ChatHistory(user_id=user_id, wa_id=wa_id, name=name, user_message=user_message, agent_response=agent_response)
    session.add(new_message)
    session.commit()
    print("Saved!!!!!!!!!!!!!!!!!")
    
# Retrieve context for the user
def get_context_from_db(session, user_id, limit=10):
    return (
        session.query(ChatHistory)
        .filter(ChatHistory.user_id == user_id)
        .order_by(ChatHistory.timestamp.desc())  # Most recent first
        .limit(limit)  # Restrict to 'limit' rows
        .all()
    ) 

""" 
# Retrieve chat history from DB
def fetch_chat_history(session, user_id, limit=10):
    chat_history_records = get_context_from_db(session, user_id, limit)
    chat_history = [
        {"role": "user", "content": record.user_message} if record.user_message else
        {"role": "assistant", "content": record.agent_response} if record.agent_response else None
        for record in reversed(chat_history_records)  # Reverse to maintain chronological order
    ]
    return [msg for msg in chat_history if msg]  # Remove None values
"""

def fetch_chat_history(session, user_id, user_email, limit=10):
    
    
    # 🔹 Define System Instructions for Better Tool Selection
    system_prompt = f"""
                    🟢 Role & Purpose
                        Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
                        Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
                        Your long-term goal however, is to encourage users to subscribe to the comapnies Insurance services while although providing empathetic, thoughtful, and personalized responses, you are carefully guiding them towards getting one of the companies insurance services. This role must be done gradually, and not interfere with finding out the needs of the user first. Use the "wellbridg_Insurance_and_institutions" tool for this.
                        However, You are also to respond to user's who want to get medical tests offered by wellbridg. This information is present in the "medical_test_information" tool in your knowledge base. Users can also ask questions about Medical tests offered by the company, which is another service completely independent off the Insurance. 
        
                        Your primary responsibilities are:

                        Providing accurate healthcare and insurance information as well as interactions and recommendations. Keep in mind the two insurance Types offered vary between Hygeia which is specifically for seniors (i.e folks that are aged 60 years old and above), and Axa which is for people who are not seniors i.e (anyone below the age of 60 years old). This information is important when talking all insurance related issues, like the insurance types and the organization they are covered under 
                        Recommending and explaining medical tests using "medical_test_information" tool.
                        Helping users book medical tests and insurance plans while ensuring all necessary details are collected before confirming the booking.
                        Managing email communications via Gmail, sending booking confirmations once all details are complete.
                        Your responses should be engaging, human-like, and conversational, ensuring users feel like they are interacting with a professional assistant rather than a chatbot.

                        🟡 Core Guidelines & Best Practices
                        
                        ✅ 1. Prioritize Empathy & Personalization
                        Engage in natural, friendly conversations with users.
                        Ensure users feel heard, reassured, and informed before making decisions.
                        Engage with empathy and personalization:
                        - Acknowledge the user’s unique situation and adapt your responses based on the context of the conversation.
                        - Priotize firstly understanding the requirements, problem the user faces, and recommending healthcare treatments for them, before gradually encouraging them to sign up for an Insurance
                        - Health conditions like headaches, fevers, and other ailments are things users may ask for, Always ask in-depth questions to know more about what kind of ailment or what degree of severity the ailment has gotten to before recommending any treatments or insurance services
                        - If a query is unclear, ask clarifying questions to gather more details.
                        - Avoid technical jargon. Use simple, conversational language to create a human-like experience.
                        - Reflect on past user queries and offer thoughtful follow-up suggestions when appropriate.
                        - Keep answers short and friendly unless detailed responses are necessary.
                        - When discussing or recommending Insurance plans for users, always state the associated prices/costs/pricing, **only when appropriate**, as this is the most important detail to the customer
        
        
                        2. **Healthcare/other Facility Listings:**
                        **Always** provide **5+ facilities** near the user’s location (e.g., Gbagada, Lagos). If fewer exist, say: "Here’s what I found – for more options, check [map service] or email hi@welbridg.com."
                        
                        3. **Pricing Rules:**
                            - **Immediately** share costs: "The Hygeia Silver Seniors plan costs NGN41,970/month. Want annual pricing? That’s NGN503,640!"
                            - If unsure: "Let me check! Email hi@welbridg.com for a quick quote."

                        4. Accuracy is Key:
                            - Always query your knowledge base before answering to ensure you provide accurate and trustworthy information.
                            - Avoid giving incorrect or incomplete information, as this can erode user trust.
                        
                        5. Handling Missing Information:
                            - If the information is not available, never tell the user to "speak with their insurance provider."
                            - Instead, instruct them to "send a mail to hi@welbridg.com for human support" to get the assistance they need.

                        
                        ✅ 6. Information Accuracy & Retrieval
                        Always query the correct tool before responding to a user's question.
                        For medical test inquiries, use med_test_retrieval_tool.
                        For general health questions, use general_retrieval_tool.
                        
                        ✅ 7. Handling Booking Requests
                        Detect when a user wants to book a service (insurance or lab test).
                        Track the collected booking details in memory.
                        Ask for missing details conversationally and naturally.
                        Use chat history to infer missing details before asking the user directly.
                        
                        ✅ 8. Required Information for Bookings
                        When a user wants to book a medical test or insurance plan, you must collect:
                        1️⃣ Service Type: Insurance or lab test.
                        2️⃣ Service Details: The specific insurance plan or medical test.
                        3️⃣ Who is it for? (Self, parent, child, etc.)
                        4️⃣ Subject Details: Name, age, and relevant health information.
                        5️⃣ Additional Information (if the user provides any).

                        ✅ 9. How to Collect Booking Information
                        First, check chat history and memory for any missing details.
                        If any details are missing, ask the user without disrupting the conversation flow.
                        If the user provides partial information, acknowledge it and guide them to complete the booking.
                        If the user changes their mind or needs time, allow them to continue the conversation naturally.
                        
                        ✅ 10. When All Booking Details Are Collected
                        Confirm the booking details with the user.
                        Use Gmail tools to send a booking confirmation email to the Welbridg team.
                        Notify the user that the booking is in progress and they will be contacted soon.
                        
                        ✅ 11. Email Handling via Gmail Tools
                        Only send an email when all booking details are complete.
                        Format the email clearly with all the collected details.
                        Ensure the subject line is clear and professional (e.g., "New Booking Request: [Service Type] for [Name]").
                    
                        ✅ 12. Tone & Style
                        Be fun, friendly, and professional—never robotic.
                        Keep responses conversational and engaging.
                        Ensure responses flow naturally, avoiding abrupt or generic questions.
                    
                        ✅ 13. Prohibited Actions
                        Never send an incomplete booking request.
                        Never ask the user for information that can be inferred from memory or chat history.
                        Never guess details—ask for clarification if needed.
                        
                        
                        🟠 Booking Workflow Implementation
                        
                        🎯 Step 1: Detect a Booking Request
                        If a user expresses interest in booking, acknowledge it warmly.
                        Check if any booking details are missing in memory.
                    
                        🎯 Step 2: Gather Missing Information
                        Use chat history to retrieve already provided details before asking.
                        If some details are still missing, ask conversationally.
                    
                        🎯 Step 3: Confirm the Booking
                        Once all required details are collected, summarize them for the user.
                        Ask for final confirmation before proceeding.
                    
                        🎯 Step 4: Send Email via Gmail Tools
                            Once the user confirms, you are to send two emails.
                            
                            1. You must send an email to the company email "hi@welbridg.com" notifying them of the users request with the ffg details:  

                                - Subject: New Booking Request: [Service Type] for [Name]
                                - Content: All collected details formatted clearly.
                                - Also add a good explanation of what the user wants based on your discussions with the user. 
            
                            2. After that you must send an email to the user's mail "{user_email}", notifying the user that their booking is being processed and that Welbridg will contact them soon.
                            
                                
                            NOTE: Sneding both emails is of utmost priority !!!! Use the gmail_tool to carry out the process of sending both emails.
                        
                        🟢 Example Booking Conversation Flow
                        👤 User: I’d like to book a Glycated Hemoglobin test.
                        🤖 Oma: Got it! Is this for you or someone else?
                        👤 User: It’s for my dad.
                        🤖 Oma: Great! Could you share his name, age, and any relevant health details?
                        👤 User: His name is James, he’s 62, and he has type 2 diabetes.
                        🤖 Oma: Perfect! I have all the details. I’ll now proceed with your booking.
                        🤖 Oma: ✅ Your request for a Glycated Hemoglobin test for James (62, type 2 diabetes) has been submitted. The Welbridg team will contact you shortly!                  
                        
                                 
                        Tone & Style:
                        - Be fun and friendly, but always maintain professionalism.
                        - COMPLETELY Avoid greetings like "Hi," "Hey there!".
                        - Take note of conclusive statements like okay, got it etc, know to conclude conversations in this instant
                        - Avoid mentioning technical terms like "database" or "tables" in responses.

                        Example Responses:
                        Example 1:
                            User: "I’m feeling really anxious about my upcoming surgery. What should I expect?"
                            Assistant: "I understand that surgery can be nerve-wracking, and it’s perfectly normal to feel anxious. Let’s take it step by step. I can share some general tips on preparing or help you connect with someone from your healthcare team for more specific guidance. How would you prefer to proceed?"
                        
                        Example 2:
                            User: "What insurance plan is best for me?"
                            Assistant: "I’d love to help you find the best plan! Could you share more about your health needs—like specific treatments or providers you prefer? I can also explain the differences between some popular plans."
                        
                        Key Guidelines:
                        - Always prioritize building rapport and trust by creating a personalized healthcare experience.
                        - Never mention technical terms like "database" or "data tables" in responses.
                        - Keep responses short, clear, and fun unless the situation calls for a more detailed explanation.      
                        
                                      
    """
    
    chat_history_records = get_context_from_db(session, user_id, limit)
    chat_history = [{"role": "system", "content": system_prompt}]  # Add system prompt here

    for record in reversed(chat_history_records):  # Reverse to maintain order
        if record.user_message:
            chat_history.append({"role": "user", "content": record.user_message})
        if record.agent_response:
            chat_history.append({"role": "assistant", "content": record.agent_response})

    return chat_history


#...................................................................................................
# DB function
#............................................................
# STAGE GATE CHAT HISTORY
#............................................................
from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime


class StageGate(Base):
    __tablename__ = "stage_gate_chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)  # Surrogate primary key
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    name = Column(String(255), nullable=False)
    user_message = Column(Text, nullable=False)  # 'user' or 'assistant'
    agent_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Save interactions to DB
def save_message_for_startgate(session, wa_id, name, user_message, agent_response):
    new_message = StageGate(wa_id=wa_id, name=name, user_message=user_message, agent_response=agent_response)
    session.add(new_message)
    session.commit()
    print("Saved!!!!!!!!!!!!!!!!!")
    
# Retrieve context for the user
def get_context_for_startgate(session, wa_id, limit=10):
    return (
        session.query(StageGate)
        .filter(StageGate.wa_id == wa_id)
        .order_by(StageGate.timestamp.desc())  # Most recent first
        .limit(limit)  # Restrict to 'limit' rows
        .all()
    ) 
#................................................................................................    

#................................................................
# TABLE FOR TICKET
#................................................................
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import random
import string


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user_registration.id"), nullable=False)  # Common ID
    ticket_number = Column(String(50), unique=True, nullable=False)
    username = Column(String(100), nullable=False)
    email = Column(String(100), nullable=False)
    phone_number = Column(String(15), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), default="open")  # Status could be 'open', 'closed', 'pending'
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    def __repr__(self):
        return (f"<Ticket(ticket_number={self.ticket_number}, username={self.username}, "
                f"email={self.email}, phone_number={self.phone_number}, status={self.status})>")



def add_ticket(session, user_id, ticket_number, username, email, phone_number, message, status="open"):
    new_ticket = Ticket(
        user_id=user_id,
        ticket_number=ticket_number,
        username=username,
        email=email,
        phone_number=phone_number,
        message=message,
        status=status
    )
    session.add(new_ticket)
    session.commit()
    
    return f"Ticket '{ticket_number}' has been successfully created."


def is_ticket_existing(session, ticket_number):
    result = (
        session.query(Ticket)
        .filter(Ticket.ticket_number == ticket_number)
        .first()
    )
    return result is not None


def generate_ticket_number(length=10):
    characters = string.ascii_uppercase + string.digits
    ticket_number = ''.join(random.choices(characters, k=length))
    return f"TKT-{ticket_number}"


# Set a Ticket to Pending
from datetime import datetime
def set_ticket_pending(session, ticket_number):
    ticket = session.query(Ticket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return f"No ticket found with ticket number {ticket_number}."
    if ticket.status == "pending":
        return f"Ticket {ticket_number} is already pending."
    ticket.status = "pending"
    ticket.updated_at = datetime.utcnow()
    
    try:
        session.commit()
        return f"Ticket {ticket_number} has been marked as pending."
    except Exception as e:
        session.rollback()
        return f"Error updating ticket status: {str(e)}"

# Set a Ticket to closed
from datetime import datetime
def close_ticket(session, ticket_number):
    ticket = session.query(Ticket).filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return f"No ticket found with ticket number {ticket_number}."
    if ticket.status == "closed":
        return f"Ticket {ticket_number} is already closed."

    ticket.status = "closed"
    ticket.updated_at = datetime.utcnow()
    
    try:
        session.commit()
        return f"Ticket {ticket_number} has been successfully closed."
    except Exception as e:
        session.rollback()
        return f"Error closing ticket: {str(e)}"

#................................................................................................    
# Create the table in the database
Base.metadata.create_all(engine)
# Bind sessionmaker and create session
Session = sessionmaker(bind=engine)
session = Session()

#................................................................................................    
# NON SESSION BASED SQL CODE  CONTEXT ANDD CHAT_HISTORY
#................................................................................................    
def check_db_for(user_id):
    # Fetch and format context
    context = get_context_from_db(session, user_id, limit=20)
    conversation_history = [
        f"User: {msg.user_message}\nAssistant: {msg.agent_response}" for msg in context
    ]
    # Combine history into the input message
    message = "\n".join(conversation_history)
    return message

def check_db_for_startgate(wa_id):
    # Fetch and format context
    context = get_context_for_startgate(session, wa_id, limit=20)
    conversation_history = [
        f"User: {msg.user_message}\nAssistant: {msg.agent_response}" for msg in context
    ]
    # Combine history into the input message
    message = "\n".join(conversation_history)
    return message


from sqlalchemy.orm import Session
#from models import UserRegistration  # Assuming your models are in models.py
def get_user_id_by_wa_id(session, wa_id):
    user = session.query(UserRegistration).filter_by(phone_number=wa_id).first()
    return user.id if user else None  # Return user_id if found, otherwise None


from sqlalchemy.orm import Session
#from models import UserRegistration  # Assuming your models are in models.py
def get_user_email_by_wa_id(session, wa_id):
    user = session.query(UserRegistration).filter_by(phone_number=wa_id).first()
    return user.email if user else None  # Return user_id if found, otherwise None
#....................................................................................................................................





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
llm_gmail = ChatOpenAI(model="gpt-4o", openai_api_key=os.getenv("OPENAI_API_KEY"))
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=os.getenv("OPENAI_API_KEY"))

#llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
#llm = ChatOpenAI(model="gpt-4.5-preview", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)


# Service Account Configuration
#SERVICE_ACCOUNT_FILE = 'oma_baby_full_google.json'#os.path.join(os.path.dirname(__file__), 'oma_baby_full_google.json')  # Ensure correct path
#USER_EMAIL = 'bolu@casialab.com'  # Workspace email to impersonate
SERVICE_ACCOUNT_FILE = 'welbridg-agent.json'  # Ensure correct path
USER_EMAIL = 'Oma@welbridg.com'  # Sender's email
SCOPES = ['https://mail.google.com/']

# Build Gmail Service with Service Account
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
        subject=USER_EMAIL
    )
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

def send_mail(example_query):
    email_details = {"to": None, "subject": None, "body": None}
    
    try:
        events = agent_executor.stream(
            {"messages": [("user", example_query)]},
            stream_mode="values",
        )

        for event in events:
            for message in event.get("messages", []):
                if isinstance(message, AIMessage):
                    for tool_call in getattr(message, "tool_calls", []):
                        if tool_call.get("name") == "send_gmail_message":
                            args = tool_call.get("args", {})
                            email_details.update({
                                "to": args.get("to"),
                                "subject": args.get("subject"),
                                "body": args.get("message")
                            })
        return email_details
    
    except Exception as e:
        print(f"Error in send_mail: {e}")
        raise




#............................................................
# LLM TO GUIDE REGISTRATION
#............................................................
# Check if user is approved
import openai
import os
from dotenv import load_dotenv
import json
from openai import OpenAI
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")     


def registrer(question, context):
    client = OpenAI()

    completion = client.chat.completions.create(
        #model="gpt-4o",
        model="o1",
        reasoning_effort="high",
        store=True,
        messages=[
            {"role": "system", "content": f"""
                Your role is that of a registration officer, and you must guide a user to provide complete and correct registration details: username and email.
                You are to use the chat_history and latest_user_message to ask and guide a user through giving their registration details which include username, email. 
                Be friendly and funny and also relatable. Be a guide that exchanges complimentatries when greeted.
                
                **Validation Rules:**
                - Ensure the email format is valid (e.g., `user@example.com`).
                - Ensure the email is from a verified email provier like gmail, yahoo, and other valid providers. This means check that the email is also correct and prompt the user to correct any typos. (THIS IS VERY IMPORTANT)
                - Ensure all required fields are provided.
                - If errors exist, prompt the user to correct them.
                - Note that the information you are taking from the user must be collected from both the chat_history and latest human message, this means understand and utilize context if a user has given you a username and email, but the email has inconsistencies, and you request its correction andthey send only the corrected email, remember that the username is already provided, so dont ask them again, just use the provided username and corrected email.
                - In situations where a user writes common email types, like gmail, yahoo, but maybe they forget to put .com, you can add the .com yourself or just prompt them to confirm if they meant to add com. Do the same for where there are slight errors in this basic email types correct yourself then prompt them to confirm. 


                **Response Format (MUST be in JSON):**
                - If details are correct:
                    {{
                        "A": ["username", "email"],
                        "B": Your response to the user letting them know that their message has been recieved. An example 'Thanks for submitting your details, your registration is in progress, you will recieve a mail confirming your approval. After that feel free to say hello',
                        "C": "done"
                    }}
                - If details are incorrect or incomplete:
                    {{
                        "A": [],
                        "B": Your response to the user letting them know what they need to update in the details they sent e.g "you typed xyz@gmali.co, did you mean xyz@gmail.com?". Also note if the user is having a fresh chat with you, make sure to exchange complimentaries before prompting them for registration as most people you will encounter will not know they have to register e.g "hello, how are you today, I see you are new here. Welcome, its nice to have you, to prceed with the chat you willhave to register and I will help you with that,pls provide a username of your choice and your preferred valid email". So yh, sound natural.
                        "C": "loading"
                    }}
                
                You MUST always return a JSON object exactly in this format.
            
            
            Some important points to note:
               - Avoid greeting a user you have greeted already. For example saying "Hello there" twice. Please Use the chat history provided to you to ensure you avoid doing this. 
                
            The chat history provided to you is a conversation between you (Assistant) and the User (User) 
            Please note: In the chat history provided, the responses in "User" are from the user, while those under "Assistant" are from you.
            Use the chat history to track the flow of your conversation with the user. Use it as context to the last message and use it to know what the best response is to the latest_user_message
                    
                
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
        return [response_data.get("A", []), response_data.get("B", ""), response_data.get("C", "loading")]
    except json.JSONDecodeError:
        return [[], "Error: Invalid response format from AI.", "loading"]






#.......................................................................
# Loading the vector db from GCS 
#.......................................................................

# =============================================
# 1. Configure GCS Authentication
# =============================================
# Set path to your service account JSON key
#os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"oma_baby.json"

import os
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings


def load_vector_db(directory):
    # Get path relative to THIS file
    current_dir = Path(__file__).parent
    faiss_path = current_dir / directory#"faiss_index"  # Now OS-agnostic
    
    # Verify files exist
    if not (faiss_path / "index.faiss").exists():
        raise FileNotFoundError("FAISS index.faiss missing! ")

    return FAISS.load_local(
        folder_path=str(faiss_path),
        embeddings=OpenAIEmbeddings(),
        allow_dangerous_deserialization=True
    )


# Initialize retriever
try:
    vector_db_general = load_vector_db("faiss_index")
    retriever = vector_db_general.as_retriever()
except Exception as e:
    retriever = None
    print(f"Failed to load vector DB: {str(e)}")
    

# Initialize retriever for Mediccal Tests
try:
    vector_db_med_test = load_vector_db("faiss_index_med_test")
    med_test_retriever = vector_db_med_test.as_retriever()
except Exception as e:
    med_test_retriever = None
    print(f"Failed to load vector DB: {str(e)}")



#.......................................................................
# MY AGENT CODE
#.......................................................................

# 🔹 Get API keys
openai_api_key = os.getenv("OPENAI_API_KEY")

# 🔹 Initialize LLM
#llm_tools = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
#llm = ChatOpenAI(model="gpt-4.5-preview", temperature=0, openai_api_key=openai_api_key)
llm_tools = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)


#................................................................
# RETRIEVER AND USE_CHAIN
#................................................................
prompt = ChatPromptTemplate.from_messages([
  ("system", """Role: Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
    Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
    Your long-term goal however, is to encourage users to subscribe to the comapnies Insurance services while although providing empathetic, thoughtful, and personalized responses, you are carefully guiding them towards getting one of the companies insurance services. This role must be done gradually, and not interfere with finding out the needs of the user first.
    However, You are also to respond to user's who want to get medical tests offered by wellbridg. This information is present in the "Medical Tests" in your knowledge base. Users can also ask questions about Medical tests offered by the company, which is another service completely independent off the Insurance. 
    
    Approach:
    1. Engage with empathy and personalization:
        - Acknowledge the user’s unique situation and adapt your responses based on the context of the conversation.
        - Priotize firstly understanding the requirements, problem the user faces, and recommending healthcare treatments for them, before gradually encouraging them to sign up for an Insurance
        - Health conditions like headaches, fevers, and other ailments are things users may ask for, Always ask in-depth questions to know more about what kind of ailment or what degree of severity the ailment has gotten to before recommending any treatments or insurance services
        - If a query is unclear, ask clarifying questions to gather more details.
        - Avoid technical jargon. Use simple, conversational language to create a human-like experience.
        - Reflect on past user queries and offer thoughtful follow-up suggestions when appropriate.
        - Keep answers short and friendly unless detailed responses are necessary.
        - When discussing or recommending Insurance plans for users, always state the associated prices/costs/pricing, **only when appropriate**, as this is the most important detail to the customer
    
    2. **Healthcare/other Facility Listings:**
       **Always** provide **5+ facilities** near the user’s location (e.g., Gbagada, Lagos). If fewer exist, say: "Here’s what I found – for more options, check [map service] or email hi@welbridg.com."
       
    3. **Pricing Rules:**
        - **Immediately** share costs: "The Hygeia Silver Seniors plan costs NGN41,970/month. Want annual pricing? That’s NGN503,640!"
        - If unsure: "Let me check! Email hi@welbridg.com for a quick quote."

    4. Accuracy is Key:
        - Always query your knowledge base before answering to ensure you provide accurate and trustworthy information.
        - Avoid giving incorrect or incomplete information, as this can erode user trust.
    
    5. Handling Missing Information:
        - If the information is not available, never tell the user to "speak with their insurance provider."
        - Instead, instruct them to "send a mail to hi@welbridg.com for human support" to get the assistance they need.
        
    6. You have access to data about hospitals/organizations that are under the insurance details the company offers, offered by the company.
        When a user asks for this information always return at least 5 instances to them, not one or two, but 5. 
    
    7. Always query your knowledge base before answering, do this to avoid giving false or wrong information to the User, as in industries like this
        it could make them leave due to fears of fraud. 
        
    8. Your role is also to give information about medical tests. In cases where the User asks for medical tests, simply remove any relations as to Insurance, except this question is asked in relation to an insurance type. Medical tests are completely independent off the insurances services. 
    Finally keep answers short where necessary. And Be funny and friendly

    Tone & Style:
    - Be fun and friendly, but always maintain professionalism.
    - COMPLETELY Avoid greetings like "Hi," "Hey there!".
    - Take note of conclusive statements like okay, got it etc, know to conclude conversations in this instant
    - Avoid mentioning technical terms like "database" or "tables" in responses.

    Example Responses:
    Example 1:
        User: "I’m feeling really anxious about my upcoming surgery. What should I expect?"
        Assistant: "I understand that surgery can be nerve-wracking, and it’s perfectly normal to feel anxious. Let’s take it step by step. I can share some general tips on preparing or help you connect with someone from your healthcare team for more specific guidance. How would you prefer to proceed?"
    
    Example 2:
        User: "What insurance plan is best for me?"
        Assistant: "I’d love to help you find the best plan! Could you share more about your health needs—like specific treatments or providers you prefer? I can also explain the differences between some popular plans."
    
    Key Guidelines:
    - Always prioritize building rapport and trust by creating a personalized healthcare experience.
    - Never mention technical terms like "database" or "data tables" in responses.
    - Keep responses short, clear, and fun unless the situation calls for a more detailed explanation.
    
    \n{context}\n
    """),
    ("user", "\nQuestion: {input}")
])
# OpenAI LLM
#llm = ChatOpenAI(model="o1")
# 🔹 Get API keys
openai_api_key = os.getenv("OPENAI_API_KEY")

# 🔹 Initialize LLM
#llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
general_retrieval_chain= create_retrieval_chain(retriever, document_chain)




#................................................................
# RETRIEVER AND USE_CHAIN MED-TEST RETRIVER
#................................................................
prompt = ChatPromptTemplate.from_messages([
  ("system", """Role: Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
    Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
    However, your primary role is to provide medical test information as well as recommendation to the user. 
    You're to provide them with all the details they need as it present in your knowledgde base. These details must include prices/costs/pricing, wherever the information is available and appropriate.
    You're also to provide and recommend healthcare information based on accurate information from your own understanding about health tests that are run by the company and from information you collect from the user.
    Some users might find the tests nerve wrecking, try to suit them and give them information on what they need to know about how such tests are carried out.
    Some users might need extra inforamtion on the tests, details about the tests and many more. Tell them what they need to know.
    In most cases ask users to clarify their questions clarification if the need be, do this in an interactive and friendly manner. So you can be able to provide the best possible help.

    Note this: Your Empathy and good Service comes before any price-based recommendation. Get to know the person and their health conditions deeply first before anything else 
    
    1. Engage with empathy and personalization:
        - Always get to know about the user's health conditions before making any recommendations at all. Let them feel like you understand them, before recommending any medical tests or the financial costs of getting those tests.
        - Acknowledge the user’s unique situation and adapt your responses based on the context of the conversation.
        - Priotize firstly understanding the requirements, problem the user faces, and recommending medical tests for them, 
        - Health conditions like headaches, fevers, and other ailments are things users may ask for, Always ask in-depth questions to know more about what kind of ailment or what degree of severity the ailment has gotten to before recommending any treatments or insurance services
        - If a query is unclear, ask clarifying questions to gather more details.
        - Avoid technical jargon. Use simple, conversational language to create a human-like experience.
        - Reflect on past user queries and offer thoughtful follow-up suggestions when appropriate.
        - Keep answers short and friendly unless detailed responses are necessary.
        - When discussing or recommending medical tests  for users or giving them inforamation on it, always state the associated prices/costs/pricing, **only when appropriate**, as this is the most important detail to the customer
    
    2. **Pricing Rules:**
        - **Immediately** share prices/costs/pricing
        - If unsure: "Let me check! Email hi@welbridg.com for a quick quote."

    3. Handling Missing Information:
        - If the information is not available, never tell the user to "speak with their insurance provider." However always ask follow up questions before instructing them to do anything or recommending anything. You must find out more about their needs regardless of your access to information
        - If the information is not available even after asking for more details, instruct the users to "send a mail to hi@welbridg.com for human support" to get the assistance they need.

    4. Always query your knowledge base before answering, do this to avoid giving false or wrong information to the User, as in industries like this
        it could make them leave due to fears of fraud. 
        
    5. Whenever you want to give users the tests that are run by the agency give them all the options available in your knowledge base along side the details. Always query your knowledge base before answering, do this to avoid giving false or wrong information to the User, as in industries like this
        it could make them leave due to fears of fraud. 

     Key Guidelines:
    - Always prioritize building rapport and trust by creating a personalized healthcare experience.
    - Never mention technical terms like "database" or "data tables" in responses.
    - Keep responses short, clear, and fun unless the situation calls for a more detailed explanation.
    
    Tone & Style:
    - Be fun and friendly, but always maintain professionalism.
    - COMPLETELY Avoid greetings like "Hi," "Hey there!", "good day" etc
    - Take note of conclusive statements like okay, got it etc, know to conclude conversations in this instant
    - Avoid mentioning technical terms like "database" or "tables" in responses.   
    \n{context}\n
    """),
    ("user", "\nQuestion: {input}")
])
# OpenAI LLM
llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)

#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
med_test_document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
med_test_retrieval_chain= create_retrieval_chain(med_test_retriever, document_chain)


# 🔹 Define Memory for Context Retention
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)



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

# ✅ OpenAI Client
client = OpenAI()

# ✅ Gmail API Configuration
#SERVICE_ACCOUNT_FILE = 'oma_baby_full_google.json'  # Ensure correct path
#USER_EMAIL = 'bolu@casialab.com'  # Sender's email
SERVICE_ACCOUNT_FILE = 'welbridg-agent.json'  # Ensure correct path
USER_EMAIL = 'Oma@welbridg.com'  # Sender's email
SCOPES = ['https://mail.google.com/']

# Authenticate Gmail API
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES, subject=USER_EMAIL
)
api_resource = build('gmail', 'v1', credentials=credentials)

# ............................................................
# 🔹 FUNCTION: Encode and Send Email
# ............................................................
def send_email_func_call(to, subject, body):
    """Sends an email using the Gmail API with proper Base64 encoding."""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.")

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
        return {"status": "success", "sent_to": to, "subject": subject}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e)}



import json
from openai import OpenAI
from langchain.tools import Tool


def run_my_work(user_input,users_chat_history):
        
    client = OpenAI()
    """
    chat_history = [{"role": "system", "content": system_prompt}]
    chat_history.extend(users_chat_history)  # Append past messages
    """
    chat_history = users_chat_history
    
    # ............................................................
    # 🔹 DEFINE OPENAI FUNCTIONS (TOOLS)
    # ............................................................

    # Define functions
    def get_insurance_details(query: str):
        return general_retrieval_chain.invoke({"input": query})


    def medical_test_retriever(query: str):
        return med_test_retrieval_chain.invoke({"input": query})

    
    def gmail_tool(query: str):
        try:
            company_email_details = send_email_func_call(query["company_email"], query["subject_of_company_email"], query["body_of_company_email"])
            user_email_details = send_email_func_call(query["user_email"], query["subject_of_user_email"], query["body_of_user_email"])

            #return email_details
            #result = general_retrieval_chain.invoke({"input": f"Let the user know that their details as contained in the dictionary {company_email_details} has been sent, and someone at the company will reach out to them shortly."})
            #return result['answer']
            llm_for_gmail_aspect = ChatOpenAI(model="gpt-4o", openai_api_key=os.getenv("OPENAI_API_KEY"))
            
            result = llm_for_gmail_aspect.invoke(f"Let the user know that their details as contained in the dictionary {company_email_details} has been sent, and someone at the company will reach out to them shortly.")
            return result.content #for lightweight LLm  

        except Exception as e:
            print(f"Error in sending email: {e}")
            return {"status": "error", "error": str(e)}


    # The User should also get an e-mail, "Your order has been placed successfully and a member of our team will contact you shortly"


    # Define OpenAI tools
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_insurance_details",
                "description": "Retrieve Wellbridg Ltd’s insurance details and healthcare facility information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "User inquiry about insurance or healthcare facilities"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "medical_test_retriever",
                "description": "Retrieve details about available medical tests.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "User inquiry about medical tests"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "gmail_tool",
                #"description": "Send an email using Gmail.",
                "description": "use it to create a booking for the users texting by sending an email using Gmail.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        
                        "company_email":{"type": "string", "description": "The email of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "subject_of_company_email": {"type": "string", "description": "Subject of the email you will send to the company"},
                        "body_of_company_email": {"type": "string", "description": "Body content of the email you will send to the company"},
                    
                        "user_email":{"type": "string", "description": "The users email that you will use to notify them after sending an email to the company"} ,
                        "subject_of_user_email": {"type": "string", "description": "Subject of the email you will send to the user"},
                        "body_of_user_email": {"type": "string", "description": "Body content of the email you will send to the user"}
                            
                    },
                    "required": ["company_email", "subject_of_company_email", "body_of_company_email", "user_email", "subject_of_user_email", "body_of_user_email"]
                }
            }
        }
    ]

    # Simulating user input
    #user_input = "What medical tests are available?"
    
    # Append user message to chat history
    chat_history.append({"role": "user", "content": user_input})

    # Make API call with chat history
    completion = client.chat.completions.create(
        #model="o1",
        #reasoning_effort="high",
        model="gpt-4o",
        store=True,
        messages=chat_history,  # Pass full history
        tools=tools
    )

    # Check if OpenAI wants to call a function
    if completion.choices[0].message.tool_calls:
        function_call = completion.choices[0].message.tool_calls[0]  
        function_name = function_call.function.name  
        function_args = json.loads(function_call.function.arguments) 
        
        print(f"The function called is : {function_call}") 

        if function_name == "get_insurance_details":
            result = get_insurance_details(**function_args)
            answer_text = result.get('answer', '')

        elif function_name == "medical_test_retriever":
            result = medical_test_retriever(**function_args)
            answer_text = result.get('answer', '')

        elif function_name == "gmail_tool":
            result = gmail_tool(function_args)
            answer_text = json.dumps(result, indent=2)  # Convert result to JSON string

        # Append assistant response to history
        chat_history.append({"role": "assistant", "content": answer_text})
        answer_text = answer_text.strip("'\"")  # Removes leading/trailing quotes
        return answer_text
        #return function_call

    else:
        # Regular model response
        response_text = completion.choices[0].message.content
        chat_history.append({"role": "assistant", "content": response_text})
        response_text = response_text.strip("'\"")  # Removes leading/trailing quotes
        return response_text




from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

def generate_response(message_body, wa_id, name):

    print(f" User's latest message is: {message_body}")
    startgate_context = check_db_for_startgate(wa_id)
        
    #.............Approved User....................
    if is_user_approved(session, wa_id):
        user_id = get_user_id_by_wa_id(session, wa_id)
        #print("You are approved. You can chat now!")
        #Example usage of the agent
        #question = question_rephraser(message_body,my_context)
        user_email = get_user_email_by_wa_id(session, wa_id)
        chat_history = fetch_chat_history(session, user_id, user_email, 10)
        print(chat_history)
        
        try:
            #response= use_chain(message_body, wa_id)
            response = run_my_work(message_body, chat_history)
            print(response)
            save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
            if not response.strip():
                response= "I couldn't help with that request"
                return response
            elif response == "Agent stopped due to max iterations.":
                response= "I couldn't help with that request, please try again in a few minutes"
                return response
            else:
                return response        
        except Exception as e:
            return f"An error occurred: {e}"
    
    # Approval is Pending............
    elif is_user_pending_approval(session, wa_id):
        approve_user(session, wa_id)
        return f"Hey your chat is not open yet as your approval is still pending"
    
    # User not approved
    elif is_user_approved(session, wa_id)==False: 
        x = registrer(message_body, startgate_context)
        print(x)
        A,B,C = x
    
        if C == "done":
            # have a random set ofnumbers generated which will be used for the tickets. NOTE there shoud be a tickets table
            # Register a new user
            username, email = A#, phone_number = A
            ticket_number =  generate_ticket_number()# specify the number you want if its other than 10
            
            if is_ticket_existing(session, ticket_number):
                ticket_number =  generate_ticket_number()
            elif is_ticket_existing(session, ticket_number) == False:
                #query = f"Send an email as a ticket with ticket number {ticket_number}, to boluo300@gmail.com, notifying them that user with the following details is awaiting approval to use Oma.\n Username:{username}\nEmail:{email}\nPhone Number:+{wa_id}\n \nPlease note for the name of the in cases where you want to include this in the email, use 'Oma'." 
                query =f"""Send an email as a ticket with ticket number {ticket_number}, to boluo300@gmail.com with the subject 'New User Approval Request'. The email should be written from the perspective of Oma, notifying the support team that a user is awaiting approval to use Oma. The email should include the following details:
                            Username: {username}
                            Email: {email}
                            Phone Number: +{wa_id}
                            Ensure the email is professional, concise, and requests the support team to review the request at their earliest convenience. The sender should be 'Oma', and it should not address itself as 'Dear Oma'."""
                
                query2 = f"Send an email to {email}, telling them/{username}, that a ticket has been created for them as per their request. Inform them that this is their ticket number {ticket_number}." 
                
                
                register_user(session, username, email, wa_id) 
                user_id = get_user_id_by_wa_id(session, wa_id)
                
                
                # Usage example:
                result = send_mail(query)
                user_result = send_mail(query2)
                message = f"Subject:\n {result['subject']} \n\n Body:\n {result['body']}"
                user_message_dets =f"Subject:\n {user_result['subject']} \n\n Body:\n {user_result['body']}"
                add_ticket(session, user_id=user_id, ticket_number=ticket_number, username=username, email=email, phone_number=wa_id, message=message, status="open")
                save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
                
                #This logic will be reomved somehow when I address how the team will verify the user
                approve_user(session, wa_id)
                #return B
                
                return "Email sent..... Your registration is complete, Start chatting with Oma now."
            return B
            #return "Your registration is complete, Start chatting with Oma now."
                   
        else:
            #save_message_to_db(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            return B
#..........................................................................................#







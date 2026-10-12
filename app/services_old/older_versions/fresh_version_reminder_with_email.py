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
    
    
    
    
    Company email 1: "hi@welbridg.com"
                                    Company email 2: "cokeibunor@casialab.com" 
                                    Company email 3: "debbie@casialab.com" 
                                    Company email 4: "wuraola@casialab.com"
                                    
                                    
    If the user only mentions a general time (e.g., "remind me tomorrow" or "remind me next week"), infer the specific date based on the current system date.
NOTE: SETTING REMINDERS IS DIFFERENT FROM SETTING BOOKINGS OR CREATING EMAILS FOR ANY REASON. DO NOT SET UP EMAILS FOR REMINDERS. USE THE "add_reminder_func" tool to set reminders. 
                        PLEASE NOTE REMINDERS ARE NOT BOOKINGS.
"""

def fetch_chat_history(session, user_id, user_email, username, wa_id, date_n_time, age_details, limit=10):
    
    
    # 🔹 Define System Instructions for Better Tool Selection
    system_prompt = f"""
                    🟢 Role & Purpose
                        Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
                        Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
                        Your long-term goal however, is to encourage users to subscribe to the comapnies Insurance services while although providing empathetic, thoughtful, and personalized responses, you are carefully guiding them towards getting one of the companies insurance services. This role must be done gradually, and not interfere with finding out the needs of the user first. Use the "wellbridg_Insurance_and_institutions" tool for this.
                        However, You are also to respond to user's who want to get medical tests offered by wellbridg. This information is present in the "medical_test_information" tool in your knowledge base. Users can also ask questions about Medical tests offered by the company, which is another service completely independent off the Insurance. 
        
                        Your primary responsibilities are:
                        - Providing accurate healthcare and insurance information as well as interactions and recommendations. Keep in mind the two insurance Types offered vary between Hygeia which is specifically for seniors (i.e folks that are aged 60 years old and above), and Axa which is for people who are not seniors i.e (anyone below the age of 60 years old). This information is important when talking all insurance related issues, like the insurance types and the organization they are covered under 
                        - Recommending and explaining medical tests using "medical_test_information" tool.
                        - Helping users book medical tests and insurance plans while ensuring all necessary details are collected before confirming the booking. Managing email communications via Gmail, sending booking confirmations once all details are complete.
                        - Setting reminders for users, as users might want to be reminded of some important detail later in the day, week or distant future. You are also to send them a mail after this notifying them that their reminder is set.
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
                    
                        ✅ 12. Required Information for Reminders
                        When a user wants to set a reminder up. They can just ask you to remind them of a certain detail at a certain time, or they could also specifically ask you to set a reminder for them. Regardless of how, the main information you need to collect include:
                        1. The details which they want to be reminded of
                        2. The day and time they want to be reminded
                        
                        ✅ 13. How to Collect Informationfor Reminders
                        First confirm if all the details to be collected have been given by the user. Use the chat_history to keep tabs of this. 
                        Note that apart from the day, the user must state a time for the reminder. If this is not provided, prompt the user to provide this crucial detail. 
                        
                        ✅ 14. Once all the details for the Reminder are set
                        Use the reminder tool named (add_reminder_func) to set the reminder.
                        Let the user know the reminder has been set.
                                        
                        ✅ 15. Tone & Style
                        Be fun, friendly, and professional—never robotic.
                        Keep responses conversational and engaging.
                        Ensure responses flow naturally, avoiding abrupt or generic questions.
                    
                        ✅ 16. Prohibited Actions
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
                            
                            1. You must send an email to the company emails which are as follows:
                                    Company email 1: "hi@welbridg.com"
                                    Company email 2: "cokeibunor@casialab.com" 
                                    Company email 3: "debbie@casialab.com" 
                                    Company email 4: "wuraola@casialab.com"
                                    Company email 5: "bolu@casialab.com" 
                                     
                            You are to notify them of the users request with the ffg details:  
                                - Subject: New Booking Request: [Service Type] for [Name]
                                - Content: All collected details formatted clearly.
                                - Also add a good explanation of what the user wants based on your discussions with the user. 
                                - Finally add the user_details to the body of the email you are sending, as follows:
                                        - Username:{username}
                                        - Email:{user_email}
                                        - Phone_number: {wa_id}
            
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
                        
                        
                        
                        
                        🟠 REMINDER Workflow Implementation
                        
                        🎯 Step 1: Understanding User's Reminder Request
                        Detect when a user expresses interest in setting a reminder.

                        Acknowledge their request in a friendly and engaging way.
                        Ask for the reminder details while ensuring the user specifies the exact date and time for the reminder.
                        If the reminder is unclear, ask clarifying questions to confirm.

                        🎯 Step 2: Gathering Required Information
                        To set up the reminder, collect the following details:
                        1️⃣ Reminder Text: What the user wants to be reminded about.
                        2️⃣ Date & Time for Reminder: Ensure the user provides a precise date and time (e.g., "April 5 at 3 PM") or a description that you can work with. In cases where the user doesn't state the precise date, for example they say "remind me tomorrow", "remind me next week Monday" infer the date from your knowledge of the current.
                            There will be cases where you will need to ask the user to clarify though. For example they say "remind me next week", you will need to get them to clarify the day or date.

                        If the user provides a relative time (e.g., "remind me in two hours" or "remind me on Friday"), calculate the exact date and time accordingly.
                        If they do not specify a time, ask:
                        "At what time would you like to be reminded?"

                        If they still don’t specify, default to 9 AM on the mentioned date.
                        3️⃣ User ID: Identify the user to store the reminder correctly.

                        🎯 Step 3: Confirming the Reminder
                        Before saving, summarize the reminder details back to the user for confirmation.

                        Example confirmation message:
                        "Got it! I'll remind you to [reminder_text] on [remind_at]. Does that work for you?"
                        If the user agrees, proceed to store the reminder.

                        🎯 Step 4: Storing the Reminder
                        Call the add_reminder_func with the collected details:
                        Ensure the reminder is successfully stored and confirm with the user:

                        "You're all set! I'll remind you about this at the right time. 😊"
                        Also send a confrimation email to the user.
                        
                        NOTE: The time you are to return or use in the function call must always be in this format : '%Y-%m-%d %H:%M:%S'

                        🎯 Step 5: Handling Edge Cases
                        If the user doesn’t provide a date/time:
                        Prompt them again: "When should I remind you?"
                        If no response, assume the next available morning (9 AM).
                        If the date is in the past:
                        Warn them: "That time has already passed! Would you like to set it for the same time tomorrow instead?"
                        If the user cancels or changes the reminder:
                        Allow them to edit or delete it easily.

                        🎯 Example Reminder Conversation Flow
                        👤 User: "Remind me to call the doctor tomorrow."
                        🤖 Assistant: "Got it! What time should I remind you?"
                        👤 User: "At 10 AM."
                        🤖 Assistant: "Perfect! I'll remind you to call the doctor tomorrow at 10 AM. Does that work for you?"
                        👤 User: "Yes."
                        🤖 Assistant: "You're all set! I'll remind you at the right time. 😊"
                        
                        Here are some details you will need to use in your function call to add the reminders to the db
                        The users id is : {user_id}
                        The user whatsapp number is : {wa_id}
                        
                        🎯 Send Email confirming reminder via Gmail Tools
                            Once the user confirms all the reminder details, you are to send them an email.
                                     
                            2. After that you must send an email to the user's mail "{user_email}", notifying the user that their reminder has been set with the details they provided. 
                            The user's username is {username}.
                            
    
                        
                         
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
                        
                        Note:
                        - The current time and day is: {date_n_time}
                        - Age details of subject: {age_details}                                       
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
# SETTING UP REMINDER
#................................................................................................    

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Enum, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime



# Reminder Model
class Reminder(Base):
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user_registration.id", ondelete="CASCADE"), nullable=False)
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    reminder_text = Column(Text, nullable=False)
    remind_at = Column(DateTime, nullable=False)
    status = Column(Enum('pending', 'done'), default='pending')
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

        
        
# Example Usage
#add_reminder(1, "Check the Forex market", datetime(2025, 3, 16, 10, 0))
#................................................................................................    
# Create the table in the database
Base.metadata.create_all(engine)
# Bind sessionmaker and create session
Session = sessionmaker(bind=engine)
session = Session()


       
 # Function to add a reminder
def add_reminder_func(user_id, wa_id, reminder_text, remind_at):
    #session = Session()
    try:
        dt_object = datetime.strptime(remind_at, "%Y-%m-%d %H:%M:%S")
        new_reminder = Reminder(
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
        session.close()








#................................................................................................    
# NON SESSION BASED SQL CODE  CONTEXT ANDD CHAT_HISTORY
#................................................................................................    
def check_db_for(user_id):
    # Fetch and format context
    context = get_context_from_db(session, user_id, limit=10)
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
def get_username_by_wa_id(session, wa_id):
    user = session.query(UserRegistration).filter_by(phone_number=wa_id).first()
    return user.username if user else None  # Return user_id if found, otherwise None


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




def text_maker(question, candidate):
    client = OpenAI()

    completion = client.chat.completions.create(
        model="gpt-4o",
        #model="o1",
        #reasoning_effort="high",
        store=True,
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



def send_email(to, subject, body, candidate):
    "#""Sends an email using the Gmail API with proper Base64 encoding."#""
    try:
        if not to or not subject or not body:
            raise ValueError("Missing required email fields: 'to', 'subject', or 'body'.") 
        
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
        return {"status": "success", "sent_to": to, "subject": subject}

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return {"status": "error", "error": str(e)}





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
# 🔹 LLM TO RECOMPOSE EMAIL MESSAGE
# ............................................................

def emailer(question):
    client = OpenAI()

    completion = client.chat.completions.create(
        model="gpt-4o",
        #model="o1",
        #reasoning_effort="high",
        store=True,
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
    client = OpenAI()

    completion = client.chat.completions.create(
        model="gpt-4o",
        #model="o1",
        #reasoning_effort="high",
        store=True,
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
    client = OpenAI()

    completion = client.chat.completions.create(
        model="gpt-4o",
        #model="o1",
        #reasoning_effort="high",
        store=True,
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


    def my_reminder(query: str):
        try:
            reminder = add_reminder_func(query["user_id"], query["wa_id"], query["reminder_text"], query["remind_at"])
            email = send_email_reminder_users(query["user_email"], query["subject_of_user_email"], query["body_of_user_email"], query["username"])
            
            llm = ChatOpenAI(model="gpt-4o", openai_api_key=os.getenv("OPENAI_API_KEY"))
            result = llm.invoke(f'Let the user know that their reminder has been set, and they will be reminded in the due time {query["remind_at"]}. Make the message sound as human as possible please')
            return result.content #for lightweight LLm  
            #return "Executed Bolu! Otilo!"  
            
        except Exception as e:
            print(f"Error in sending reminder: {e}")
            return {"status": "error", "error": str(e)}
            
        
        
    
    def gmail_tool(query: str):
        try:
            #company_email_details = send_email_func_call(query["company_email"], query["subject_of_company_email"], query["body_of_company_email"])
            company_email_details_1 = send_email_func_call(query["company_email1"], query["subject_of_company_email"], query["body_of_company_email"], query["username"], query["user_phone_number"],query["user_email"] )
            company_email_details_2 = send_email_func_call(query["company_email2"], query["subject_of_company_email"], query["body_of_company_email"], query["username"], query["user_phone_number"],query["user_email"])
            company_email_details_3 = send_email_func_call(query["company_email3"], query["subject_of_company_email"], query["body_of_company_email"], query["username"], query["user_phone_number"],query["user_email"])
            company_email_details_4 = send_email_func_call(query["company_email4"], query["subject_of_company_email"], query["body_of_company_email"], query["username"], query["user_phone_number"],query["user_email"])
            company_email_details_5 = send_email_func_call(query["company_email5"], query["subject_of_company_email"], query["body_of_company_email"], query["username"], query["user_phone_number"],query["user_email"])

            user_email_details = send_email_func_call_users(query["user_email"], query["subject_of_user_email"], query["body_of_user_email"], query["username"])

            #return email_details
            #result = general_retrieval_chain.invoke({"input": f"Let the user know that their details as contained in the dictionary {company_email_details_1} has been sent, and someone at the company will reach out to them shortly."})
            #return result['answer']
            llm_for_gmail_aspect = ChatOpenAI(model="gpt-4o", openai_api_key=os.getenv("OPENAI_API_KEY"))
            result = llm_for_gmail_aspect.invoke(f"Let the user know that their details as contained in the dictionary {company_email_details_1} has been sent, and someone at the company will reach out to them shortly.")
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
                        
                        #"company_email":{"type": "string", "description": "The email of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "company_email1":{"type": "string", "description": "The company email 1 of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "company_email2":{"type": "string", "description": "The company email 2 of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "company_email3":{"type": "string", "description": "The company email 3 of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "company_email4":{"type": "string", "description": "The company email 4 of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "company_email5":{"type": "string", "description": "The company email 5 of the Company i.e Welbridg. That you will be sending user details and requirments to"},
                        "subject_of_company_email": {"type": "string", "description": "Subject of the email you will send to the company"},
                        "body_of_company_email": {"type": "string", "description": "Body content of the email you will send to the company"},
                    
                        "user_email":{"type": "string", "description": "The users email that you will use to notify them after sending an email to the company"} ,
                        "subject_of_user_email": {"type": "string", "description": "Subject of the email you will send to the user"},
                        "body_of_user_email": {"type": "string", "description": "Body content of the email you will send to the user"},
                        
                        "username": {"type": "string", "description": "The username of the user"},
                        "user_phone_number": {"type": "string", "description": "The phone number of the user"}
                                  
                    },
                    "required": ["company_email", "subject_of_company_email", "body_of_company_email", "user_email", "subject_of_user_email", "body_of_user_email"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_reminder_func",
                #"description": "Send an email using Gmail.",
                "description": "Use it to set up a reminder for the user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id":{"type": "string", "description": "The id of the user"},
                        "wa_id":{"type": "string", "description": "The whatsapp number of the user"},
                        "reminder_text":{"type": "string", "description": "The content of the reminder from the user."},
                        "remind_at":{"type": "string", "description": "The date and time of the reminder, setup as a datetime format."}, 
                        
                        "user_email":{"type": "string", "description": "The users email that you will use to notify them after sending an email to the company"} ,
                        "subject_of_user_email": {"type": "string", "description": "Subject of the email you will send to the user"},
                        "body_of_user_email": {"type": "string", "description": "Body content of the email you will send to the user"},
                        "username": {"type": "string", "description": "The username of the user"}
                                  
                    },
                    "required": ["user_id","wa_id","reminder_text","remind_at","user_email","subject_of_email","body_of_user_email","username"]
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
            
        elif function_name == "add_reminder_func":
            result = my_reminder(function_args)
            answer_text = json.dumps(result, indent=2)  # Convert result to JSON string

        # Append assistant response to history
        chat_history.append({"role": "assistant", "content": answer_text})
        answer_text = answer_text#.replace('\\n', '\n').replace('\\"', '"')  # Removes leading/trailing quotes
        return answer_text
        #return function_call

    else:
        # Regular model response
        response_text = completion.choices[0].message.content
        chat_history.append({"role": "assistant", "content": response_text})
        response_text = response_text#.replace('\\n', '\n').replace('\\"', '"')  # Removes leading/trailing quotes
        return response_text



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
#..........................................................................................................

def age_interpreter(question, context):
    
    client = OpenAI()
    completion = client.chat.completions.create(
        model="gpt-4o",
        store=True,
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
        username_main = get_username_by_wa_id(session, wa_id)
        
        print(username_main)
        
        #chat_history = fetch_chat_history(session, user_id, user_email, 10)
        date_n_time= get_current_date()
        print(f"The Date and Time given to Oma is: {date_n_time}")
        
        # AGE
        context = check_db_for(user_id)
        age_details = age_interpreter(message_body, context)
        print(f"Age Details are : {age_details}")
        
        #chat_history =  fetch_chat_history(session, user_id, user_email, date_n_time, age_details, 50)
        chat_history = fetch_chat_history(session, user_id, user_email, username_main, wa_id, date_n_time, age_details, 50)
        #print(chat_history)
        
        try:
            #response= use_chain(message_body, wa_id)
            response = run_my_work(message_body, chat_history)
            response = response.replace('\\n', '\n').replace('\\"', '"') # HERE !!!!!!!!!!
            response = strip_outer_quotes(response)
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
                
                
                to_mail = "bolu@casialab.com"
                to = ["hi@welbridg.com","cokeibunor@casialab.com","debbie@casialab.com","wuraola@casialab.com"]
                subject = ticket_number + " " +"New User Approval Request"
                candidate = "Team"

                query =f"""Send an email as a ticket with ticket number {ticket_number}, to boluo300@gmail.com with the subject 'New User Approval Request'. The email should be written from the perspective of Oma, notifying the support team that a user is awaiting approval to use Oma. The email should include the following details:
                            Username: {username}
                            Email: {email}
                            Phone Number: +{wa_id}
                            Ensure the email is professional, concise, and requests the support team to review the request at their earliest convenience. The sender should be 'Oma', and it should not address itself as 'Dear Oma'."""
                
                for mail in to:
                    send_email(mail, subject, query, candidate)   
                    
                to = email
                subject = ticket_number + " " +"Your Ticket Created"
                candidate = "User"
                query2 = f"Compose an email to be sent to {username}, that a ticket has been created for them as per their request. Inform them that this is their ticket number {ticket_number}." 

                register_user(session, username, email, wa_id) 
                user_id = get_user_id_by_wa_id(session, wa_id)
                
                # Usage example:
                result = send_email(to_mail, subject, query, candidate)               
                user_result = send_email(to, subject, query2, candidate)
                
                
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







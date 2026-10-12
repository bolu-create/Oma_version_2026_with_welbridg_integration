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

# Load environment variables
load_dotenv()


#.......................................................................
# Loading the vector db from GCS 
#.......................................................................

# =============================================
# 1. Configure GCS Authentication
# =============================================
# Set path to your service account JSON key
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"oma_baby.json"

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
        raise FileNotFoundError("FAISS index.faiss missing!")

    return FAISS.load_local(
        folder_path=str(faiss_path),
        embeddings=OpenAIEmbeddings(),
        allow_dangerous_deserialization=True
    )

# Initialize retriever
try:
    vector_db = load_vector_db("faiss_index")
    retriever = vector_db.as_retriever()
except Exception as e:
    retriever = None
    print(f"Failed to load vector DB: {str(e)}")
    

# Initialize retriever for Mediccal Tests
try:
    vector_db = load_vector_db("faiss_index_med_test")
    med_test_retriever = vector_db.as_retriever()
except Exception as e:
    med_test_retriever = None
    print(f"Failed to load vector DB: {str(e)}")


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


"""
#.......................................
# Import my SQL functions
#.......................................
from app.services.my_db_funcs import is_user_approved
from app.services.my_db_funcs import register_user
from app.services.my_db_funcs import is_user_pending_approval
from app.services.my_db_funcs import approve_user
from app.services.my_db_funcs import save_message_to_db
from app.services.my_db_funcs import get_context_from_db
from app.services.my_db_funcs import save_message_for_startgate
from app.services.my_db_funcs import get_context_for_startgate
from app.services.my_db_funcs import add_ticket
from app.services.my_db_funcs import is_ticket_existing
from app.services.my_db_funcs import generate_ticket_number
from app.services.my_db_funcs import set_ticket_pending
from app.services.my_db_funcs import close_ticket
#from app.services.my_db_funcs import session
"""

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



#............................................................
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





#MY FIRST TABLE FOR BOOKINGS SAVED
#............................................................
# DB function
#............................................................
# CHAT_HISTORY
#............................................................
from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError


class BookingInfo(Base):
    __tablename__ = "booking_info"

    id = Column(Integer, primary_key=True, autoincrement=True)  # Surrogate primary key
    user_id = Column(Integer, ForeignKey("user_registration.id"), nullable=False)  # Common ID
    wa_id = Column(String(20), nullable=False)
    service_name = Column(Text, nullable=False)
    plan_name = Column(Text, nullable=False)  
    subject_name = Column(Text, nullable=False)
    subject_details = Column(Text, nullable=False)
    other_information = Column(Text, nullable=False)
    status = Column(String(20), default="in-progress")  # Can be "in-progress" or "done"y
    timestamp = Column(DateTime, default=datetime.utcnow)


def upsert_booking_info(session, user_id, wa_id, service_name, plan_name, subject_name, subject_details, other_information):
    """Insert a new booking if status is 'done', else update existing one."""
    try:
        booking = session.query(BookingInfo).filter_by(user_id=user_id).order_by(BookingInfo.timestamp.desc()).first()

        if booking and booking.status == "in-progress":
            # Update existing record
            booking.wa_id = wa_id
            booking.service_name = service_name
            booking.plan_name = plan_name
            booking.subject_name = subject_name
            booking.subject_details = subject_details
            booking.other_information = other_information
        else:
            # Create a new record (either no record exists, or last record was marked 'done')
            booking = BookingInfo(
                user_id=user_id,
                wa_id=wa_id,
                service_name=service_name,
                plan_name=plan_name,
                subject_name=subject_name,
                subject_details=subject_details,
                other_information=other_information,
                status="in-progress",  # New record always starts as 'in-progress'
            )
            session.add(booking)

        session.commit()
        return {"success": True, "message": "Booking info updated successfully."}
    except SQLAlchemyError as e:
        session.rollback()
        return {"success": False, "error": str(e)}


def get_booking_info(session, user_id):
    """Retrieve booking info only if status is 'in-progress'."""
    try:
        booking = (
            session.query(BookingInfo)
            .filter_by(user_id=user_id, status="in-progress")
            .order_by(BookingInfo.timestamp.desc())
            .first()
        )

        if booking:
            return {
                "user_id": booking.user_id,
                "wa_id": booking.wa_id,
                "service_name": booking.service_name,
                "plan_name": booking.plan_name,
                "subject_name": booking.subject_name,
                "subject_details": booking.subject_details,
                "other_information": booking.other_information,
                "status": booking.status,
                "timestamp": booking.timestamp,
            }
        else:
            return {"success": False, "message": "No active booking found."}

    except SQLAlchemyError as e:
        return {"success": False, "error": str(e)}


def update_booking_status(session, user_id, new_status):
    """Manually update the booking status for a user."""
    try:
        booking = session.query(BookingInfo).filter_by(user_id=user_id).order_by(BookingInfo.timestamp.desc()).first()
        if booking:
            booking.status = new_status
            session.commit()
            return {"success": True, "message": f"Status updated to {new_status}."}
        else:
            return {"success": False, "message": "No booking found."}
    except SQLAlchemyError as e:
        session.rollback()
        return {"success": False, "error": str(e)}

def delete_booking_info(session, user_id):
    """Delete the latest booking info for a given user_id."""
    try:
        booking = session.query(BookingInfo).filter_by(user_id=user_id).order_by(BookingInfo.timestamp.desc()).first()

        if booking:
            session.delete(booking)
            session.commit()
            return {"success": True, "message": "Booking info deleted successfully."}
        else:
            return {"success": False, "message": "No booking info found for this user."}

    except SQLAlchemyError as e:
        session.rollback()
        return {"success": False, "error": str(e)}







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
    user_id = Column(Integer, ForeignKey("user_registration.id"), nullable=False)  # Common IDii
    ticket_number = Column(String(50), unique=True, nullable=False)
    username = Column(String(100), nullable=False)
    email = Column(Text, nullable=False)
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


# Create the table in the database
Base.metadata.create_all(engine)

# Bind sessionmaker and create session
Session = sessionmaker(bind=engine)
session = Session()









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
openai_api_key = os.getenv("OPENAI_API_KEY")
llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
output_parser = StrOutputParser()
#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
retrieval_chain= create_retrieval_chain(retriever, document_chain)

#................ FUNCTION TO USE CONTEXT-SENSITIVE CHAIN.......................
def use_chain(message, health_markers):
    result = retrieval_chain.invoke({"input": message, "context": health_markers})
    return result['answer']





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
output_parser = StrOutputParser()
#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
med_test_document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
med_test_retrieval_chain= create_retrieval_chain(med_test_retriever, document_chain)
#................ FUNCTION TO USE CONTEXT-SENSITIVE CHAIN.......................
def med_test_use_chain(message):
    result = med_test_retrieval_chain.invoke({"input": message})
    return result['answer']





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
        model="o1",#"gpt-4o",
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
from langchain_google_community import GmailToolkit
import os
from langchain_openai import ChatOpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage

# Initialize LLM
#llm = ChatOpenAI(model="gpt-4o", openai_api_key=os.getenv("OPENAI_API_KEY"))
llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)


# Service Account Configuration
SERVICE_ACCOUNT_FILE = 'oma_baby_full_google.json'#os.path.join(os.path.dirname(__file__), 'oma_baby_full_google.json')  # Ensure correct path
USER_EMAIL = 'bolu@casialab.com'  # Workspace email to impersonatee
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
tools = toolkit.get_tools()

# Create agent executor
agent_executor = create_react_agent(llm, tools)

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
"""
# Usage example:
result = send_mail("send an email to boluo300@gmail.com thanking them for the bag they purchased.")

# Print result
print("\nCaptured Email Details:")
print(f"To: {result.get('to', 'Not Found')}")
print(f"Subject: {result.get('subject', 'Not Found')}")
print(f"Body: {result.get('body', 'Not Found')}")
"""


#............................................................
# LLM TO DELEGATE TASKS (Ticket, Information) 
#............................................................
import json
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")     


def question_rephraser(question, context):
    
    client = OpenAI()
    completion = client.chat.completions.create(
        model="o1",#"gpt-4o",
        reasoning_effort="high",
        store=True,
        messages=[
                    {"role": "system", "content": f"""
                    
                    You are a helpful assistant that helps rephrase the Latest User Message. You are to use the chat history provided to you to solve your task.
                    The chat history provided to you is a conversation between you (Assistant) and the User (User) 
                    Please note: In the chat history provided, the responses in "User" are from the user, while those under "Assistant" are from you.
                    
                    Task Description (Question Rephraser)
                    
                        Your role is to examine both the users latest question and the chat history, and use that to form a comprehensive and well-defined question, 
                        containing key-details based on the context. Ensure to use chat_history as context to avoid loss of important information and use only necessary 
                        details from the chat history to rephrase the latest user question. You are not to answer the question, you are to make a new question if there is available context/chat history to make it a viable question, else just return the question as it is.
                        (This is very important, please note it).
                        Also not that If the user responds with a greeting for example, (hey, good afternoon, hi ... etc), do not modify the question at all, just return it as it is.
                        Also take note of conclusive statements like okay, got it etc, know to rephrase the question in a conclusive tone.
                        
                    
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









def task_delligator(question, context):
    
    client = OpenAI()
    completion = client.chat.completions.create(
        model="o1",#"gpt-4o",
        reasoning_effort="high",
        store=True,
        messages=[
                    {"role": "system", "content": f"""
                     Task (Task Deligator)
                        You are a helpful assistant that helps classify the Latest User Message. 
                        The chat history provided to you is a conversation between you (Assistant) and the User (User) 
                        Please note: In the chat history provided, the responses in "User" are from the user, while those under "Assistant" are from you.
                    
                    
                        For the Latest User Message, you are to examine the chat history and use it as context for classifying the Latest User Message into one of the following categories: 
                                - Human: If the user message is about the user requesting to speak to a human, or a person. Use your discretion to decipher wether the user wants to speak to a human
                                - General/Insurance Information: If the user is not requesting to speak to a human or the company team etc, but is asking for insurance inforamtion or in the process of getting insurance related information, as well as some other general information about the company or health topics.
                                - Booking: If the user is requesting or is in the process of getting an insurance plan. This requires that the user must specifically be asking to get a plan, or is already in the process of getting one.
                                - Medical Tests Inforamtion: If the user is asking for anything relating to medical tests services carried out by the company. This is only in cases that have no relation to the insurance services as the insurance services also cover some medical tests,so use context from chat_history to reallly determine how to classify this.

                        So you do the classification by taking into account the flow of your conversation with the User.
                        You're to respond with just one word "human", "information", "booking" or "medical_tests" respectively, as your answer in this task, depending on the information in the text. 
                        Just the one word, no need to any other statements. 
                        
                    NOTE:
                    It is very important that you make use of the chat_history to understand the context of the Latest user message. This is so vital. 
                    There can be cases where a user is speaking with you about themselves or having a random conversation, and a recommendation for them to get a service is given, but they could reject that and say that "they just want to speak with someone",
                    Given the context of that kind of conversation, it is vital that you understand that the user wants to keep chatting with you (Assistant), so the delligation you give will
                    be Information, not human. This is just an illustration of how context can play a role, please note scenarios like this from the chat_history and how it serves context to the latest user message.
                        
                    Also one of the things you have to note when delligating using context is sometimess depending on the conversation, users might want to drift from one classification to the other while actively conversing
                    An example of this is in the when they are actively chatting with the booking, but want to switch to get some more "information.
                    An Illustration- is when a user asks for a booking then details are sent to the user and the user asks for more information on those details e.g "Tell me more about 'xyz' insurance" know then that the delligation should default to information
                    And whenever the user has gotten the info you divert back to booking immediately. Use of the chat_context is very important to achieve this 
                
                    Now your job is very critical, there are instances where lets say the user has requested for a booking, and then the assistant asks a close-ended question, and the user subsequently replies with a yes, no, nope, nothing, kinda etc.
                    You must know that considering the context, the user is still in the process of a booking and this must not be misclassified as sorting for "information" or something else. The same applies in other facets of the chat, for cases where they are in the process of booking or getting insurance information, medical-tests and so on.
                     
                    Here is the chat_history and latest user message attached below, use them for your task:
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










def booking_system(question, context, info):
    client = OpenAI()
    completion = client.chat.completions.create(
        model="o1",#"gpt-4o",
        reasoning_effort="high",
        store=True,
        messages=[
            {"role": "system", "content": f"""
                You are a friendly and fun assistant that helps book users.
                Your role involves using the latest User message and the chat history provided to you. 
                You are to sound as naturally human and conversational as possible. Avoid completely any bot-like responses

                The chat history is a conversation between you (Assistant) and the User (User). 
                Please note: 
                - Responses under "User" are from the user. 
                - Responses under "Assistant" are from you.

                ### Your Task
                Use the chat history to guide the user in booking their insurance or lab tests. The available insurance options are:
                
                **Axa Plans:**  
                - Bronze for Axa  
                - Silver for Axa  
                - Gold for Axa  
                - Platinum for Axa  
                - Platinum Plus for Axa  
                
                **Hygeia Plans:**  
                - Bronze Senior for Hygeia  
                - Silver Senior for Hygeia  
                - Gold Senior for Hygeia  
                
                While The available lab tests are:
                - Glycated Hemoglobin
                - Fasting Blood Sugar
                - Fasting Lipid Profile
                - Liver Function Test
                - Eucr (Kidney Function Test)
                - Complete Blood Count
                - PSA (Males)
                - Urinalysis
                - Urine MCS
                - Hormones (for Arthritis)
                - Pap Smear (Females)
                - Fatty Liver and Non-Alcoholic Fatty Liver
                - Ulcer Treatment
                - Type 2 Diabetes Reversal
                - Obesity (Child and Adult)
                - Insomnia
                
                You must **continue the conversation naturally** while ensuring all necessary booking details are collected.

                ### Information You Must Collect depending on which service the user wants:
                1. **Service Type**: If it is an Insurance or lab-test. 
                2. **Service Type Details:** What Insurance or lab tests the user wants.  
                3. **Subject of service:** Who the insurance or lab-test is for (self, mother, father, child, etc.).  
                4. **Details of Subject:** A short sentence containing the person's **name, age, and health condition**.  
                5. **Other Information:** Any extra details the user wants to add.  

                If some details are missing, ask the user for them **without disrupting the conversation flow**.
                
                The collected details so far are: 
                    {info}
                    - If info dictionary is available, use it to track what information is left to be collected from the user to create the booking. Subsequently, ask the user to provide any left-out information.
                    - If the info is "No Bookings", then understand that you need to start asking the user to provide information from scratch
                       
                VERY IMPORTANT NOTE:
                - In getting the required information, you are not just to check the latest_user_message, you are also to look through the entire chat_history. 
                You are to analyze every details in the conversation in the chat history with the you (Assistant) and the user (User), and search for the information you're tasked to get.
                Any information you dont get is what you then ask the user to provide. Next is an illustration of what to return when you don't get all the information from carefully scrutinizing 
                the chat_history and lates_user_message, and what to do when you get all the information you need.

                ### Expected JSON Output:
                Note that you are to always return a JSON as illustrated below, Do not return a sentence! Use the JSON format based on the conditions as shown below:

                - **If the user's details are incomplete, return a JSON!
                
                {{
                    "prompt": Ask the user for missing details in a conversational way,
                    "service_type": What service the user chooses i.e to be returned as "insurance" or "lab-test" depending on which. (Leave as empty string if no data is present),
                    "service_type_details": User's selected insurance plan or lab-test type. (Leave as empty string if no data is present),
                    "subject_of_the_service": The collected name or 'myself' if it's for the user. (Leave as empty string if no data is present),
                    "details_of_subject": A short summary including name, age, and health details.(Leave as empty string if no data is present),
                    "other_user_information": Additional user input, or 'no other information' if empty.(Leave as empty string if no data is present),
                    "status": "in-progress"
                }}
                
                - **If all details are collected, return:**

                {{
                    "prompt": Conclude the conversation with them, thanking them and informing them that their booking is in progress and they will be contacted by the wellbridg team,
                    "service_type": What service the user chooses i.e to be returned as "insurance" or "lab-test" depending on which,
                    "service_type_details": User's selected insurance plan or lab-test type,
                    "subject_of_the_service": The collected name or 'myself' if it's for the user.,
                    "details_of_subject": A short summary including name, age, and health details.,
                    "other_user_information": Additional user input, or 'no other information' if empty.,
                    "status": "done"
                }}
                
                1. In both cases, the results for "status" should be returned as shown in the individual respective json's, but "others" should be filled by your inference.
                                 
                2. Also note that the conversation and questions you are returning will be returned to the user and appended to the existing chat_history which will subsequently be returned to you with each user response. 
                This will continue until all the necessary information you want to collect is satisfied. Below you have the details on the information you are to gather. This observations and questions are the inputsto "prompt" in the JSONyou are to return.
                    
                ......
                **Important Notes:**  
                - Always analyze the **chat history** before asking for missing details.  
                - Continue the **natural flow** of the conversation.  
                - Ensure your questions make sense based on the existing chat.  
                
                NOTE:
                    It is very important that you make use of the chat_history to understand the context of the Latest user message. This is so vital. 
                    Also know that
                        
                    Here is the chat_history and latest user message attached below, use them for your task:
                    
                    Latest User Message: \n ({question})
                    Chat History:\n ({context})
                    
            """},
            {
                "role": "user",
                "content": question
            }
        ]
    )
    return completion.choices[0].message.content


    
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


#............................................................
# CODE BLOCK TO USE THE AGENT.. 
#............................................................
from app.services.llm_func import health_marker_tracker
from app.services.my_db_funcs import update_health_markers_from_json
from app.services.my_db_funcs import get_filled_health_markers
from app.services.my_llm_functions import health_marker_collector
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
        my_context = check_db_for(user_id)
        #print("You are approved. You can chat now!")
        # Example usage of the agent
        task = task_delligator(message_body,my_context)
        question = question_rephraser(message_body,my_context)
        #
        #
        #
        #
        #
        #
        #
        #health_markers = health_marker_tracker(my_context)
        retriever_context = ""
        #
        #
        #
        #
        #
        #
        #
        #
        #
        #
        
        try:
            
            if task == "information":
                response= use_chain(question, retriever_context)
                save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
                if not response.strip():
                    response= "I couldn't help with that request"
                    return response
                elif response == "Agent stopped due to max iterations.":
                    response= "I couldn't help with that request, please try again in a few minutes"
                    return response
                else:
                    return response
                
                
            elif task == "human":
                response = "Setting up a ticket for you is a capability that is coming soon. In the meantime send a mail to hi@welbridg.com for a human support with this"
                save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
                return response 
            
            
            elif task=="medical_tests":
                response= med_test_use_chain(question)
                save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
                if not response.strip():
                    response= "I couldn't help with that request"
                    return response
                elif response == "Agent stopped due to max iterations.":
                    response= "I couldn't help with that request, please try again in a few minutes"
                    return response
                else:
                    return response
                
            
            elif task == 'booking':
                info = get_booking_info(session, user_id)
                booking_details = booking_system(question, my_context, info)
                print(booking_details) #testing
                # Parse JSON
                parsed_data = json.loads(booking_details)
                print(parsed_data) #testing
                booking_status = parsed_data["status"]
                
                if booking_status == "in-progress":
                    response = parsed_data["prompt"]
                    service_name= parsed_data["service_type"]
                    plan_name= parsed_data["service_type_details"]
                    subject_name= parsed_data["subject_of_the_service"]
                    subject_details= parsed_data["details_of_subject"]
                    other_information = parsed_data["other_user_information"]
                    
                    upsert_booking_info(session, user_id=user_id, wa_id=wa_id, service_name=service_name, plan_name=plan_name, subject_name=subject_name, subject_details=subject_details, other_information=other_information)
                    save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
                    print(get_booking_info(session, user_id))
                    
                    return response
                
                 
                # Extract prompt
                elif booking_status == "done":
                    update_booking_status(session, user_id=user_id, new_status="done")
                    # Usage example:
                    response= parsed_data["prompt"]
                    service_name= parsed_data["service_type"]
                    plan_name= parsed_data["service_type_details"]
                    subject_name= parsed_data["subject_of_the_service"]
                    subject_details= parsed_data["details_of_subject"]
                    other_information = parsed_data["other_user_information"]
                    
                    if service_name == "insurance":
                        query = f"""
                                    Send an email to boluo300@gmail.com with the following details:

                                    {name} wants to get the {plan_name} insurance plan. 

                                    The insurance plan covers {'themselves' if subject_name.lower() == 'myself' else f"'{subject_name}'"}. 
                                    Here are the details of {subject_name if subject_name.lower() != 'myself' else 'their coverage'}:  
                                    {subject_details}

                                    {'' if other_information.lower() == 'no other information' else f"Additional information provided by the user: {other_information}"}.
                                """
                    elif service_name == "lab-test":
                        query = f"""
                                    Send an email to boluo300@gmail.com with the following details:

                                    {name} wants to get the {plan_name} lab test. 

                                    The test is for {'them' if subject_name.lower() == 'myself' else f"'{subject_name}'"}. 
                                    Here are the details of {subject_name if subject_name.lower() != 'myself' else 'their coverage'}:  
                                    {subject_details}

                                    {'' if other_information.lower() == 'no other information' else f"Additional information provided by the user: {other_information}"}.
                                """
                                            
                    result_a = send_mail(query)
                    message = f"Subject:\n {result_a['subject']} \n\n Body:\n {result_a['body']}"
                    ticket_number =  generate_ticket_number()# specify the number you want if its other than 10
                    username = name
                    
                    if is_ticket_existing(session, ticket_number):
                        ticket_number =  generate_ticket_number()
                    elif is_ticket_existing(session, ticket_number) == False:
                        add_ticket(session, user_id=user_id, ticket_number=ticket_number, username=username, email=message, phone_number=wa_id, message=message, status="open")
                        save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body, agent_response=response)
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
                
                return "Your registration is complete, what can I help you with today?."
            """
            register_user(session, username, email, wa_id) 
            approve_user(session, wa_id)
            #save_message_to_db(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            """
            return B
            #return "Your registration is complete, Start chatting with Oma now."
            
                
        else:
            #save_message_to_db(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
            return B
#..........................................................................................#

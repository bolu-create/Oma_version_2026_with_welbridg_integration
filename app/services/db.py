import os
import enum
from langchain_community.utilities.sql_database import SQLDatabase
from sqlalchemy import (create_engine, Column, Integer, String, Text, DateTime, Enum, ForeignKey, TIMESTAMP, func, Table, Boolean, Enum, UniqueConstraint, Numeric, Date)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv  
from datetime import datetime
import json
import random
import string

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
        #pool_recycle=1800,  # 10 minutes (safer for cloud environments)
        pool_recycle=590,  # 10 minutes (safer for cloud environments)
        pool_pre_ping=True,  # Ensure the connection is alive before using it
        pool_size=10,  # Number of connections in the pool
        max_overflow=20,  # Maximum number of connections that can be created beyond pool_size
        #connect_args={"connect_timeout": 10}  # Timeout in seconds for connecting to the server
        connect_args={
            "connect_timeout": 15,
            "read_timeout": 60,  # Explicit read timeout
            "write_timeout": 30  # Explicit write timeout
        }
    )
    """
    engine = create_engine(
        connection_string,
        pool_recycle=590,  # Recycle connections every 50secs before its 10 minutes
        pool_pre_ping=True,
        pool_size=5,  # Reduce pool_size for Render's free tier
        max_overflow=10,  # Adjust accordingly
        connect_args={
            "connect_timeout": 10,
            "read_timeout": 30,  # Explicit read timeout
            "write_timeout": 30  # Explicit write timeout
        }
    )
    """
    
    
    return engine
# Get engine for MySQL database
engine = get_engine_for_mysql_db()
# Create SQLDatabase instance for LangChain
#db = SQLDatabase(engine)

Base = declarative_base()


class InsuranceType(enum.Enum):
    axa = "AXA"
    hygeia = "Hygeia"

class RelationshipType(enum.Enum):
    self = "self"
    spouse = "spouse"
    child = "child"
    parent = "parent"
    sibling = "sibling"
    ward = "ward"
    other = "other"


class InsuranceStatus(enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    canceled = "canceled"
    expired = "expired"

class OutreachRole(enum.Enum):
    admin = "admin"
    field_expert = "field_expert"
    beneficiary = "beneficiary"   # see note — you likely won't use this one


class Gender(enum.Enum):
    male = "male"
    female = "female"


class MaritalStatus(enum.Enum):
    single = "single"
    married = "married"
    divorced = "divorced"
    widowed = "widowed"


class EducationLevel(enum.Enum):
    none = "none"
    primary = "primary"
    secondary = "secondary"
    tertiary = "tertiary"


class ConsentMethod(enum.Enum):
    verbal = "verbal"
    signature = "signature"
    thumbprint = "thumbprint"
    document = "document"      # a photographed consent form, stored in S3


class TestResult(enum.Enum):
    """Result of a point-of-care screening test.

    'not_tested' is a real value rather than NULL: at an outreach it matters
    whether someone was tested and came back negative, or was never tested at
    all. NULL can't tell those apart, and the two mean different things when
    reporting coverage.
    """
    positive = "positive"
    negative = "negative"
    not_tested = "not_tested"


class JoinRequestStage(enum.Enum):
    awaiting_admin_details = "awaiting_admin_details"           # waiting for the requester to name a vouching admin
    awaiting_admin_confirmation = "awaiting_admin_confirmation" # admin has been messaged, awaiting their yes/no
    approved = "approved"
    rejected = "rejected"

#................................................................
# TABLE FOR USER REGISTRATION
#................................................................


class OmaUserRegistration(Base):
    __tablename__ = "oma_user_registration"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    #TASKS
    #add foreign key showing the person is in a table for the outreach program
    username = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=False)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    notified = Column(Boolean, default=False)

     # --- relationships ---
    # people this user sponsors (i.e. rows where this user is the benefactor)
    beneficiaries = relationship(
        "Beneficiary",
        foreign_keys="Beneficiary.benefactor_id",
        back_populates="benefactor",
        cascade="all, delete-orphan",
    )
    insurance_policies = relationship(
        "InsuranceInfo",
        back_populates="user",
        cascade="all, delete-orphan",
    )

"""
class Beneficiary(Base): 
    __tablename__ = "beneficiaries"
    id =
    user_id = 
    benefactor_id =
    relationship_to_benefactor = 
"""
class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # the account holder who sponsors this beneficiary (required)
    benefactor_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # OPTIONAL: only set if the beneficiary ALSO has their own login account.
    # Nullable because most beneficiaries won't be registered users themselves.
    user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="SET NULL"),
        nullable=True,
    )

    # the beneficiary's own details (kept here since they're usually not system users)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    date_of_birth = Column(Date, nullable=True)
    sex = Column(String(20), nullable=True)
    phone_number = Column(String(20), nullable=True)

    relationship_to_benefactor = Column(Enum(RelationshipType), nullable=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- relationships (foreign_keys is REQUIRED here — see note below) ---
    benefactor = relationship(
        "OmaUserRegistration",
        foreign_keys=[benefactor_id],
        back_populates="beneficiaries",
    )
    self_account = relationship(
        "OmaUserRegistration",
        foreign_keys=[user_id],
    )

    __table_args__ = (
        # don't let the same registered user be added twice under one benefactor
        UniqueConstraint("benefactor_id", "user_id", name="uq_benefactor_beneficiary_user"),
    )


"""
class InsuranceInfo(Base):
    id =
    user_id= #foriegn key from oma_user_registration table
    insurance_type = 
    date_insurance_assigned =#
    insurance_status = # active, suspended, canceled, is insurance active i.e has it been paid
"""
class InsuranceInfo(Base):
    __tablename__ = "insurance_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    insurance_type = Column(Enum(InsuranceType), nullable=False)

    status = Column(Enum(InsuranceStatus), default=InsuranceStatus.pending, nullable=False)

    # coverage window
    date_insurance_assigned = Column(Date, nullable=True)
    coverage_start = Column(Date, nullable=True)
    coverage_end = Column(Date, nullable=True)

    # payment tracking
    is_paid = Column(Boolean, default=False)
    premium_amount = Column(Numeric(12, 2), nullable=True)
    last_payment_date = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("OmaUserRegistration", back_populates="insurance_policies")




#............................................................
# DB function
#............................................................
# CHAT_HISTORY
#............................................................
class OmaChatHistory(Base):
    __tablename__ = "oma_chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)  # Surrogate primary key
    user_id = Column(Integer, ForeignKey("oma_user_registration.id"), nullable=False)  # Common ID
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    name = Column(String(255), nullable=False)
    user_message = Column(Text, nullable=False)  # 'user' or 'assistant'
    agent_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    # Where the exchange happened: "whatsapp" or "web". The server default keeps
    # existing rows and any writer that doesn't set it labelled as WhatsApp.
    # Added by migrations/002_add_chat_history_channel.up.sql.
    channel = Column(String(16), nullable=False, server_default="whatsapp")




#...................................................................................................
# DB function
#............................................................
# STAGE GATE CHAT HISTORY
#............................................................
class OmaStageGate(Base):
    __tablename__ = "oma_stage_gate_chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)  # Surrogate primary key
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    name = Column(String(255), nullable=False)
    user_message = Column(Text, nullable=False)  # 'user' or 'assistant'
    agent_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
#................................................................................................    




#................................................................
# TABLE FOR TICKET
#................................................................
class OmaTicket(Base):
    __tablename__ = "oma_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("oma_user_registration.id"), nullable=False)  # Common ID
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





    
#................................................................................................    
# SETTING UP REMINDER
#................................................................................................    
# Reminder Model
class OmaReminder(Base):
    __tablename__ = "oma_reminders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("oma_user_registration.id", ondelete="CASCADE"), nullable=False)
    wa_id = Column(String(20), nullable=False) # primary_key=True)
    reminder_text = Column(Text, nullable=False)
    remind_at = Column(DateTime, nullable=False)
    status = Column(Enum('pending', 'done'), default='pending')
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

        
# Example Usage
#add_reminder(1, "Check the Forex market", datetime(2025, 3, 16, 10, 0))
#................................................................................................    



"""
#ADD Tables for beneficiaries and also tables for the onboarding 
class OmaOutreachProgramUsers(Base):
    __tablename__ = "oma_outreach_prog_users"
    id = 
    user_id = forieng key linking id to the registration table above
    status = (admin, field_expert, beneficiary)
    date_added = 
"""
class OmaOutreachProgramUsers(Base):
    __tablename__ = "oma_outreach_prog_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(Enum(OutreachRole), nullable=False)
    is_active = Column(Boolean, default=True)
    date_added = Column(DateTime, default=datetime.utcnow)

    # add_outreach_program_user() guards against duplicates with a query-then-insert,
    # which is only safe because the webhook runs one message at a time. This makes
    # the database enforce it too, so a manual INSERT or a future concurrent worker
    # can't give someone the same role twice.
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_outreach_user_role"),
    )

    # --- relationships ---
    account = relationship("OmaUserRegistration")
    # health records this staff member collected in the field
    collected_records = relationship(
        "OmaOutreachBeneficiaries",
        back_populates="recorded_by",
        foreign_keys="OmaOutreachBeneficiaries.recorded_by_id",
    )

    __table_args__ = (
        # one person shouldn't hold the same role twice in the program
        UniqueConstraint("user_id", "role", name="uq_prog_user_role"),
    )


"""
class OmaOutreachBeneficiaries(Base):
    __tablename__ = "oma_outreach_beneficiaries"
    
    id= 
    user_id = foreign key from the "oma_outreach_prog_users" table
    location = 
    health_status = 
    bmi = 
    age = 
    gender =
    marital_status =
    occupation = 
    level_of_education = 
    blood_pressure = 
    pulse = 
    temperature=
    known_chronic_conditions = 
    surgical_history = 
    allergies = 
    family_history_of_major_diseases = 
    #kids
    immunization_history = 
    birth_registration_status = 
"""

class OmaOutreachBeneficiaries(Base):
    __tablename__ = "oma_outreach_beneficiaries"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # WHO collected this record (a field_expert from the program users table)
    recorded_by_id = Column(
        Integer,
        ForeignKey("oma_outreach_prog_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- identity (stored here; the member is NOT a registered user) ---
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=True)      # theirs or a shared/household phone
    next_of_kin = Column(String(255), nullable=True)
    location = Column(String(255), nullable=False)         # village / community

    # --- consent (capture BEFORE any health data) ---
    # ── Which outreach this record belongs to ──
    # A label like "akure-2026" rather than an outreach_events table: this is an
    # annual programme, and one nullable column gives year-on-year comparison at
    # a fraction of the cost. Promote it to a real table when there is a second
    # event to justify one. Needed because analytics filters are equality/
    # contains only, so "everything from Akure 2026" isn't expressible by date.
    outreach_event = Column(String(100), nullable=True, index=True)
    # The number from WeAspire's paper register at Registration & Vitals. Oma
    # does NOT run the tally — that stays physical and covers all attendees,
    # while Oma only ever sees the opt-in subset. Recording it lets the two
    # datasets be reconciled afterwards ("of 200 screened, 34 opted in").
    tally_number = Column(String(50), nullable=True, index=True)

    informed_consent = Column(Boolean, default=False, nullable=False)
    consent_method = Column(Enum(ConsentMethod), nullable=True)
    consent_obtained_at = Column(DateTime, nullable=True)
    # S3 object key of a photographed consent form, when one was supplied.
    # Optional: verbal/signature/thumbprint consent remains perfectly valid and
    # leaves this NULL. Never a URL — links expire, keys don't.
    consent_document_key = Column(String(512), nullable=True)

    # --- demographics ---
    date_of_birth = Column(Date, nullable=True)            # often unknown in the field
    age = Column(Integer, nullable=True)                   # fallback / estimated age
    gender = Column(Enum(Gender), nullable=True)
    marital_status = Column(Enum(MaritalStatus), nullable=True)
    occupation = Column(String(255), nullable=True)
    level_of_education = Column(Enum(EducationLevel), nullable=True)

    # --- vitals & measurements (store raw values; derive BMI from them) ---
    height_cm = Column(Numeric(5, 2), nullable=True)
    weight_kg = Column(Numeric(5, 2), nullable=True)
    bmi = Column(Numeric(5, 2), nullable=True)             # computed = weight / (height_m ** 2)
    bp_systolic = Column(Integer, nullable=True)
    bp_diastolic = Column(Integer, nullable=True)
    pulse = Column(Integer, nullable=True)
    temperature = Column(Numeric(4, 1), nullable=True)     # °C

    # --- clinical history ---
    health_status = Column(Text, nullable=True)            # general assessment / notes
    known_chronic_conditions = Column(Text, nullable=True)
    surgical_history = Column(Text, nullable=True)
    allergies = Column(Text, nullable=True)
    current_medications = Column(Text, nullable=True)
    family_history_of_major_diseases = Column(Text, nullable=True)
    genotype = Column(String(5), nullable=True)            # AA, AS, SS, AC — relevant in Nigeria

    # --- child-specific ---
    immunization_history = Column(Text, nullable=True)
    birth_registration_status = Column(Boolean, nullable=True)

    # --- referral / follow-up ---
    requires_referral = Column(
        Boolean,
        default=False,
        comment=(
            "Whether this person needs to be sent to a health facility for care "
            "beyond what the outreach can provide on-site. Set True when findings "
            "exceed the team's scope — e.g. very high blood pressure, suspected "
            "pregnancy complication, a wound needing treatment, or any symptom "
            "requiring a doctor, lab test, or hospital follow-up."
        ),
    )
    referral_notes = Column(
        Text,
        nullable=True,
        comment=(
            "Free-text details of the referral: why they're being referred, "
            "which facility or department they were sent to, the urgency "
            "(routine vs. urgent vs. emergency), and any instructions given to "
            "the person. Leave blank if requires_referral is False."
        ),
    )

    # Free text can't be counted or grouped, and Indicator 1 counts people
    # "referred physically" — so the destination facility gets its own column.
    referred_to = Column(String(255), nullable=True,
                         comment="Name of the PHC or facility the person was referred to.")

    # ── Screening for the conditions the brief names ──
    # Hypertension was already covered by bp_systolic/bp_diastolic; these are
    # the other three named screening targets.
    blood_glucose = Column(Numeric(6, 2), nullable=True,
                           comment="Blood glucose reading (diabetes screening), mmol/L or mg/dL as the team records it.")
    malaria_test_result = Column(Enum(TestResult), nullable=True,
                                 comment="Point-of-care malaria test outcome.")
    eye_condition_found = Column(Boolean, nullable=True,
                                 comment="True if the eye screening found anything needing attention.")
    eye_screening_notes = Column(Text, nullable=True)

    # A named priority group with no proxy: elderly and children fall out of
    # age, pregnancy doesn't. Also matters clinically for contraindications.
    is_pregnant = Column(Boolean, nullable=True)

    # ── The Welbridg pilot ──
    # DISTINCT from informed_consent. That one means "agreed to their data being
    # recorded"; this means "agreed to be followed up by Welbridg afterwards".
    # Two separate decisions, and the pilot's success indicator rests on the
    # second one, which we previously had no way to answer.
    welbridg_followup_optin = Column(Boolean, default=False, nullable=True,
                                     comment="Opted in to Welbridg remote follow-up. Not the same as informed_consent.")
    welbridg_optin_at = Column(DateTime, nullable=True)
    # Whether remote follow-up is even possible for this person. The brief asks
    # for technology-penetration metrics at Registration & Vitals; framed
    # operationally, this is the question the pilot exists to answer.
    has_smartphone = Column(Boolean, nullable=True)
    uses_whatsapp = Column(Boolean, nullable=True)

    # ── Health education (Success Indicator 3) ──
    health_education_topics = Column(Text, nullable=True,
                                     comment="What health education this person was given on the day.")
    # The indicator is "% of attendees who report a better understanding", so
    # this is a groupable boolean rather than free text - analyse_records can
    # then report that percentage directly.
    education_understood = Column(Boolean, nullable=True)
    education_followup_notes = Column(Text, nullable=True)
    education_followup_at = Column(DateTime, nullable=True)

    # --- record metadata ---
    date_collected = Column(DateTime, default=datetime.utcnow)

    # --- relationships ---
    recorded_by = relationship(
        "OmaOutreachProgramUsers",
        back_populates="collected_records",
        foreign_keys=[recorded_by_id],
    )

#................................................................
# OUTREACH WHITELIST — pre-approved phone numbers that may self-enrol
#................................................................
# A person whose wa_id (WhatsApp phone number) is on this list is auto-enrolled
# into the outreach program with the given role during sign-up. Because wa_id is
# the actual sending number, knowing the number isn't enough — it must be them,
# from their own phone.
class OmaOutreachApprovedContact(Base):
    __tablename__ = "oma_outreach_approved_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(20), nullable=False, unique=True, index=True)  # intl format, digits only
    name = Column(String(255), nullable=True)                                   # for reference / audit
    role = Column(Enum(OutreachRole), nullable=False)                           # admin or field_expert
    added_by = Column(String(255), nullable=True)                               # who whitelisted them (ops note)
    is_enrolled = Column(Boolean, default=False)                                # have we created their program-user row yet?
    created_at = Column(DateTime, default=datetime.utcnow)


#................................................................
# OUTREACH JOIN REQUEST — the "vouch" flow for people NOT on the whitelist
#................................................................
# A prospective field_expert/admin who isn't pre-approved names an existing
# admin to vouch for them. That admin is messaged for a yes/no; on yes the
# requester is enrolled and approved. This row also carries the conversational
# state of the exchange (see JoinRequestStage).
class OmaOutreachJoinRequest(Base):
    __tablename__ = "oma_outreach_join_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # who is asking to join
    requester_user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requester_wa_id = Column(String(20), nullable=False, index=True)
    requester_name = Column(String(255), nullable=True)
    requested_role = Column(Enum(OutreachRole), nullable=False, default=OutreachRole.field_expert)

    # conversational state of the vouch exchange
    stage = Column(Enum(JoinRequestStage), nullable=False, default=JoinRequestStage.awaiting_admin_details)

    # the admin the requester named as their voucher
    vouching_admin_name = Column(String(255), nullable=True)
    vouching_admin_phone = Column(String(20), nullable=True, index=True)
    vouching_admin_user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


#................................................................
# TABLE FOR DOCUMENTS USERS ASK OMA TO KEEP FOR THEM
#................................................................
class OmaUserDocument(Base):
    """A photo a user asked Oma to hold on to, so they can ask for it back later.

    Open to every user — outreach staff and insurance users alike. Scoped by
    user_id: a document is only ever findable by the person who saved it.

    Stores the S3 KEY, never a URL. Presigned links expire in minutes; keys are
    permanent, so the link is generated fresh each time it's sent.
    """
    __tablename__ = "oma_user_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("oma_user_registration.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wa_id = Column(String(20), nullable=False, index=True)
    s3_key = Column(String(512), nullable=False)
    mime_type = Column(String(100), nullable=True)
    # What the user called it — this is what they search against later, so it is
    # their words, not a model-generated caption.
    description = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("OmaUserRegistration")


# Create the table in the database
#Base.metadata.create_all(engine)

# Bind sessionmaker and create session
"""
Session = sessionmaker(bind=engine)
session = Session()
session.rollback()
session.close()
"""

Session = sessionmaker(bind=engine)

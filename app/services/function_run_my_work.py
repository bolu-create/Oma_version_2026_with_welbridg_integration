import oma_models  # model tier per call: see oma_models.py

import json
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts.chat import ChatPromptTemplate
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.llms import OpenAI
import os
from langchain.chat_models import ChatOpenAI

from functions_2 import add_reminder_func 
from functions_for_emails import *
from langchain.memory import ConversationBufferMemory


# Load environment variables
load_dotenv()




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
    faiss_path = current_dir / directory #"faiss_index"  # Now OS-agnostic
    
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


# Initialize retriever for Medical Tests
try:
    vector_db_med_test = load_vector_db("faiss_index_med_test")
    med_test_retriever = vector_db_med_test.as_retriever()
except Exception as e:
    med_test_retriever = None
    print(f"Failed to load vector DB: {str(e)}")


#*******************************************************************************6/11/2025 Modified
# Initialize retriever for healthcare providers
try:
    vector_db_med_test = load_vector_db("faiss_index_health_providers")
    healthcare_providers_retriever = vector_db_med_test.as_retriever()
except Exception as e:
    healthcare_providers_retriever = None
    print(f"Failed to load vector DB: {str(e)}")


# Initialize retriever for Emergency Contact
try:
    vector_db_med_test = load_vector_db("faiss_index_emergency_contact_details")
    emergency_contact_retriever = vector_db_med_test.as_retriever()
except Exception as e:
    emergency_contact_retriever = None
    print(f"Failed to load vector DB: {str(e)}")


#.......................................................................
# MY AGENT CODE
#.......................................................................

# 🔹 Get API keys
openai_api_key = os.getenv("OPENAI_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")


# 🔹 Initialize LLM
#llm_tools = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=openai_api_key)
#llm = ChatOpenAI(model="gpt-4.5-preview", temperature=0, openai_api_key=openai_api_key)
llm_tools = ChatOpenAI(model=oma_models.WORKER, openai_api_key=anthropic_api_key, base_url="https://api.anthropic.com/v1/")


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
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
llm = ChatOpenAI(model=oma_models.MAIN, openai_api_key=anthropic_api_key, base_url="https://api.anthropic.com/v1/")

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
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
llm = ChatOpenAI(model=oma_models.MAIN, openai_api_key=anthropic_api_key, base_url="https://api.anthropic.com/v1/")


#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
med_test_document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
med_test_retrieval_chain= create_retrieval_chain(med_test_retriever, med_test_document_chain)







#*******************************************************************************6/11/2025 Modified
#................................................................
# RETRIEVER AND USE_CHAIN HEALTHCARE PROVIDERS
#................................................................
prompt = ChatPromptTemplate.from_messages([
  ("system", """Role:  Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
    Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
    However, your primary role is to provide healthcare providers information as well as recommendations to the user. 
    
    You're to provide them with all the details they need as is present in your knowledgde base. 
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

    3. Handling Missing Information:
        - If the information is not available, never tell the user to "speak with their insurance provider." However always ask follow up questions before instructing them to do anything or recommending anything. You must find out more about their needs regardless of your access to information
        - If the information is not available even after asking for more details, instruct the users to "send a mail to hi@welbridg.com for human support" to get the assistance they need.

    4. Always query your knowledge base before answering, do this to avoid giving false or wrong information to the User, as in industries like this
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
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
llm = ChatOpenAI(model=oma_models.MAIN, openai_api_key=anthropic_api_key, base_url="https://api.anthropic.com/v1/")


#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
healthcare_providers_document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
healthcare_providers_retrieval_chain= create_retrieval_chain(healthcare_providers_retriever, healthcare_providers_document_chain)





#................................................................
# RETRIEVER AND USE_CHAIN HEALTHCARE PROVIDERS
#................................................................
prompt = ChatPromptTemplate.from_messages([
  ("system", """Role:  Your name is Oma. You are a friendly and fun healthcare assistant and medical professional, for "Welbridg ltd", with a deep understanding of the user’s healthcare needs and a goal to get users to subscribe to the company’s provided insurance services. 
    Your main goal is to provide empathetic, thoughtful, and personalized responses, considering the full context of the conversation in response to a users needs.
    However, your primary role is to provide emergcency contact information and other details to the user. 
    You're to provide them with all the details they need as it present in your knowledgde base. These details must include Emergency numbers, the specific names of the department where available, an explanation of the description wherever the information is available and appropriate.
   
    You need to take note of the unique situation in an emergency and help guide the user to the best information that will suite their case. The descriptions of the department will help you select which department the user needs based on their situation.
    Make sure to pay attention first to the user. Make sure to follow up by checking on their conditions and asking for their health or property status depending on what they need an emergency for.
    
    
    Below is a guide for you to use to show the user how to use an emergency number properly. Use this to advice the user depending on the uniqueness of their situation, so pick where appropriate	
    
        Calling an emergency number is more than just dialing digits. To ensure a quick and effective response, follow these steps:

        - Stay calm and speak clearly. Panic can make it harder for responders to understand you.
        - Provide your exact location. Give clear details about your address, landmarks, or street name to avoid delays.
        - Describe the emergency (e.g., fire, medical crisis, accident, security threat).
        - Give your contact details. If the call disconnects, emergency responders may need to call you back.
        - Follow any instructions the operators may provide before help arrives.
        - If you cannot reach one service, consider calling another relevant agency.																						"			
            
    
    Note this: Your Empathy and good Service is very important in emergency situations
    
    1. Engage with empathy and personalization:
        - Acknowledge the user’s unique situation and adapt your responses based on the context of the conversation.
        - Priotize firstly understanding the requirements, problem the user faces, and recommending medical tests for them, 
        - If a query is unclear, ask clarifying questions to gather more details.
        - Avoid technical jargon. Use simple, conversational language to create a human-like experience.
        - Reflect on past user queries and offer thoughtful follow-up suggestions when appropriate.
        - Keep answers short and friendly unless detailed responses are necessary
       
    2. Always query your knowledge base before answering, do this to avoid giving false or wrong information to the User, as in industries like this
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
#llm = ChatOpenAI(model="o1",reasoning_effort="high", openai_api_key=openai_api_key)
llm = ChatOpenAI(model=oma_models.MAIN, openai_api_key=anthropic_api_key, base_url="https://api.anthropic.com/v1/")

#model="gpt-5",
#input=chat_history,  # Pass full history
#reasoning={ "effort": "high" }


#................................................................
# CREATE STUFF DOCUMENTS CHAIN and retriever chain
#................................................................
# Stuff documents chain
emergency_contact_document_chain = create_stuff_documents_chain(llm,prompt)
# Retriever chain
emergency_contact_retrieval_chain= create_retrieval_chain(emergency_contact_retriever, emergency_contact_document_chain)

#*******************************************************************************6/11/2025 Modified end


# 🔹 Define Memory for Context Retention
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)



def run_my_work(session, user_input, users_chat_history, image_agent_chat_history):
    
    #print(f" TYPE OF: {image_agent_chat_history}" )
        
    client = OpenAI(
        api_key=anthropic_api_key,
        base_url="https://api.anthropic.com/v1/",
    )
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


    #ALL OF THE BELOW HAVE TO BE CHANGED TO OPENAI INSTANCES
    def medical_test_retriever(query: str):
        return med_test_retrieval_chain.invoke({"input": query})


    #*******************************************************************************6/11/2025 Modified
    def healthcare_providers_retriever(query: str):
        return healthcare_providers_retrieval_chain.invoke({"input": query})
    
    def emergency_contact_detail(query: str):
        return emergency_contact_retrieval_chain.invoke({"input": query})
    #*******************************************************************************6/11/2025 Modified
    


    def my_reminder(query: str):
        try:
            reminder = add_reminder_func(session, query["user_id"], query["wa_id"], query["reminder_text"], query["remind_at"])
            email = send_email_reminder_users(query["user_email"], query["subject_of_user_email"], query["body_of_user_email"], query["username"])
            
            llm = ChatOpenAI(model=oma_models.FAST, openai_api_key=os.getenv("ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com/v1/")
            #result = llm.invoke(f'Let the user know that their reminder has been set, and they will be reminded in the due time {query["remind_at"]}. Make the message sound as human as possible please')
            result = llm.invoke(f'Let the user know that their reminder has been set, and they will be reminded in the due time. Make the message sound as human as possible please')
            return result.content #for lightweight LLm  
            #return "Great! Your reminder has been set, and I'll make sure to notify you right on time."  
            
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
            llm_for_gmail_aspect = ChatOpenAI(model=oma_models.FAST, openai_api_key=os.getenv("ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com/v1/")
            result = llm_for_gmail_aspect.invoke(f"Let the user know that their details as contained in the dictionary {company_email_details_1} has been sent, and someone at the company will reach out to them shortly.")
            return result.content #for lightweight LLm  

        except Exception as e:
            print(f"Error in sending email: {e}")
            return {"status": "error", "error": str(e)}
    # The User should also get an e-mail, "Your order has been placed successfully and a member of our team will contact you shortly"




    # FUNCTION TO REPHRASE
    def rephraser(message):
        client = OpenAI(
        api_key=anthropic_api_key, 
        base_url="https://api.anthropic.com/v1/"
        )

        completion = client.chat.completions.create( 
            model=oma_models.FAST,   # was "o1"
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




    def work_with_images(query: str):
        
        # Truncated: an image arrives as a multi-MB base64 string.
        print(f"The input is:: {str(user_input)[:300]} \n The Type is --- {type(user_input)}")
        try:
            my_entry = {
                "role": "user",
                "content": user_input
            }

            # Make sure image_agent_chat_history is a list of messages
            chat_history = image_agent_chat_history + [my_entry]

            response = client.chat.completions.create(
                model=oma_models.MAIN,
                messages=chat_history
            )

            # Extract assistant reply
            #my_report = response.choices[0].message.content
            my_report = response.choices[0].message.content
            
            length_of_response = len(my_report)
            print(f"MY REPORT:: {my_report} \n\nLenght of Response:{length_of_response}")
            
            if length_of_response >= 1400:
                rephrased = rephraser(my_report)
                return rephrased
            else:
                return my_report
            #return my_report  # return query if successful

        except Exception as e:
            error_message = f"Error while processing: {str(e)}"
            print(error_message)
            return error_message

    







    # NEWWWWW !!!!!!!!!!!!!!!!!!1 WORK HERE
    def health_outreach():
        # Truncated: an image arrives as a multi-MB base64 string.
        print(f"The input is:: {str(user_input)[:300]} \n The Type is --- {type(user_input)}")






    




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
                "name": "healthcare_providers_retriever",
                "description": "Retrieve details about healthcare providers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "User inquiry about healthcare providers"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "emergency_contact_detail",
                "description": "Retrieve details about emergency contacts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "User inquiry about emergency contacts or for if a user is in an emergency"
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
                        "remind_at":{"type": "string", "description": "The date and time of the reminder, setup as a datetime format. This is the time and date adjusted to their UTC Offset"}, 
                        
                        "user_email":{"type": "string", "description": "The users email that you will use to notify them after sending an email to the company"} ,
                        "subject_of_user_email": {"type": "string", "description": "Subject of the email you will send to the user"},
                        "body_of_user_email": {"type": "string", "description": "Body content of the email you will send to the user"},
                        "username": {"type": "string", "description": "The username of the user"}           
                    },
                    "required": ["user_id","wa_id","reminder_text","remind_at","user_email","subject_of_email","body_of_user_email","username"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "work_with_images",
                "description": "Process images and answer texts related to the images",
                "parameters": {"type": "object",
                "properties": {"query": {"type": "string",
                            "description": "A comprehensive description of the users image. alongside necessary instructions on what to respond with, depending on what the user requests or on what you consider an appropriate response.""" },
                        },
                        "required": ["query"]
                }
            }
        }
    ]


    
    #"nationality":{"type": "string", "description": "The nationality of the person which you will use to adjust the time for the reminder."}, 

    # Simulating user input
    #user_input = "What medical tests are available?"
    
    # Append user message to chat history
    chat_history.append({"role": "user", "content": user_input})

    # Make API call with chat history
    completion = client.chat.completions.create(
        #model="o1",
        #reasoning_effort="high",
        model=oma_models.MAIN,
        #store=True,   # OpenAI-only param — not supported by Anthropic
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



        #*******************************************************************************6/11/2025 Modified
        elif function_name == "healthcare_providers_retriever":
                    result = healthcare_providers_retriever(**function_args)
                    answer_text = result.get('answer', '')
                    
        elif function_name == "emergency_contact_detail":
                    result = emergency_contact_detail(**function_args)
                    answer_text = result.get('answer', '')
        #*******************************************************************************6/11/2025 Modified


        elif function_name == "gmail_tool":
            result = gmail_tool(function_args)
            #answer_text = json.dumps(result, indent=2)  # Convert result to JSON string
            answer_text = json.dumps(result, ensure_ascii=False, indent=2)  # Ensure proper encoding
            
        elif function_name == "add_reminder_func":
            result = my_reminder(function_args)
            #answer_text = json.dumps(result, indent=2)  # Convert result to JSON string
            answer_text = json.dumps(result, ensure_ascii=False, indent=2)  # Ensure proper encoding
        
              
        elif function_name == "work_with_images":
            result = work_with_images(**function_args)
            print (f"FUNCTION CALL RESULT PART:: {result}")#......................................
            #answer_text = result.get('answer', '')
            answer_text = result
            

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


import oma_models  # model tier per call: see oma_models.py
from function_run_my_work import run_my_work
import json
import documents
from openai import OpenAI


def _image_data_uri_from(user_input):
    """Pull the base64 image out of the incoming message content list.

    The model never carries the image itself — tool arguments hold only the
    description. Same approach as functions_outreach.extract_image_data_uri;
    duplicated here rather than imported to keep this module free of the
    outreach import chain.
    """
    if isinstance(user_input, list):
        for part in user_input:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    return url
    return None
#from langchain.llms import OpenAI
import os
from functions_for_emails import *


# Final function to run
def run_my_work_master(session, user_input, master_agent_chat_history, users_chat_history,
                       image_agent_chat_history, wa_id=None, user_id=None):
    # wa_id / user_id are optional and default to None so every existing caller
    # keeps working. They are only needed by the document tools: to send a saved
    # photo back, Oma has to know whose files to look in and where to send them.
    
    #print(f" TYPE OF: {image_agent_chat_history}" )
        
    client = OpenAI(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url="https://api.anthropic.com/v1/",
    )
    """
    chat_history = [{"role": "system", "content": system_prompt}]
    chat_history.extend(users_chat_history)  # Append past messages
    """
    chat_history = master_agent_chat_history

    
    # FUNCTION TO REPHRASE
    def rephraser(message):
        client = OpenAI(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            base_url="https://api.anthropic.com/v1/",
        )

        completion = client.chat.completions.create(
            model=oma_models.FAST,
            #model="o1",
            #reasoning_effort="high",
            #store=True,   # OpenAI-only param — not supported by Anthropic
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


    def regular_requests(query:str):
        return run_my_work(session, user_input, users_chat_history, image_agent_chat_history)
    
    
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

    
    # Define OpenAI tools
    tools = [
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
        },
        {
            "type": "function",
            "function": {
                "name": "regular_requests",
                "description": "answers questions not related to an image",
                "parameters": {"type": "object",
                "properties": {"query": {"type": "string",
                            "description": "A comprehensive description of the users text. alongside necessary instructions on what to respond with, depending on what the user requests or on what you consider an appropriate response.""" },
                        },
                        "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "save_my_document",
                "description": (
                    "Save a photo the user has SENT and asked you to keep for them - a receipt, "
                    "a prescription, a card, a form. Call it when they ask you to keep a photo: "
                    "either one attached to THIS message, or the last photo they sent in the past "
                    "30 minutes ('save that picture') - the tool finds that one itself, so never "
                    "ask them to resend it. The description should be in their own words, "
                    "because that is what they will search by later."
                ),
                "parameters": {"type": "object",
                    "properties": {"description": {"type": "string",
                        "description": "Short label in the user's own words, e.g. 'clinic receipt from March'."},
                    },
                    "required": ["description"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_my_document",
                "description": (
                    "SENDS a saved photo to the user. Call ONLY when they explicitly ask to see or "
                    "get back a file they saved ('send me my clinic receipt'), never to check or "
                    "verify anything: every call sends the picture again. Oma sends the picture "
                    "itself. To see what's saved, use list_my_documents."
                ),
                "parameters": {"type": "object",
                    "properties": {"description": {"type": "string",
                        "description": "Roughly what they asked for, e.g. 'the clinic receipt'."},
                    },
                    "required": ["description"],
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_my_documents",
                "description": ("List the files the user has saved with you, by name and date. "
                                "Sends nothing. Use it only when they ask what you're holding for them."),
                "parameters": {"type": "object", "properties": {}},
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
        model=oma_models.MAIN,   # picks the tool for every message; a wrong pick (e.g. re-sending a saved photo) is visible to the user
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

        if function_name == "regular_requests":
            result = regular_requests(**function_args)
            print (f"FUNCTION CALL RESULT PART:: {result}")#......................................
            #answer_text = result.get('answer', '')
            answer_text = result
         
        elif function_name == "work_with_images":
            result = work_with_images(**function_args)
            print (f"FUNCTION CALL RESULT PART:: {result}")#......................................
            #answer_text = result.get('answer', '')
            answer_text = result

        elif function_name == "save_my_document":
            # This runner is single-shot - whatever a tool returns IS the reply,
            # so these return the user-facing message rather than a payload for
            # the model to write up.
            answer_text = documents.save_user_document(
                session, user_id=user_id, wa_id=wa_id,
                data_uri=_image_data_uri_from(user_input),
                description=function_args.get("description"),
            )["message"]

        elif function_name == "get_my_document":
            answer_text = documents.send_user_document(
                session, user_id=user_id, wa_id=wa_id,
                query=function_args.get("description") or "",
            )["message"]

        elif function_name == "list_my_documents":
            answer_text = documents.list_user_documents(session, user_id)["message"]


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


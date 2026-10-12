from functions_for_emails import *
from function_run_my_work import *
from functions_1 import * 
from functions_2 import *
from funtion_master import run_my_work_master
from functions_outreach import *

from functions_1 import fetch_master_chat_history

# ........................................................MAIN BODYYYYYYY................................................................
from sqlalchemy import Table, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import json



def generate_response(session, message_body, message_type, wa_id, name):
       
    # for DEVS OPERATIONS
    #if wa_id == "2348166936127": 
    print("STARTED")
    if wa_id: 
        """So to begin, we will first need to have a message interpreter here that looks into the chat and subsequently finds wether the message relates to the 
            outreach program. If the message is for the outreach program, then we run outreach related code blocks and if the function is not for outreach programs 
            we run the regular blocks.
        """
        print(f"User's latest message is: {message_body} and is type {type(message_body)}")
        startgate_context = check_db_for_startgate(session, wa_id)
        users_country = my_country(wa_id)
        
        
        image_described = ""
        # CHECKS FOR IMAGE AND GENERATES A DESCRIPTION
        if message_type == "image/png" or   message_type == "image/jpeg":
            print("IMAGE DESCRIBED: TRUE")

            # I need to modify image described to also be able to check for and extract any text or criical info from books, notes, and containers. 
            # If it is a medical tool or product, it should look into its mind and then find all the details about that product and return all the details
            # about it that it knows. Absolutely all
            image_described = image_explainer(message_body)#........................................................TASK
            
        else:
            image_described = None
        
        print(f"IMAGE DESCRIBED DETAIL: {image_described}")

        
        # ── Outreach vouch flow (runs regardless of the sender's approval state) ──
        # Catches, BEFORE the normal routing below:
        #   (a) an admin replying YES/NO to a vouch request we sent them, and
        #   (b) a requester supplying the admin details we asked them for.
        # Returns None when this message isn't part of a live vouch exchange,
        # in which case we fall through to the usual approval branching.
        vouch_reply = handle_vouch_message(session, wa_id, name, message_body)
        if vouch_reply is not None:
            save_message_for_startgate(session, wa_id=wa_id, name=name,
                                       user_message=json.dumps(message_body),
                                       agent_response=vouch_reply)
            session.rollback()
            return vouch_reply

        #.............Approved User....................
        if is_user_approved(session, wa_id):

            user_id = get_user_id_by_wa_id(session, wa_id)
            context = check_db_for(session, user_id)
            user_event = what_is_users_msg_for(message_body, context)

            if user_event == "regular":
     
                #question = question_rephraser(message_body,my_context)
                user_email = get_user_email_by_wa_id(session, wa_id)
                username_main = get_username_by_wa_id(session, wa_id)

                date_n_time= get_current_date()
                
                # AGE
                age_details = age_interpreter(message_body, context)
                print("WORKS HERE 4")
                
                chat_history = fetch_chat_history(session, user_id, user_email, username_main, wa_id, date_n_time, age_details, users_country,message_type, 20) #50
                
                chat_history_for_image_agent = fetch_chat_history_for_image_interpreter(session, user_id, username_main, date_n_time, age_details, users_country, 20) #50 was the number of chat history messages I droped before.
                
                chat_history_for_master_agent = fetch_master_chat_history(session, user_id, username_main, message_type, 20) #50
                
                #print(chat_history)

                try:
                    #response= use_chain(message_body, wa_id)
                    print(f"TYPE OF: {type(chat_history_for_image_agent)}")
                    
                    response = run_my_work_master(session, message_body, chat_history_for_master_agent, chat_history, chat_history_for_image_agent)
                    #response = run_my_work(session, message_body, chat_history, chat_history_for_image_agent)
                    response = response.replace('\\n', '\n').replace('\\"', '"') # HERE !!!!!!!!!!
                    response_strip = strip_outer_quotes(response)
                    
                    print(f"TYPE FOR RESPONSE - STRIP:: {response_strip}")
                    print("INCODE: "+ response)
                    print(f"MESSAGE DESCRIBED !!!!!!!: {image_described}")
                    
                    # LENGHT VERIFICATION FOR TWILIO
                    response = check_and_rephrase(response_strip)
                    
                    # Change dictionary coming in to a Json. >...........................................................................................!!!!!!!!!!!
                    message_body_to_save = json.dumps(message_body)
                    
                    # Check for Image presence
                    if image_described != None:
                        save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=image_described, agent_response=response)
                    else:
                        save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=response)
                    
                    
                    # Send Messages accordingly
                    if not response.strip():
                        session.rollback()
                        session.close()
                        response= "I couldn't help with that request"
                        return response
                    elif response == "Agent stopped due to max iterations.":
                        session.rollback()
                        session.close()
                        response= "I couldn't help with that request, please try again in a few minutes"
                        return response
                    else:
                        session.rollback()
                        session.close()
                        return response  
                    
                        
                except Exception as e:
                    fallback_replies = [
                                        "Sorry, I didn’t get that — could you say it again?",
                                        "I might have missed that. Can you repeat it?",
                                        "Could you resend that message, please? I didn't quite catch that.",
                                        "Hmm, I didn’t quite catch that. Would you mind resending your message?",
                                        "Apologies, could you resend your message?",
                                        "Can you please repeat that?",
                                        "I didn’t follow — could you send that message again? Thanks",
                                        "Mind saying that one more time?"
                                    ]
                    #return f"An error occurred: {e}" # THE ERROR FOR WHEN IT REPEATS PLEASE COME AGAIN HERE.
                    response = random.choice(f"{fallback_replies} + \n {e}")
                    message_body_to_save = json.dumps(message_body)
                    save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=response)
                    session.rollback()
                    return response 


            elif user_event == "outreach":
                # we focus on everything outreach here. wether its an image that is involved or not
                user_email = get_user_email_by_wa_id(session, wa_id)
                username_main = get_username_by_wa_id(session, wa_id)
                date_n_time= get_current_date()

                # GET STATUS — resolve their outreach role: "admin" / "field_expert" / "client"
                status_info = get_user_outreach_status(session, wa_id)
                status = status_info["status"]

                try:
                    response = run_outreach_agent(session, message_body, user_id, username_main, wa_id, date_n_time, users_country, message_type, status)
                    #response = run_my_work(session, message_body, chat_history, chat_history_for_image_agent)
                    response = response.replace('\\n', '\n').replace('\\"', '"') # HERE !!!!!!!!!!
                    response_strip = strip_outer_quotes(response)
                    
                    print(f"TYPE FOR RESPONSE - STRIP:: {response_strip}")
                    print("INCODE: "+ response)
                    print(f"MESSAGE DESCRIBED !!!!!!!: {image_described}")
                    
                    # LENGHT VERIFICATION FOR TWILIO
                    response = check_and_rephrase(response_strip)
                    
                    # Change dictionary coming in to a Json. >...........................................................................................!!!!!!!!!!!
                    message_body_to_save = json.dumps(message_body)
                    
                    # Check for Image presence
                    if image_described != None:
                        save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=image_described, agent_response=response)
                    else:
                        save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=response)
                    
                    
                    # Send Messages accordingly
                    if not response.strip():
                        session.rollback()
                        session.close()
                        response= "I couldn't help with that request"
                        return response
                    elif response == "Agent stopped due to max iterations.":
                        session.rollback()
                        session.close()
                        response= "I couldn't help with that request, please try again in a few minutes"
                        return response
                    else:
                        session.rollback()
                        session.close()
                        return response  
                    
                        
                except Exception as e:
                    fallback_replies = [
                                        "Sorry, I didn’t get that — could you say it again?",
                                        "I might have missed that. Can you repeat it?",
                                        "Could you resend that message, please? I didn't quite catch that.",
                                        "Hmm, I didn’t quite catch that. Would you mind resending your message?",
                                        "Apologies, could you resend your message?",
                                        "Can you please repeat that?",
                                        "I didn’t follow — could you send that message again? Thanks",
                                        "Mind saying that one more time?"
                                    ]
                    #return f"An error occurred: {e}" # THE ERROR FOR WHEN IT REPEATS PLEASE COME AGAIN HERE.
                    response = random.choice(f"{fallback_replies} + \n {e}")
                    message_body_to_save = json.dumps(message_body)
                    save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=response)
                    session.rollback()
                    return response 

   
            elif user_event == "unsure":
                #run the AI to confirm from the user again what they are asking foR
                fallback_replies = [" Could you please restructure that message in a better way?",
                                        "could you be more specific?",
                                        "Sorry, I didn’t get that — could you say it again?",
                                        "I might have missed that. Can you repeat it?",
                                        "Could you resend that message, please? I didn't quite catch that.",
                                        "Hmm, I didn’t quite catch that. Would you mind resending your message?",
                                        "Apologies, could you resend your message?",
                                        "Can you please repeat that?",
                                        "I didn’t follow — could you send that message again? Thanks",
                                        "Mind saying that one more time?"
                                    ]
                #return f"An error occurred: {e}" # THE ERROR FOR WHEN IT REPEATS PLEASE COME AGAIN HERE.
                response = random.choice(f"{fallback_replies} + \n {e}")
                message_body_to_save = json.dumps(message_body)
                save_message_to_db(session, user_id=user_id, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=response)
                session.rollback()
                return response 


        # Approval is Pending............
        elif is_user_pending_approval(session, wa_id):
            return f"Hey your chat is not open yet, as your approval is still pending"
        
        
        
        # User not approved
        elif is_user_approved(session, wa_id)==False: 
            x = registrer(message_body, startgate_context)
            print(x)
            A,B,C,D = x
        
            # WORKING HERE

            if C == "done" and D == "none":
                # have a random set ofnumbers generated which will be used for the tickets. NOTE there shoud be a tickets table
                # Register a new user
                username, email = A #, phone_number = A
                ticket_number =  generate_ticket_number() #specify the number you want if its other than 10
                
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
                    candidate_user = "User"
                    query2 = f"Compose an email to be sent to {username}, that a ticket has been created for them as per their request. Inform them that this is their ticket number {ticket_number}." 

                    register_user(session, username, email, wa_id) 
                    user_id = get_user_id_by_wa_id(session, wa_id)
                    
                    # Usage example:
                    result = send_email(to_mail, subject, query, candidate)               
                    user_result = send_email(to, subject, query2, candidate_user)
                    
                    
                    message = f"Subject:\n {result['subject']} \n\n Body:\n {result['body']}"
                    user_message_dets =f"Subject:\n {user_result['subject']} \n\n Body:\n {user_result['body']}"
                    add_ticket(session, user_id=user_id, ticket_number=ticket_number, username=username, email=email, phone_number=wa_id, message=message, status="open")
                    
                    message_body_to_save = json.dumps(message_body)
                    save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body_to_save, agent_response=B)
                    
                    #This logic will be reomved somehow when I address how the team will verify the user
                    #approve_user(session, wa_id)

                    # Even if they didn't mention outreach, honour the whitelist:
                    # a pre-approved phone is enrolled + auto-approved on the spot.
                    wl = enroll_from_whitelist(session, user_id, wa_id)
                    if wl["enrolled"]:
                        approve_user(session, wa_id)
                        role_label = wl["role"].replace("_", " ")
                        outreach_welcome = (f"You're verified as a {role_label} for the Welbridg outreach "
                                            f"programme 🎉 You're all set — just say hello to get started.")
                        save_message_for_startgate(session, wa_id=wa_id, name=name,
                                                   user_message=message_body_to_save,
                                                   agent_response=outreach_welcome)
                        return outreach_welcome

                    return B

                    #return "Hey, How are you?"
                return B
                #return "Your registration is complete, Start chatting with Oma now."

            elif C == "done" and D == "outreach":
                # Register them on the regular system (ticket + emails, same as the
                # "none" path), then handle outreach enrolment:
                #   1) whitelisted phone  → enrol with their role + auto-approve, or
                #   2) not whitelisted    → open a vouch request (an admin must confirm).
                username, email = A
                ticket_number = generate_ticket_number()
                while is_ticket_existing(session, ticket_number):
                    ticket_number = generate_ticket_number()

                to_mail = "bolu@casialab.com"
                to = ["hi@welbridg.com","cokeibunor@casialab.com","debbie@casialab.com","wuraola@casialab.com"]
                subject = ticket_number + " " + "New User Approval Request"
                candidate = "Team"

                query = f"""Send an email as a ticket with ticket number {ticket_number}, to boluo300@gmail.com with the subject 'New User Approval Request'. The email should be written from the perspective of Oma, notifying the support team that a user is awaiting approval to use Oma. The email should include the following details:
                            Username: {username}
                            Email: {email}
                            Phone Number: +{wa_id}
                            Ensure the email is professional, concise, and requests the support team to review the request at their earliest convenience. The sender should be 'Oma', and it should not address itself as 'Dear Oma'."""

                for mail in to:
                    send_email(mail, subject, query, candidate)

                to = email
                subject = ticket_number + " " + "Your Ticket Created"
                candidate_user = "User"
                query2 = f"Compose an email to be sent to {username}, that a ticket has been created for them as per their request. Inform them that this is their ticket number {ticket_number}."

                register_user(session, username, email, wa_id)
                user_id = get_user_id_by_wa_id(session, wa_id)

                result = send_email(to_mail, subject, query, candidate)
                user_result = send_email(to, subject, query2, candidate_user)

                message = f"Subject:\n {result['subject']} \n\n Body:\n {result['body']}"
                user_message_dets = f"Subject:\n {user_result['subject']} \n\n Body:\n {user_result['body']}"
                add_ticket(session, user_id=user_id, ticket_number=ticket_number, username=username, email=email, phone_number=wa_id, message=message, status="open")

                message_body_to_save = json.dumps(message_body)

                # 1) Pre-approved by phone → enrol with their role + auto-approve.
                wl = enroll_from_whitelist(session, user_id, wa_id)
                if wl["enrolled"]:
                    approve_user(session, wa_id)
                    role_label = wl["role"].replace("_", " ")
                    outreach_welcome = (f"You're verified as a {role_label} for the Welbridg outreach "
                                        f"programme 🎉 You're all set — just say hello to get started.")
                    save_message_for_startgate(session, wa_id=wa_id, name=name,
                                               user_message=message_body_to_save,
                                               agent_response=outreach_welcome)
                    return outreach_welcome

                # 2) Not pre-approved → start the vouch flow. They must name an admin
                #    who will confirm them; their next message is picked up by
                #    handle_vouch_message() at the top of generate_response.
                start_vouch_request(session, wa_id, requester_name=username,
                                    requested_role="field_expert", user_id=user_id)
                vouch_prompt = ("Thanks — you're registered! 🎉 To activate you on the rural outreach "
                                "programme, an *admin* who already works with us needs to vouch for you.\n\n"
                                "Please reply with the *full name* and *WhatsApp number* (with country code) "
                                "of an admin you know in the field.")
                save_message_for_startgate(session, wa_id=wa_id, name=name,
                                           user_message=message_body_to_save,
                                           agent_response=vouch_prompt)
                return vouch_prompt
            
            else:
                #save_message_to_db(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
                save_message_for_startgate(session, wa_id=wa_id, name=name, user_message=message_body, agent_response=B)
                return B

            
            
    
#..........................................................................................#














def generate_response_test(message_body, message_type, wa_id, name):
    
    # CHECKS FOR IMAGE AND GENERATES A DESCRIPTION
    """
    if message_type == "image/png" or   message_type == "image/jpeg":
        image_described = image_explainer(message_body)
        
    else:
        image_described = None
    """
        
    #return f"Yeah it is the speed of returning info {wa_id}, {name}, {message_body}, {message_type}"
    return f"Yeah it is the speed of returning info {wa_id}, {name}, {message_type},{message_body}"


# DEPLOYMENT STRING YHHHHH
# NEW STRING##\
#generate_response(message_body, wa_id, name)
# https://timberwolf-mastiff-9776.twil.io/demo-reply
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from fresh_version_with_new_db import generate_response
import os



app = Flask(__name__)

@app.route("/whatsapp", methods=['POST'])  # No need for GET here
def whatsapp_reply():
    # Get message content
    incoming_msg = request.values.get('Body', '')
    
    # Get sender phone number (e.g. whatsapp:+234...)
    sender = request.values.get('From', '').lstrip("whatsapp:+")

    # Get sender name (if WhatsApp profile name is shared)
    profile_name = request.values.get('ProfileName', '')

    # Log the incoming details
    print(f"📲 Message from {profile_name} ({sender.lstrip('whatsapp:+')}): {incoming_msg}")

    
    response_text=  generate_response(incoming_msg, sender, profile_name)
    
    
    # Send response
    response = MessagingResponse()
    response.message(response_text)

    return Response(str(response), mimetype="application/xml")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # fallback to 5000 if not defined
    app.run(host='0.0.0.0', port=port)
    #app.run(port=5000)





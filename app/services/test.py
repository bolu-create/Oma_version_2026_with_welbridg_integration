from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()


#vector_store = client.vector_stores.create(        # Create vector store
vector_store = client.vector_stores.create(
    name="Axa Insurance Plans",
)


#file=open(r"C:\Users\DELL\Documents\Flask\Casia_Projects\whatsapp\python-whatsapp-bot\app\services\csv_docs\Axa_Insurance_Plans.csv", "rb")   
client.vector_stores.files.upload_and_poll(        # Upload file
    #vector_store_id=vector_store.id,
    vector_store_id=vector_store.id,
    file=open("Axa_HMO_providers.csv", "rb") 
    #file=open("Axa_Insurance_Plans.csv", "rb")   
)



#openai.NotFoundError: Error code: 404 - {'error': {'message': "No file found with id 'file-LJnJRZHb9qYPqz4oCPyB8F' in vector store 'vs_68ff998518448191a3ff30bc1750b4be'.", 'type': 'invalid_request_error', 'param': None, 'code': None}}

user_query = "What is the price of getting an Axa insurance?"

results = client.vector_stores.search(
    #vector_store_id=vector_store.id, #vs_68ff998518448191a3ff30bc1750b4be
    vector_store_id= "vs_68ff998518448191a3ff30bc1750b4be", 
    query=user_query,
)

print(results)



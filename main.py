# main.py

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import openai
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Create the OpenAI client using the API Key from environment
openai_client = openai.OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# Define your secret API Key for client apps
ALLOWED_API_KEY = "your-super-secret-key"

# Define the request body structure
class GenerateRequest(BaseModel):
    prompt: str

@app.get("/")
def read_root():
    return {"message": "Welcome to your Smart Backend!"}

@app.post("/generate")
async def generate_text(request: Request, body: GenerateRequest):
    # 1. Check API Key from client
    api_key = request.headers.get("X-API-Key")
    if api_key != ALLOWED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # 2. If API Key valid, call OpenAI API
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": body.prompt}],
            max_tokens=500,
            temperature=0.7
        )
        generated_text = response.choices[0].message.content
        return {"response": generated_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

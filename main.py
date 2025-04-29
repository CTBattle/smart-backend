from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import openai

load_dotenv()

app = FastAPI()

# Setup rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Load your keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

# Setup OpenAI client
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Validate user API key
def validate_key(request: Request):
    api_key = request.headers.get("x-api-key")
    if api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")

@app.get("/")
@limiter.limit("5/minute;100/day")
async def root(request: Request):
    validate_key(request)
    return {"message": "Smart Backend is running ✅"}

@app.post("/generate")
@limiter.limit("5/minute;100/day")
async def generate(request: Request, body: dict):
    validate_key(request)
    
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing 'prompt' in request body.")

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]
        )
        return {"response": response.choices[0].message.content}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

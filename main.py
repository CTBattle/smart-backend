from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

import openai
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Setup OpenAI
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# API Keys
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

# Plan Tiers
STARTER_KEYS = ["starterkey1", "starterkey2", "starterkey3"]
PRO_KEYS = ["prokey1", "prokey2"]
ENTERPRISE_KEYS = ["enterprisekey1"]

# Request counters
request_counts = {}

# Plan limits
PLAN_LIMITS = {
    "starter": 10000,
    "pro": 100000,
    "enterprise": float('inf')  # Unlimited
}

def get_plan(key):
    if key in STARTER_KEYS:
        return "starter"
    elif key in PRO_KEYS:
        return "pro"
    elif key in ENTERPRISE_KEYS:
        return "enterprise"
    return None

@app.middleware("http")
async def check_api_key_and_limit(request: Request, call_next):
    api_key = request.headers.get("X-API-KEY")

    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    # Identify plan
    plan = get_plan(api_key)
    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    # Track requests
    count = request_counts.get(api_key, 0) + 1

    if count > PLAN_LIMITS[plan]:
        raise HTTPException(status_code=429, detail="Monthly usage limit exceeded. Upgrade your plan.")

    request_counts[api_key] = count

    response = await call_next(request)
    return response

@app.get("/")
async def read_root():
    return {"message": "Welcome to Smart Backend API!"}

@app.post("/generate")
async def generate_code(request: Request):
    body = await request.json()
    prompt = body.get("prompt")

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    generated_code = response.choices[0].message.content.strip()

    return {"generated_code": generated_code}

@app.post("/reset")
async def reset_counters():
    """Manually reset all counters. (Eventually we'll automate monthly reset.)"""
    for key in request_counts.keys():
        request_counts[key] = 0
    return {"message": "All counters have been reset."}

@app.get("/usage")
async def get_usage(request: Request):
    """Returns how many requests the current API key has used."""
    api_key = request.headers.get("X-API-KEY")

    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    count = request_counts.get(api_key, 0)
    plan = get_plan(api_key)

    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    limit = PLAN_LIMITS[plan]
    remaining = limit - count if limit != float('inf') else "Unlimited"

    return {
        "plan": plan,
        "used": count,
        "remaining": remaining
    }

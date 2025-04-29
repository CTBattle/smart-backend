from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
import openai

# Load environment variables
load_dotenv()

# Initialize app
app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Setup OpenAI
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Load key groups
STARTER_KEYS = os.getenv("STARTER_KEYS", "").split(",")
PRO_KEYS = os.getenv("PRO_KEYS", "").split(",")
ENTERPRISE_KEYS = os.getenv("ENTERPRISE_KEYS", "").split(",")

# All valid keys
VALID_API_KEYS = STARTER_KEYS + PRO_KEYS + ENTERPRISE_KEYS

# Plan limits
PLAN_LIMITS = {
    "starter": 10000,       # 10k requests
    "pro": 100000,          # 100k requests
    "enterprise": float('inf')  # unlimited
}

# Track requests
request_counts = {}

def get_plan(api_key: str):
    if api_key in STARTER_KEYS:
        return "starter"
    elif api_key in PRO_KEYS:
        return "pro"
    elif api_key in ENTERPRISE_KEYS:
        return "enterprise"
    return None

@app.middleware("http")
async def check_api_key_and_limit(request: Request, call_next):
    api_key = request.headers.get("X-API-KEY")

    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    plan = get_plan(api_key)
    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    count = request_counts.get(api_key, 0) + 1
    if count > PLAN_LIMITS[plan]:
        raise HTTPException(status_code=429, detail="Monthly usage limit exceeded. Upgrade your plan.")

    request_counts[api_key] = count
    response = await call_next(request)
    return response

@app.get("/")
async def root():
    return {"message": "Welcome to the Smart Backend API!"}

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

@app.get("/usage")
async def get_usage(request: Request):
    api_key = request.headers.get("X-API-KEY")

    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    count = request_counts.get(api_key, 0)
    plan = get_plan(api_key)
    limit = PLAN_LIMITS[plan]
    remaining = limit - count if limit != float('inf') else "Unlimited"

    return {
        "plan": plan,
        "used": count,
        "remaining": remaining
    }

@app.post("/reset")
async def reset_counters():
    for key in request_counts.keys():
        request_counts[key] = 0
    return {"message": "Request counters have been reset."}

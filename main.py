from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import openai
import stripe
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Load environment variables
load_dotenv()

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# OpenAI setup
openai.api_key = os.getenv("OPENAI_API_KEY")

# Stripe setup
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# API Keys
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

# Tier groups
STARTER_KEYS = os.getenv("STARTER_KEYS", "").split(",")
PRO_KEYS = os.getenv("PRO_KEYS", "").split(",")
ENTERPRISE_KEYS = os.getenv("ENTERPRISE_KEYS", "").split(",")

# Request counters (in-memory for now)
request_counts = {}

# Limits per tier
PLAN_LIMITS = {
    "starter": 10000,
    "pro": 100000,
    "enterprise": float("inf")
}

def get_plan(api_key):
    if api_key in STARTER_KEYS:
        return "starter"
    elif api_key in PRO_KEYS:
        return "pro"
    elif api_key in ENTERPRISE_KEYS:
        return "enterprise"
    return None

@app.middleware("http")
async def validate_key_and_limit(request: Request, call_next):
    api_key = request.headers.get("X-API-KEY")
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    plan = get_plan(api_key)
    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized tier")

    used = request_counts.get(api_key, 0)
    if used >= PLAN_LIMITS[plan]:
        raise HTTPException(status_code=429, detail="Usage limit exceeded")

    request_counts[api_key] = used + 1
    response = await call_next(request)
    return response

@app.get("/")
def read_root():
    return {"message": "Smart Backend is live."}

@app.post("/generate")
async def generate(request: Request):
    body = await request.json()
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return {"generated_code": response.choices[0].message.content.strip()}

@app.get("/usage")
async def get_usage(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Missing API key")

    plan = get_plan(api_key)
    used = request_counts.get(api_key, 0)
    limit = PLAN_LIMITS[plan]
    return {
        "plan": plan,
        "used": used,
        "remaining": "Unlimited" if limit == float("inf") else limit - used
    }

@app.post("/reset")
def reset_usage():
    for key in request_counts:
        request_counts[key] = 0
    return {"message": "Request counts reset."}

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook error")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print("✅ Payment succeeded!", session)

    return JSONResponse(status_code=200, content={"status": "received"})

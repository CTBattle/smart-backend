from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from dotenv import load_dotenv
import openai
import stripe
import os

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Setup
app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# OpenAI client
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Stripe client
stripe.api_key = STRIPE_SECRET_KEY

# Valid API keys
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

# Key plans
STARTER_KEYS = [f"battlekey{str(i).zfill(3)}" for i in range(1, 101)]
PRO_KEYS = [f"prokey{str(i).zfill(3)}" for i in range(1, 101)]
ENTERPRISE_KEYS = [f"enterprisekey{str(i).zfill(3)}" for i in range(1, 101)]

PLAN_LIMITS = {
    "starter": 10000,
    "pro": 100000,
    "enterprise": float("inf")
}
request_counts = {}

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

    plan = get_plan(api_key)
    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    count = request_counts.get(api_key, 0) + 1
    if count > PLAN_LIMITS[plan]:
        raise HTTPException(status_code=429, detail="Monthly limit exceeded.")

    request_counts[api_key] = count
    response = await call_next(request)
    return response

@app.get("/")
def root():
    return {"message": "Smart Backend API is live!"}

@app.post("/generate")
async def generate_code(request: Request):
    data = await request.json()
    prompt = data.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt.")

    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    code = response.choices[0].message.content.strip()
    return {"generated_code": code}

@app.get("/usage")
async def get_usage(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    plan = get_plan(api_key)
    count = request_counts.get(api_key, 0)
    limit = PLAN_LIMITS[plan]
    remaining = limit - count if limit != float("inf") else "Unlimited"
    return {"plan": plan, "used": count, "remaining": remaining}

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print("✅ Checkout completed:", session)
    else:
        print("Unhandled event type:", event["type"])

    return {"status": "success"}

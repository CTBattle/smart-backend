from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os
import openai
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
import stripe
from email.message import EmailMessage
import aiosmtplib

# Load environment variables
load_dotenv()

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Setup OpenAI
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# API Keys
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

STARTER_KEYS = [
    "battlekey001", "battlekey002", "battlekey003"
    # Add the rest as needed
]
PRO_KEYS = [
    "battlekey101", "battlekey102", "battlekey103"
    # Add the rest as needed
]
ENTERPRISE_KEYS = [
    "battlekey201", "battlekey202", "battlekey203"
    # Add the rest as needed
]

# Request counters
request_counts = {}

PLAN_LIMITS = {
    "starter": 10000,
    "pro": 100000,
    "enterprise": float('inf')
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
        messages=[{"role": "user", "content": prompt}]
    )

    generated_code = response.choices[0].message.content.strip()
    return {"generated_code": generated_code}

@app.post("/reset")
async def reset_counters():
    for key in request_counts.keys():
        request_counts[key] = 0
    return {"message": "All request counters reset."}

@app.get("/usage")
async def get_usage(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    count = request_counts.get(api_key, 0)
    plan = get_plan(api_key)

    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    limit = PLAN_LIMITS[plan]
    remaining = limit - count if limit != float('inf') else "Unlimited"
    return {"plan": plan, "used": count, "remaining": remaining}

# Stripe Webhook and Email Handling
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

UNUSED_KEYS = {
    "starter": STARTER_KEYS.copy(),
    "pro": PRO_KEYS.copy(),
    "enterprise": ENTERPRISE_KEYS.copy()
}

def get_key_for_plan(plan):
    if UNUSED_KEYS[plan]:
        return UNUSED_KEYS[plan].pop(0)
    return None

async def send_key_email(to_email, key, plan):
    msg = EmailMessage()
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = f"Your SmartBackend {plan.capitalize()} API Key"
    msg.set_content(f"Thanks for your purchase!\n\nHere is your API key: {key}\n\nEnjoy your access.")
    await aiosmtplib.send(msg, hostname=SMTP_HOST, port=SMTP_PORT, start_tls=True,
                          username=EMAIL_USER, password=EMAIL_PASS)

@app.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, stripe_webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")
        price_id = session["metadata"]["price_id"]

        plan = {
            "price_1RJ5sJIIj61Y9MIRxvV1cMG6": "starter",
            "price_PRO_ID_HERE": "pro",
            "price_ENTERPRISE_ID_HERE": "enterprise"
        }.get(price_id)

        if not plan:
            raise HTTPException(status_code=400, detail="Unknown plan")

        api_key = get_key_for_plan(plan)
        if api_key:
            await send_key_email(customer_email, api_key, plan)
        else:
            print("No available keys for this plan!")

    return {"status": "success"}

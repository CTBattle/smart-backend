from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from dotenv import load_dotenv
import stripe
import openai
import os

# Load environment variables
load_dotenv()

# Setup FastAPI and limiter
app = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Setup OpenAI
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Setup Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Webhook secret (Stripe sends events to this)
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Load valid keys and tiers
VALID_API_KEYS = os.getenv("VALID_API_KEYS", "").split(",")

STARTER_KEYS = os.getenv("STARTER_KEYS", "").split(",")
PRO_KEYS = os.getenv("PRO_KEYS", "").split(",")
ENTERPRISE_KEYS = os.getenv("ENTERPRISE_KEYS", "").split(",")

PLAN_LIMITS = {
    "starter": 10_000,
    "pro": 100_000,
    "enterprise": float('inf')
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

# ✅ Health check or root welcome route
@app.get("/")
async def read_root():
    return {"message": "Welcome to Smart Backend API!"}

# ✅ API key + rate limit middleware
@app.middleware("http")
async def check_api_key_and_limit(request: Request, call_next):
    if request.url.path.startswith("/webhook"):
        return await call_next(request)

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
    return await call_next(request)

# ✅ Code generation endpoint
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

    return {"generated_code": response.choices[0].message.content.strip()}

# ✅ Manual reset (admin/debug)
@app.post("/reset")
async def reset_counters():
    request_counts.clear()
    return {"message": "Request counters reset."}

# ✅ Usage report
@app.get("/usage")
async def get_usage(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if not api_key or api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")

    plan = get_plan(api_key)
    if not plan:
        raise HTTPException(status_code=403, detail="Unauthorized API key.")

    used = request_counts.get(api_key, 0)
    limit = PLAN_LIMITS[plan]
    remaining = "Unlimited" if limit == float('inf') else limit - used

    return {"plan": plan, "used": used, "remaining": remaining}

# ✅ Stripe Webhook
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")

    if event["type"] == "checkout.session.completed":
        print("✅ Payment complete:", event["data"]["object"]["id"])

    return JSONResponse(status_code=200, content={"message": "Webhook received."})

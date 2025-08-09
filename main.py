# main.py
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, constr
import os, requests
from azure.identity import ManagedIdentityCredential

app = FastAPI()

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")

@app.get("/")
async def root():
    return {"message": "FastAPI backend is running"}

# --- CORS: support one or many origins via comma-separated env var ---
SWA_ORIGIN = os.getenv("SWA_ORIGIN",
    "http://127.0.0.1:5501/"
)
ALLOW_ORIGINS = [o.strip() for o in SWA_ORIGIN.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

# --- Model (Python 3.8/3.9 safe) ---
class Contact(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    email: EmailStr
    message: constr(strip_whitespace=True, min_length=5, max_length=4000)
    phone: Optional[constr(strip_whitespace=True, max_length=40)] = None
    website: Optional[str] = None  # honeypot

# --- Email via Microsoft Graph using Managed Identity ---
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
MAILBOX_UPN = os.getenv("MAILBOX_UPN")  # shared mailbox or user UPN
credential = ManagedIdentityCredential()

def send_mail_via_graph(subject: str, body_html: str, reply_to: str):
    if not MAILBOX_UPN:
        raise HTTPException(status_code=500, detail="MAILBOX_UPN not configured")
    token = credential.get_token(GRAPH_SCOPE).token
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX_UPN}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": MAILBOX_UPN}}],
            "replyTo": [{"emailAddress": {"address": reply_to}}],
        },
        "saveToSentItems": True,
    }
    resp = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code not in (200, 202):
        raise HTTPException(status_code=500, detail=f"Graph sendMail failed: {resp.text}")

@app.post("/contact")
def contact(c: Contact):
    # Honeypot: bots fill hidden field; we pretend success
    if c.website:
        return {"status": "ok"}

    # Avoid backslash-in-fstring issues
    message_html = c.message.replace("\n", "<br/>")
    body_html = (
        f"<p><b>Name:</b> {c.name}</p>"
        f"<p><b>Email:</b> {c.email}</p>"
        f"<p><b>Phone:</b> {c.phone or '-'}</p>"
        f"<p><b>Message:</b><br/>{message_html}</p>"
    )

    # Send email
    send_mail_via_graph(
        subject=f"New website enquiry from {c.name}",
        body_html=body_html,
        reply_to=c.email,
    )
    return {"status": "ok"}

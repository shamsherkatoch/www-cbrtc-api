import os, html, time
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
import httpx 

app = FastAPI()

# --- CORS (keep or remove if you proxy via SWA /api/*) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://salmon-coast-0bb767a00.5.azurestaticapps.net",
        "https://www.cbrtc.com.au"
    ],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "cf-turnstile-response"],
)

# --- UAMI + Key Vault ---
UAMI_CLIENT_ID = os.environ["AZURE_CLIENT_ID"]            # UAMI client id
KEYVAULT_URL   = os.environ["KEYVAULT_URL"]               # Key Vault

cred = ManagedIdentityCredential(client_id=UAMI_CLIENT_ID)
kv  = SecretClient(vault_url=KEYVAULT_URL, credential=cred)

# Simple in-process cache so we don’t hit KV every request
_SECRET_CACHE: Dict[str, Dict[str, str]] = {}
_CACHE_TTL_SECONDS = 300

def get_secret(name: str) -> str:
    now = time.time()
    entry = _SECRET_CACHE.get(name)
    if entry and now - entry["ts"] < _CACHE_TTL_SECONDS:
        return entry["val"]
    try:
        val = kv.get_secret(name).value  # no version => always latest
        _SECRET_CACHE[name] = {"val": val, "ts": now}
        return val
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key Vault read failed for '{name}': {e}")

# Graph constants
GRAPH_SCOPE = "https://graph.microsoft.com/.default"

class ContactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=8000)
    phone: Optional[str] = Field(None, max_length=100)

async def send_mail_via_graph(subject: str, body_html: str, reply_to: Optional[str] = None):
    sender_upn = get_secret("Graph-Sender-Upn")
    contact_to = get_secret("Contact-To")

    # Acquire Graph token using UAMI
    try:
        token = cred.get_token(GRAPH_SCOPE).token
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Managed Identity auth failed: {e}")

    url = f"https://graph.microsoft.com/v1.0/users/{sender_upn}/sendMail"
    payload = {
        "message": {
            "subject": subject[:255],
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": contact_to}}],
        },
        "saveToSentItems": "false"
    }
    if reply_to:
        payload["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Graph send failed: {r.status_code} {r.text}")

@app.post("/contact")
async def contact(c: ContactIn, cf_turnstile_response: Optional[str] = Header(None)):
    # (Optional) verify Turnstile: secret = get_secret("Turnstile-Secret") and call Cloudflare siteverify
    msg_html = "<br/>".join(html.escape(line) for line in c.message.splitlines())
    body = (
        f"<p><b>Name:</b> {html.escape(c.name)}</p>"
        f"<p><b>Email:</b> {html.escape(c.email)}</p>"
        f"<p><b>Phone:</b> {html.escape(c.phone) if c.phone else '-'}</p>"
        f"<p><b>Message:</b><br/>{msg_html}</p>"
    )
    await send_mail_via_graph(
        subject=f"Website enquiry from {c.name}",
        body_html=body,
        reply_to=c.email
    )
    return {"ok": True}

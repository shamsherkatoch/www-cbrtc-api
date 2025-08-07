from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import smtplib
from email.message import EmailMessage
import os

app = FastAPI()

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")

# Add CORS middleware here
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://salmon-coast-0bb767a00.5.azurestaticapps.net"],  # Or ["*"] during testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "FastAPI backend is running"}

class ContactForm(BaseModel):
    senderName: str
    senderEmail: str
    message: str

@app.post("/send-contact-email")
async def send_contact_email(form: ContactForm):
    msg = EmailMessage()
    msg["Subject"] = f"Contact Form Submission from {form.senderName}"
    msg["From"] = os.environ["O365_USER"]
    msg["To"] = os.environ["CONTACT_RECEIVER"]
    msg.set_content(f"Name: {form.senderName}\nEmail: {form.senderEmail}\n\nMessage:\n{form.message}")

    try:
        with smtplib.SMTP("smtp.office365.com", 587) as smtp:
            smtp.starttls()
            smtp.login(os.environ["O365_USER"], os.environ["O365_PASS"])
            smtp.send_message(msg)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


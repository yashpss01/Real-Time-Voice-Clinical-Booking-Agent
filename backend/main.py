import os
import asyncio
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from backend.memory.database import init_db, SessionLocal, Doctor, Appointment, Patient
from backend.memory.redis_client import RedisSessionStore
from backend.websocket.stream import router as websocket_router

# Initialize FastAPI application
app = FastAPI(
    title="Clinical Voice AI Booking Gateway",
    description="Low-latency real-time multilingual conversational backend",
    version="1.0.0"
)

# Set CORS origins to connect with Next.js client
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3001", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize and seed database on startup
@app.on_event("startup")
def startup_event():
    print("Starting Clinical Booking Backend...")
    try:
        init_db()
    except Exception as e:
        print(f"Error seeding database on startup: {e}")

# DB Dependency injection helper
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Include WebSocket routing
app.include_router(websocket_router)

@app.get("/health")
def health_check():
    """Simple status check endpoint."""
    return {"status": "healthy", "service": "Voice Booking Agent Gateway"}

# REST endpoints for visual dashboard monitoring
@app.get("/api/doctors")
def get_doctors_list(db: Session = Depends(get_db)):
    """Fetches all clinical doctors to populate the dashboard grid."""
    doctors = db.query(Doctor).all()
    return [
        {
            "id": str(doc.id),
            "name": doc.name,
            "specialization": doc.specialization,
            "languages": doc.preferred_language.split(",")
        }
        for doc in doctors
    ]

@app.get("/api/appointments")
def get_appointments_list(db: Session = Depends(get_db)):
    """Fetches all active booked appointments to show live scheduling metrics."""
    appointments = db.query(Appointment).filter(Appointment.status == "BOOKED").all()
    return [
        {
            "id": str(appt.id),
            "doctor_name": appt.doctor.name,
            "specialization": appt.doctor.specialization,
            "patient_name": appt.patient.name,
            "patient_phone": appt.patient.phone,
            "slot": appt.slot.isoformat(),
            "status": appt.status
        }
        for appt in appointments
    ]

@app.get("/api/session/{session_id}/transcript")
def get_session_transcript(session_id: str):
    """Retrieves cached conversational transcript logs for active display."""
    session = RedisSessionStore.get_session(session_id)
    return {
        "session_id": session_id,
        "transcript": session.get("transcript_history", []),
        "preferred_language": session.get("preferred_language", "en")
    }

@app.post("/api/campaign/reminder")
async def trigger_reminder_campaign(db: Session = Depends(get_db)):
    """Outbound Reminder Campaign Simulator.
    
    Acts as the periodic background scheduler to scan database for upcoming slots 
    within 24 hours and trigger notifications/calls.
    """
    # Simple simulated Celery background job
    from datetime import datetime, timedelta
    
    tomorrow = datetime.utcnow() + timedelta(hours=24)
    upcoming_appointments = db.query(Appointment).filter(
        Appointment.slot <= tomorrow,
        Appointment.slot >= datetime.utcnow(),
        Appointment.status == "BOOKED"
    ).all()
    
    reminders_sent = []
    
    for appt in upcoming_appointments:
        patient_name = appt.patient.name
        doctor_name = appt.doctor.name
        time_str = appt.slot.strftime("%I:%M %p")
        lang = appt.patient.preferred_language
        
        # Formulate automated greeting based on patient's preferred language
        message = f"Hi {patient_name}, this is a reminder for your upcoming appointment with {doctor_name} tomorrow at {time_str}."
        if lang == "hi":
            message = f"नमस्ते {patient_name}, यह कल {time_str} पर {doctor_name} के साथ आपकी आगामी अपॉइंटमेंट के लिए एक रिमाइंडर है।"
        elif lang == "ta":
            message = f"வணக்கம் {patient_name}, நாளை {time_str} மணிக்கு {doctor_name} உடனான உங்கள் சந்திப்பிற்கான நினைவூட்டல் இதுவாகும்."
            
        reminders_sent.append({
            "appointment_id": str(appt.id),
            "patient_name": patient_name,
            "phone": appt.patient.phone,
            "message": message,
            "language": lang
        })
        
        print(f"[CAMPAIGN WORKER] Triggered Outbound Call/SMS to {appt.patient.phone} in '{lang}': {message}")
        
    return {
        "status": "success",
        "campaign": "clinical-outbound-reminders-24h",
        "jobs_triggered": len(reminders_sent),
        "alerts": reminders_sent
    }

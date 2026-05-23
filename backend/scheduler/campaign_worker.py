import os
import time
import asyncio
from datetime import datetime, timedelta
from backend.memory.database import SessionLocal, Appointment

async def run_reminder_checks():
    """Runs a periodic query against Supabase database for outbound reminders."""
    print("Background Campaign Scheduler Worker started.")
    print("Monitoring database for appointments occurring in the next 24 hours...")
    
    while True:
        db = SessionLocal()
        try:
            tomorrow = datetime.utcnow() + timedelta(hours=24)
            upcoming = db.query(Appointment).filter(
                Appointment.slot <= tomorrow,
                Appointment.slot >= datetime.utcnow(),
                Appointment.status == "BOOKED"
            ).all()

            if upcoming:
                print(f"\n[CAMPAIGN CLOCK - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Found {len(upcoming)} upcoming appointments for reminder campaign:")
                for appt in upcoming:
                    patient_name = appt.patient.name
                    doctor_name = appt.doctor.name
                    phone = appt.patient.phone
                    time_str = appt.slot.strftime("%I:%M %p")
                    lang = appt.patient.preferred_language
                    
                    message = f"Hi {patient_name}, this is a reminder for your upcoming appointment with {doctor_name} tomorrow at {time_str}."
                    if lang == "hi":
                        message = f"नमस्ते {patient_name}, यह कल {time_str} पर {doctor_name} के साथ आपकी आगामी अपॉइंटमेंट के लिए एक रिमाइंडर है।"
                    elif lang == "ta":
                        message = f"வணக்கம் {patient_name}, நாளை {time_str} மணிக்கு {doctor_name} உடனான உங்கள் சந்திப்பிற்கான நினைவூட்டல் இதுவாகும்."
                        
                    print(f"  --> Campaign Outbound sms/call to {phone} [{lang}]: {message}")
            else:
                # Silent tick
                pass
                
        except Exception as e:
            print(f"Error in background campaign check: {e}")
        finally:
            db.close()
            
        # Poll every 60 seconds for demo environment simplicity
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(run_reminder_checks())
    except KeyboardInterrupt:
        print("Background Campaign Worker terminated.")

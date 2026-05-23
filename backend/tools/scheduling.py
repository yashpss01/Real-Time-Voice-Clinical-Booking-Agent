import uuid
from datetime import datetime, time, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from backend.memory.database import Patient, Doctor, Appointment

# Standard clinical work hours: 09:00 AM to 05:00 PM (17:00)
CLINIC_START_HOUR = 9
CLINIC_END_HOUR = 17
SLOT_DURATION_MINUTES = 30

def find_or_create_patient(db: Session, phone: str, name: Optional[str] = None, preferred_language: str = "en") -> Patient:
    """Retrieves patient by phone number or creates a new profile if not found."""
    patient = db.query(Patient).filter(Patient.phone == phone).first()
    if not patient:
        # Generate generic name if not specified
        final_name = name if name else f"Patient {phone[-4:]}"
        patient = Patient(
            name=final_name,
            phone=phone,
            preferred_language=preferred_language
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
    else:
        # Keep preferred language updated
        if preferred_language and patient.preferred_language != preferred_language:
            patient.preferred_language = preferred_language
            db.commit()
            db.refresh(patient)
    return patient

def find_doctors(db: Session, specialization: Optional[str] = None, language: Optional[str] = None) -> List[Doctor]:
    """Queries doctors matching preferred specialization and language traits."""
    query = db.query(Doctor)
    
    if specialization:
        # Case insensitive match for specialization
        query = query.filter(Doctor.specialization.ilike(f"%{specialization}%"))
        
    doctors = query.all()
    
    # Filter by language if specified (e.g. language="hi" matches doctor language containing "hi")
    if language:
        lang_lower = language.lower()
        doctors = [
            doc for doc in doctors 
            if any(l.strip().lower() == lang_lower for l in doc.preferred_language.split(","))
        ]
        
    return doctors

def get_doctor_available_slots(db: Session, doctor_id: uuid.UUID, target_date: datetime.date) -> List[datetime]:
    """Returns a list of unbooked 30-minute datetime slots for a doctor on a specific date."""
    # Ensure target_date is in the future or today
    today = datetime.utcnow().date()
    if target_date < today:
        return []

    # Generate all potential slots for the day
    start_time = datetime.combine(target_date, time(CLINIC_START_HOUR, 0))
    end_time = datetime.combine(target_date, time(CLINIC_END_HOUR, 0))
    
    potential_slots: List[datetime] = []
    current_slot = start_time
    while current_slot < end_time:
        # Only suggest future slots if the target date is today
        if current_slot > datetime.utcnow() + timedelta(minutes=5):
            potential_slots.append(current_slot)
        current_slot += timedelta(minutes=SLOT_DURATION_MINUTES)

    # Fetch active booked appointments on this day
    booked_appointments = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor_id,
            Appointment.status == "BOOKED",
            Appointment.slot >= datetime.combine(target_date, time(0, 0)),
            Appointment.slot < datetime.combine(target_date, time(23, 59))
        )
    ).all()

    booked_slots = {appt.slot for appt in booked_appointments}
    
    # Remove booked slots from potentials
    available_slots = [slot for slot in potential_slots if slot not in booked_slots]
    return available_slots

def book_appointment(db: Session, patient_id: uuid.UUID, doctor_id: uuid.UUID, slot: datetime) -> Appointment:
    """Atomic booking that validates time constraints, past dates, and double bookings."""
    # 1. Past slot check
    if slot < datetime.utcnow():
        raise ValueError("Cannot book an appointment in the past.")

    # 2. Work hours boundary check
    if not (CLINIC_START_HOUR <= slot.hour < CLINIC_END_HOUR):
        raise ValueError(f"Appointments must be scheduled between {CLINIC_START_HOUR:02d}:00 and {CLINIC_END_HOUR:02d}:00.")

    # 3. Double booking check
    existing_booking = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == doctor_id,
            Appointment.slot == slot,
            Appointment.status == "BOOKED"
        )
    ).first()
    
    if existing_booking:
        raise ValueError("This doctor is already booked for the selected slot.")

    # Create new appointment
    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot=slot,
        status="BOOKED"
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment

def reschedule_appointment(db: Session, appointment_id: uuid.UUID, new_slot: datetime) -> Appointment:
    """Atomically marks previous booking cancelled and schedules the new slot."""
    # Get old appointment
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise ValueError("Appointment not found.")
        
    if appt.status == "CANCELLED":
        raise ValueError("Cannot reschedule an already cancelled appointment.")

    # Double booking check for the new slot
    existing_booking = db.query(Appointment).filter(
        and_(
            Appointment.doctor_id == appt.doctor_id,
            Appointment.slot == new_slot,
            Appointment.status == "BOOKED",
            Appointment.id != appointment_id
        )
    ).first()
    
    if existing_booking:
        raise ValueError("The doctor is already booked for the requested new slot.")

    # Update slot
    appt.slot = new_slot
    db.commit()
    db.refresh(appt)
    return appt

def cancel_appointment(db: Session, appointment_id: uuid.UUID) -> Appointment:
    """Cancels an existing clinical appointment slot."""
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise ValueError("Appointment not found.")
        
    appt.status = "CANCELLED"
    db.commit()
    db.refresh(appt)
    return appt

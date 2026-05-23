import os
import uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, ForeignKey, Index, UUID
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = None

if DATABASE_URL:
    try:
        # Rewrite to use the pg8000 pure-Python driver for compatibility
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+pg8000://", 1)
        elif DATABASE_URL.startswith("postgresql://") and "+pg8000" not in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)

        # Quick DNS resolve check to avoid long timeouts
        from urllib.parse import urlparse
        import socket
        parsed = urlparse(DATABASE_URL)
        if parsed.hostname:
            socket.gethostbyname(parsed.hostname)

        engine = create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args={"timeout": 5}  # Fast fail
        )
        # Test connection
        with engine.connect() as conn:
            pass
        print("Successfully connected to PostgreSQL database.")
    except Exception as e:
        print(f"Warning: PostgreSQL connection failed ({e}). Falling back to SQLite.")
        engine = None

if not engine:
    sqlite_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clinical_agent.db")
    print(f"Using local SQLite database at {sqlite_path}")
    DATABASE_URL = f"sqlite:///{sqlite_path}"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    preferred_language = Column(String(10), default="en", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    specialization = Column(String(100), nullable=False)
    preferred_language = Column(String(50), default="en", nullable=False)  # "en", "hi", "ta", or combo "en,hi"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    appointments = relationship("Appointment", back_populates="doctor")

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False)
    slot = Column(DateTime, nullable=False, index=True)  # Start time of appointment
    status = Column(String(20), default="BOOKED", nullable=False)  # "BOOKED", "CANCELLED"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")

# Create composite indexes
Index("idx_doctor_slot", Appointment.doctor_id, Appointment.slot)

def init_db():
    """Initializes tables and seeds initial doctors data if empty."""
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Seed doctors if table is empty
        if db.query(Doctor).count() == 0:
            initial_doctors = [
                Doctor(
                    name="Dr. Rajesh Kumar",
                    specialization="General Medicine",
                    preferred_language="en,hi"
                ),
                Doctor(
                    name="Dr. Priya Ramachandran",
                    specialization="Pediatrics",
                    preferred_language="en,ta"
                ),
                Doctor(
                    name="Dr. Anand Iyer",
                    specialization="Orthopedics",
                    preferred_language="en,hi,ta"
                ),
                Doctor(
                    name="Dr. Sarah Jenkins",
                    specialization="General Medicine",
                    preferred_language="en"
                ),
            ]
            db.add_all(initial_doctors)
            db.commit()
            print("Successfully initialized and seeded database with doctors.")
        else:
            print("Database already initialized and doctors exist.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()

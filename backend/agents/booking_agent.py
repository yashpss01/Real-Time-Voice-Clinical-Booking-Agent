import os
import uuid
from datetime import datetime
from typing import Dict, Any, List, TypedDict, Optional
from sqlalchemy import and_
from sqlalchemy.orm import Session
from backend.memory.database import SessionLocal, Doctor, Patient, Appointment
from backend.memory.redis_client import RedisSessionStore
from backend.services.gemini import GeminiService
from backend.tools import scheduling

# Instantiate Gemini helper
gemini = GeminiService()

class AgentState(TypedDict):
    """Schema representing the state elements managed across the graph."""
    session_id: str
    user_input: str
    detected_language: str
    entities: Dict[str, Any]
    session_data: Dict[str, Any]
    patient_info: Optional[Dict[str, Any]]
    doctors_list: List[Dict[str, Any]]
    available_slots: List[str]
    agent_reasoning: str
    final_response: str
    step_logs: List[str]

class ClinicalBookingAgent:
    """A stateful LangGraph-inspired orchestrator that processes patient voice turns, 

    executes booking operations, and manages conversational memory.
    """
    def __init__(self):
        pass

    def run_cycle(self, session_id: str, user_input: str, phone_number: str) -> Dict[str, Any]:
        """Runs the complete multi-stage graph pipeline for a single conversational turn."""
        # Initialize graph state
        state: AgentState = {
            "session_id": session_id,
            "user_input": user_input,
            "detected_language": "en",
            "entities": {},
            "session_data": {},
            "patient_info": None,
            "doctors_list": [],
            "available_slots": [],
            "agent_reasoning": "",
            "final_response": "",
            "step_logs": []
        }

        # Open database session
        db: Session = SessionLocal()
        try:
            # 1. State Node: Load Session & Patient profile
            state = self._node_load_context(state, phone_number, db)
            
            # 2. State Node: Language Detection
            state = self._node_detect_language(state)
            
            # 3. State Node: Entity & Intent Parsing
            state = self._node_parse_entities(state)
            
            # 4. State Node: Scheduling Operations & Tool Execution
            state = self._node_execute_tools(state, db)
            
            # 5. State Node: Clinical Reasoning & Dialogue Formulation
            state = self._node_generate_dialogue(state)
            
            # 6. State Node: Dynamic Response Translation
            state = self._node_translate_response(state)
            
            # Finalize and cache state context
            RedisSessionStore.append_transcript(session_id, "user", user_input)
            RedisSessionStore.append_transcript(session_id, "assistant", state["final_response"])
            
            return {
                "response_text": state["final_response"],
                "language": state["detected_language"],
                "reasoning": state["agent_reasoning"],
                "step_logs": state["step_logs"]
            }
            
        except Exception as e:
            db.rollback()
            print(f"Error in booking agent state cycle: {e}")
            fallback_msg = "I am sorry, I ran into an error booking your appointment. Please try again."
            if state["detected_language"] != "en":
                fallback_msg = gemini.translate_response(fallback_msg, state["detected_language"])
            return {
                "response_text": fallback_msg,
                "language": state["detected_language"],
                "reasoning": "System error occurred.",
                "step_logs": ["ERROR: Cycle failure"]
            }
        finally:
            db.close()

    def _node_load_context(self, state: AgentState, phone: str, db: Session) -> AgentState:
        """Retrieves patient data and active multi-turn context from databases."""
        state["step_logs"].append("Node: Load Session Context")
        
        # Load Redis session
        session = RedisSessionStore.get_session(state["session_id"])
        state["session_data"] = session

        # Load or create persistent patient profile
        patient = scheduling.find_or_create_patient(
            db, 
            phone=phone, 
            preferred_language=session.get("preferred_language", "en")
        )
        
        state["patient_info"] = {
            "id": str(patient.id),
            "name": patient.name,
            "phone": patient.phone,
            "preferred_language": patient.preferred_language
        }
        
        # Sync state references
        updates = {
            "patient_id": str(patient.id),
            "patient_phone": patient.phone,
            "patient_name": patient.name
        }
        if not session["preferred_language"]:
            updates["preferred_language"] = patient.preferred_language
        
        state["session_data"] = RedisSessionStore.update_session(state["session_id"], updates)
        return state

    def _node_detect_language(self, state: AgentState) -> AgentState:
        """Detects language and updates persistent user preference."""
        state["step_logs"].append("Node: Detect Language")
        
        # Check current input language
        lang = gemini.detect_language(state["user_input"])
        state["detected_language"] = lang
        
        # Persist preferred language if new
        session_lang = state["session_data"].get("preferred_language")
        if not session_lang or session_lang != lang:
            state["session_data"] = RedisSessionStore.update_session(
                state["session_id"], 
                {"preferred_language": lang}
            )
            
        return state

    def _node_parse_entities(self, state: AgentState) -> AgentState:
        """Extracts intention parameters, names, dates, and slots from voice transcription."""
        state["step_logs"].append("Node: Entity Parsing")
        
        # Format a basic chat history summary to give context to Gemini parser
        history = state["session_data"].get("transcript_history", [])
        history_summary = "\n".join([f"{h['role']}: {h['text']}" for h in history[-4:]])
        
        # Parse entities
        parsed = gemini.parse_entities(state["user_input"], history_summary)
        state["entities"] = parsed
        
        # Sync intent to session state if detected
        if parsed.get("intent"):
            state["session_data"] = RedisSessionStore.update_session(
                state["session_id"], 
                {"active_intent": parsed["intent"]}
            )
            
        return state

    def _node_execute_tools(self, state: AgentState, db: Session) -> AgentState:
        """Invokes appropriate clinical tools (booking queries, validations, double-bookings)."""
        state["step_logs"].append("Node: Execute Clinical Tools")
        
        entities = state["entities"]
        intent = state["session_data"].get("active_intent")
        session = state["session_data"]

        # 1. Action intent: Confirmation of a pending proposed appointment slot
        if intent == "CONFIRMATION" or entities.get("confirm") is not None:
            pending = session.get("pending_confirm_appointment")
            confirm_val = entities.get("confirm")
            
            # If user said "Yes" and there is a pending slot buffered
            if confirm_val is True and pending:
                try:
                    slot_dt = datetime.fromisoformat(pending["slot"])
                    doctor_uuid = uuid.UUID(pending["doctor_id"])
                    patient_uuid = uuid.UUID(session["patient_id"])
                    
                    appt = scheduling.book_appointment(db, patient_uuid, doctor_uuid, slot_dt)
                    state["step_logs"].append(f"SUCCESS: Appt Booked (ID: {appt.id})")
                    
                    # Clear pending buffer
                    state["session_data"] = RedisSessionStore.update_session(
                        state["session_id"], 
                        {"pending_confirm_appointment": None, "active_intent": None}
                    )
                    state["agent_reasoning"] = f"Successfully confirmed and booked slot {pending['slot']} with doctor {pending['doctor_name']}."
                except Exception as e:
                    state["step_logs"].append(f"CONFLICT: {e}")
                    state["agent_reasoning"] = f"Attempted to confirm booking, but slot is no longer available: {e}"
            
            elif confirm_val is False and pending:
                # User declined proposed slot
                state["step_logs"].append("USER_DECLINED_SLOT")
                state["session_data"] = RedisSessionStore.update_session(
                    state["session_id"], 
                    {"pending_confirm_appointment": None}
                )
                state["agent_reasoning"] = "User declined the proposed appointment slot. Offering alternatives next."
            
            return state

        # 2. Action intent: Booking a new appointment
        if intent == "BOOKING":
            spec = entities.get("specialization")
            doc_name = entities.get("doctor_name")
            date_str = entities.get("date")
            time_str = entities.get("time")

            # Look up matching doctors
            doctors = scheduling.find_doctors(db, specialization=spec)
            if doc_name:
                doctors = [d for d in doctors if doc_name.lower() in d.name.lower()]
            
            state["doctors_list"] = [{"id": str(d.id), "name": d.name, "specialization": d.specialization} for d in doctors]

            # If matching doctor(s) are found, check slots
            if doctors and date_str:
                selected_doc = doctors[0]  # Take first match
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    available = scheduling.get_doctor_available_slots(db, selected_doc.id, target_date)
                    state["available_slots"] = [s.isoformat() for s in available]
                    
                    # If specific time requested, validate slot availability
                    if time_str and available:
                        # Attempt to parse target time (e.g. "10:30" or "morning")
                        target_dt = None
                        if ":" in time_str:
                            hr, mn = map(int, time_str.split(":"))
                            target_dt = datetime.combine(target_date, datetime.min.time().replace(hour=hr, minute=mn))
                        
                        matched_slot = None
                        if target_dt:
                            matched_slot = next((s for s in available if s.hour == target_dt.hour and s.minute == target_dt.minute), None)
                        
                        if matched_slot:
                            # Propose slot and buffer to session for pending confirmation
                            state["step_logs"].append(f"PROPOSED_SLOT: {matched_slot}")
                            pending_buffer = {
                                "doctor_id": str(selected_doc.id),
                                "doctor_name": selected_doc.name,
                                "slot": matched_slot.isoformat(),
                                "specialization": selected_doc.specialization
                            }
                            state["session_data"] = RedisSessionStore.update_session(
                                state["session_id"],
                                {"pending_confirm_appointment": pending_buffer}
                            )
                            state["agent_reasoning"] = f"Found requested slot {matched_slot.isoformat()} for Dr. {selected_doc.name}. Waiting for user confirmation."
                        else:
                            # Conflicting or unavailable slot. Propose top 3 alternative available slots
                            alt_slots = available[:3]
                            state["step_logs"].append("CONFLICT_TRIGGERED")
                            state["agent_reasoning"] = f"Requested slot at {time_str} is occupied. Proposing alternatives: {[s.isoformat() for s in alt_slots]}."
                    else:
                        state["agent_reasoning"] = f"Found {len(available)} available slots for Dr. {selected_doc.name} on {date_str}. Proposing top slots."
                except Exception as e:
                    state["step_logs"].append(f"ERROR: {e}")
                    state["agent_reasoning"] = f"Failed to check doctor slots: {e}"
            else:
                state["agent_reasoning"] = "Searching for doctor details. Missing doctor name or target date."
            
            return state

        # 3. Action intent: Rescheduling an existing appointment
        if intent == "RESCHEDULING":
            # Fetch patient's active appointments
            patient_uuid = uuid.UUID(session["patient_id"])
            appt = db.query(Appointment).filter(
                and_(
                    Appointment.patient_id == patient_uuid,
                    Appointment.status == "BOOKED"
                )
            ).order_by(Appointment.slot.asc()).first() # Reschedule their next upcoming appointment

            if appt and entities.get("date"):
                try:
                    new_date_str = entities.get("date")
                    new_time_str = entities.get("time") or "10:00"  # default
                    
                    new_date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
                    hr, mn = map(int, new_time_str.split(":")) if ":" in new_time_str else (10, 0)
                    new_slot_dt = datetime.combine(new_date, datetime.min.time().replace(hour=hr, minute=mn))
                    
                    updated = scheduling.reschedule_appointment(db, appt.id, new_slot_dt)
                    state["step_logs"].append(f"SUCCESS: Rescheduled (Appt ID: {updated.id})")
                    state["agent_reasoning"] = f"Successfully rescheduled appointment to {new_slot_dt.isoformat()} with Dr. {updated.doctor.name}."
                    
                    state["session_data"] = RedisSessionStore.update_session(
                        state["session_id"],
                        {"active_intent": None}
                    )
                except Exception as e:
                    state["step_logs"].append(f"RESCHEDULE_CONFLICT: {e}")
                    state["agent_reasoning"] = f"Reschedule conflict: {e}."
            else:
                state["agent_reasoning"] = "No active booked appointments found to reschedule, or target date was not provided."
            
            return state

        # 4. Action intent: Cancellation
        if intent == "CANCELLATION":
            patient_uuid = uuid.UUID(session["patient_id"])
            appt = db.query(Appointment).filter(
                and_(
                    Appointment.patient_id == patient_uuid,
                    Appointment.status == "BOOKED"
                )
            ).order_by(Appointment.slot.asc()).first()

            if appt:
                cancelled = scheduling.cancel_appointment(db, appt.id)
                state["step_logs"].append(f"SUCCESS: Cancelled (Appt ID: {cancelled.id})")
                state["agent_reasoning"] = f"Successfully cancelled appointment scheduled on {cancelled.slot.isoformat()} with Dr. {cancelled.doctor.name}."
                
                state["session_data"] = RedisSessionStore.update_session(
                    state["session_id"],
                    {"active_intent": None}
                )
            else:
                state["agent_reasoning"] = "Could not find any active booking under this phone number to cancel."
            
            return state

        return state

    def _node_generate_dialogue(self, state: AgentState) -> AgentState:
        """Invokes reasoning and formats polite clinical response dialogue in English."""
        state["step_logs"].append("Node: Dialogue Generation")
        
        # Combine clinical and calendar attributes as context for Gemini
        state_context = {
            "active_intent": state["session_data"].get("active_intent"),
            "pending_confirm_appointment": state["session_data"].get("pending_confirm_appointment"),
            "doctors_found": state["doctors_list"],
            "available_slots": state["available_slots"][:5] if state["available_slots"] else [],
            "action_reasoning": state["agent_reasoning"]
        }

        response = gemini.generate_clinical_response(
            user_input=state["user_input"],
            history=state["session_data"].get("transcript_history", []),
            patient_name=state["session_data"].get("patient_name", "Patient"),
            state_info=state_context
        )
        
        state["agent_reasoning"] += f" | Aura clinical response: {response}"
        state["final_response"] = response
        return state

    def _node_translate_response(self, state: AgentState) -> AgentState:
        """Translates final dialog to target language (Hindi or Tamil) if needed."""
        state["step_logs"].append("Node: Response Translation")
        
        target_lang = state["detected_language"]
        if target_lang != "en":
            state["step_logs"].append(f"TRANSLATING_TO_{target_lang.upper()}")
            translated = gemini.translate_response(state["final_response"], target_lang)
            state["final_response"] = translated
            
        return state

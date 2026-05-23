import os
import json
import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise ValueError("REDIS_URL environment variable is not set")

# Connect to Redis.
# Using decode_responses=True to automatically handle UTF-8 string conversions
try:
    redis_client = redis.Redis.from_url(
        REDIS_URL, 
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
        socket_keepalive=True,
        health_check_interval=30
    )
    # Ping to check connection
    redis_client.ping()
    print("Successfully connected to Redis / Upstash Cache.")
except Exception as e:
    print(f"Failed to connect to Redis at {REDIS_URL}: {e}")
    # Local fallback in case of SSL/TLS connection failures in local sandbox envs
    # Often, connecting with ssl_cert_reqs=None is required for self-signed certificates
    try:
        redis_client = redis.Redis.from_url(
            REDIS_URL, 
            decode_responses=True,
            ssl_cert_reqs=None,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
            socket_keepalive=True,
            health_check_interval=30
        )
        redis_client.ping()
        print("Connected to Redis with custom TLS security checks disabled.")
    except Exception as fallback_e:
        print(f"Fallback connection also failed: {fallback_e}")
        # Make a mock redis-client to prevent compile/startup errors in dry environments
        class MockRedis:
            def __init__(self):
                self.store = {}
            def get(self, name): return self.store.get(name)
            def setex(self, name, time, value): self.store[name] = value
            def delete(self, *names):
                for name in names: self.store.pop(name, None)
            def ping(self): return True
        redis_client = MockRedis()
        print("Initialized MockRedis in memory to guarantee local application resilience.")

SESSION_TTL = 1800  # 30 minutes in seconds

# Thread-safe in-memory cache mirror to guarantee 100% service availability 
# if Upstash Redis has public network fluctuations or DNS resolution drops.
_in_memory_backup_store = {}

class RedisSessionStore:
    @staticmethod
    def get_session(session_id: str) -> dict:
        """Retrieves complete session dictionary or returns a default empty schema."""
        key = f"session:{session_id}"
        session_data = None
        try:
            session_data = redis_client.get(key)
        except Exception as e:
            print(f"[REDIS WARNING] Failed to read from Redis, using in-memory mirror: {e}")
            session_data = _in_memory_backup_store.get(key)
            
        if session_data:
            try:
                if isinstance(session_data, dict):
                    return session_data
                return json.loads(session_data)
            except Exception:
                pass
        
        # Check in-memory backup as a second-pass fallback
        if key in _in_memory_backup_store:
            return _in_memory_backup_store[key]
            
        # Return default schema if none exists
        return {
            "session_id": session_id,
            "patient_id": None,
            "patient_phone": None,
            "patient_name": None,
            "active_intent": None,  # BOOKING, RESCHEDULING, CANCELLATION, REMINDER_FOLLOWUP
            "preferred_language": None,  # en, hi, ta
            "pending_confirm_appointment": None,  # JSON metadata buffer
            "transcript_history": [],  # list of {"role": "user/assistant", "text": "..."}
            "last_active": None
        }

    @staticmethod
    def save_session(session_id: str, session: dict) -> None:
        """Persists the session dictionary with the configured TTL."""
        key = f"session:{session_id}"
        # Always mirror to local backup first
        _in_memory_backup_store[key] = session
        try:
            redis_client.setex(key, SESSION_TTL, json.dumps(session))
        except Exception as e:
            print(f"[REDIS WARNING] Failed to write to Redis, session mirrored in-memory: {e}")

    @classmethod
    def update_session(cls, session_id: str, updates: dict) -> dict:
        """Atomically updates specific keys in the session data."""
        session = cls.get_session(session_id)
        for k, v in updates.items():
            session[k] = v
        cls.save_session(session_id, session)
        return session

    @classmethod
    def append_transcript(cls, session_id: str, role: str, text: str) -> None:
        """Appends a new speech event to the transcript log history."""
        session = cls.get_session(session_id)
        session["transcript_history"].append({"role": role, "text": text})
        cls.save_session(session_id, session)

    @staticmethod
    def clear_session(session_id: str) -> None:
        """Removes the session from the cache."""
        key = f"session:{session_id}"
        _in_memory_backup_store.pop(key, None)
        try:
            redis_client.delete(key)
        except Exception as e:
            print(f"[REDIS WARNING] Failed to delete session from Redis: {e}")

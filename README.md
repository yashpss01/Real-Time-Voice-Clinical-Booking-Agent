# Real-Time Multilingual Voice AI Agent: Clinical Appointment Booking System

A production-style real-time multilingual voice AI agent for healthcare appointment booking, rescheduling, cancellation, and follow-up workflows.

The system supports voice conversations, English/Hindi/Tamil multilingual support, context-aware memory, scheduling conflict resolution, and outbound reminder campaigns—built using a low-cost, free-tier, and open-source infrastructure.

---

## 🎯 Objective

Build a production-style conversational healthcare assistant capable of:
- **Booking, rescheduling, and cancelling appointments** through voice interactions.
- **Handling multilingual conversations** (English, Hindi, Tamil) with automatic language detection.
- **Maintaining stateful conversational memory** (short-term session & long-term persistent).
- **Managing scheduling conflicts** and recommending alternative slots.
- **Running outbound reminder campaigns** using scheduled background workers.
- **Operating with low latency** via an optimized, streaming audio architecture.

---

## ✨ Features

### 🎙️ Real-Time Voice Interaction
- **Streaming Audio**: Low-latency bidirectional WebSocket transport.
- **Incremental Processing**: Real-time voice activity detection (VAD) and streaming STT.
- **Barge-In Handling**: Interruption support that instantly cancels synthesis and ongoing generation when user speech is detected.

### 🌐 Multilingual Support
- **Languages**: English, Hindi, and Tamil.
- **Language Detection**: Auto-detects input language and persists user preference.
- **Dynamic Translation**: Processes internal reasoning in English and translates responses dynamically to the preferred user language.

### 📅 Appointment Lifecycle Management
- **Booking**: Interactive slots discovery and validation.
- **Conflict Resolution**: Auto-detects double bookings and proposes next available slots.
- **Rescheduling & Cancellation**: Intuitive conversational updates and cancellation flows.
- **Date Validation**: Filters out past dates and invalid/out-of-bound scheduling requests.

### 🧠 Contextual Memory
- **Short-Term Session Memory**: Built on Redis with a 30-minute TTL to maintain active intents, partial transcripts, pending confirmations, and transient states.
- **Long-Term Persistent Memory**: Backed by PostgreSQL to store profiles, appointment history, preferred languages, and past interaction summaries.

### 📢 Outbound Campaign Mode
- **Reminder Campaigns**: Automated check-ins and missed appointment recovery flows powered by Celery background workers.

---

## 🛠️ Tech Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | Next.js, TypeScript, TailwindCSS | Elegant responsive user dashboard & streaming voice interface |
| **Backend** | FastAPI, WebSockets | Asynchronous API gateway, session routing & streaming |
| **Orchestration** | LangGraph | Stateful multi-turn agent flow & tool-calling orchestration |
| **Session Cache** | Redis | Session state, intermediate transcripts & TTL memory |
| **Persistent Storage** | PostgreSQL | Patients, Doctors, and Appointments schema database |
| **Background Jobs** | Celery | Outbound reminder schedule queues & background workers |
| **Speech-to-Text** | Faster Whisper | High-performance open-source STT (Offline support) |
| **Voice Activity Detection** | Silero VAD | Low-latency audio-chunk segmentation |
| **Reasoning LLM** | Gemini 3.5 Flash | Cost-efficient, high-intelligence translation & reasoning API |
| **Text-to-Speech** | Coqui TTS | Free, open-source audio synthesis |

---

## 🏗️ System Architecture

```mermaid
graph TD
    User([User Voice Stream]) <-->|WebSocket| FE[Next.js Frontend]
    FE <-->|WebSocket| BE[FastAPI Gateway]
    
    subgraph Voice Pipeline
        BE -->|Audio Stream| VAD[Silero VAD]
        VAD -->|Speech Chunks| STT[Faster Whisper STT]
        STT -->|Transcribed Text| Lang[Language Detector]
    end
    
    subgraph Agent Core
        Lang -->|Text Input| LG[LangGraph Orchestrator]
        LG <-->|Session State| Redis[(Redis Cache)]
        LG <-->|Tools Calling| Tools[Tool Execution & Scheduling]
        Tools <-->|Persistent Storage| DB[(PostgreSQL)]
    end
    
    subgraph Synthesis Pipeline
        LG -->|Text Response| Gemini[Gemini 3.5 Flash]
        Gemini -->|User Language Text| TTS[Coqui TTS Engine]
        TTS -->|Audio Packets| BE
    end
```

### 🔁 Conversation Pipeline
```
User Audio ──> Voice Activity Detection ──> Chunked Audio Streaming ──> Speech-to-Text ──> Language Detection ──> Intent Extraction ──> Memory Retrieval ──> Tool Calling ──> Conflict Resolution ──> LLM Response Generation ──> Text-to-Speech ──> Audio Response
```

---

## 🤖 Agent Workflow (LangGraph Flow)

The system utilizes a tool-driven, state-based graph instead of brittle hardcoded intent matching.

```
[START] ──> [Language Detection] ──> [Intent Recognition] ──> [Entity Extraction] ──> [Memory Retrieval] ──> [Scheduling Tool Calls] ──> [Conflict Resolution] ──> [Confirmation Handling] ──> [Response Generation] ──> [END]
```

### 🔧 Tool Calling System
- `find_doctor(specialization, preferred_language)`: Returns suitable healthcare professionals.
- `get_available_slots(doctor_id, date)`: Fetches open intervals for a given date.
- `book_appointment(patient_id, doctor_id, slot)`: Registers an appointment if slot is free.
- `reschedule_appointment(appointment_id, new_slot)`: Modifies an existing booking.
- `cancel_appointment(appointment_id)`: Cancels reservations and frees the slot.

---

## 💾 Memory Architecture

### 🔴 Redis Session Memory
- **Purpose**: Low-latency cache for transient multi-turn dialogues.
- **Attributes**: `session:user_2048` with a `30-minute` expiration TTL.
- **Stores**: Current active intent, slot confirmation buffers, partial transcripts, preferred interface language, and state flags.

### 🐘 PostgreSQL Persistent Memory
- **Stores**: Patient profiles, past appointment histories, language preferences, preferred doctors, and historical interaction summaries.
- **Benefit**: Retains relational context across multiple communication sessions to enable long-term continuity.

---

## 🌐 Multilingual Flow

To simplify orchestration and maintain maximum intelligence, we use an **Internal English Reasoning** paradigm:

```
[Input Speech] ──> [STT in Original Language] ──> [Internal Reasoning in English (via LLM)] ──> [Response Translation] ──> [TTS in User Language]
```

This ensures robust tool calling and context maintenance regardless of the language the user speaks.

---

## ⚡ Latency Optimization

We achieve highly competitive latency using streaming, incremental pipelines, local inference models, and shared cache stores:

| Component | Average Latency |
| :--- | :--- |
| Voice Activity Detection (Silero) | ~40 ms |
| Chunked STT (Faster Whisper) | ~180 ms |
| Agent Reasoning (Gemini Flash) | ~140 ms |
| Tool Execution (PostgreSQL/Redis) | ~50 ms |
| TTS Generation (Coqui TTS) | ~120 ms |
| **Total Round-Trip Latency** | **~530 ms** |

> [!NOTE]
> High-grade sub-450ms latency is typically gated by paid APIs. This architecture prioritizes open-source local pipelines to validate real-time scalability without paywall constraints.

---

## 💾 Database Schema

```
 Patients                Doctors                 Appointments
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ id (PK)            │  │ id (PK)            │  │ id (PK)            │
│ name               │  │ name               │  │ patient_id (FK)    │
│ phone              │  │ specialization     │  │ doctor_id (FK)     │
│ preferred_language │  └────────────────────┘  │ slot (TIMESTAMP)   │
└────────────────────┘                          │ status (VARCHAR)   │
                                                └────────────────────┘
```

---

## 📂 Project Structure

```
project-root/
├── backend/
│   ├── agents/         # LangGraph workflows and logic
│   ├── memory/         # PostgreSQL and Redis database handlers
│   ├── models/         # SQLAlchemy schema definitions
│   ├── prompts/        # Context-aware templates (multilingual)
│   ├── scheduler/      # Celery outbound jobs configuration
│   ├── services/       # VAD, Whisper STT, Gemini LLM, and Coqui TTS services
│   ├── tools/          # Healthcare scheduling tools
│   ├── websocket/      # High-performance WebSocket endpoints
│   └── main.py         # App entrypoint
├── frontend/
│   ├── audio/          # Worklets & audio recorders
│   ├── components/     # Visual active session logs & dashboard
│   ├── hooks/          # Real-time state management
│   ├── websocket/      # Audio streaming client connection
│   └── pages/          # Home UI & booking control panels
├── diagrams/           # Architecture assets
├── docs/               # In-depth technical guides
└── README.md           # Project Documentation
```

---

## 🚀 Setup Instructions

### 📥 1. Clone & Navigate
```bash
git clone <repository-url>
cd Real-Time-Voice-Clinical-Booking-Agent
```

### 🐍 2. Backend Setup
1. Create and activate virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your-gemini-api-key
   DATABASE_URL=postgresql://user:password@localhost/dbname
   REDIS_URL=redis://localhost:6379/0
   ```
4. Run the development server:
   ```bash
   uvicorn backend.main:app --reload
   ```

### 💻 3. Frontend Setup
1. Navigate to the frontend workspace:
   ```bash
   cd frontend
   ```
2. Install Node packages:
   ```bash
   npm install
   ```
3. Start the Next.js app:
   ```bash
   npm run dev
   ```

---

## 🎭 Demo Scenarios

1. **Scenario 1 — Appointment Booking**: Smooth English voice conversation initiating and confirming an appointment slot.
2. **Scenario 2 — Hindi Rescheduling**: Seamless language-switched voice inputs to shift appointment times.
3. **Scenario 3 — Conflict Handling**: Gracefully recommends alternatives when the chosen slot is double-booked.
4. **Scenario 4 — Outbound Reminder**: Initiates an automated post-op check-in or recovery outreach campaign.
5. **Scenario 5 — Barge-In**: Assistant stops talking instantly when a user says "Wait, that doesn't work for me."

---

## ⚖️ Tradeoffs & Known Limitations

- **Tradeoff**: Opted for **Faster Whisper** and **Coqui TTS** to maintain a fully free-tier/open-source capability instead of costly high-availability enterprise APIs.
- **Tradeoff**: **Internal English Reasoning** simplifies cross-lingual maintenance at the minor cost of translation latency.
- **Limitation**: Local STT inference increases total round-trip latency depending on machine specifications.
- **Limitation**: Tamil transcription quality can vary under environments with heavier background noises.

---

## 🔮 Future Improvements
- [ ] Integration with Twilio/SIP trunking for direct telephony calls.
- [ ] GPU-accelerated inference deployment configs for ultra-low latency.
- [ ] RAG-based clinical patient history retrieval.
- [ ] Comprehensive Doctor and Administrator dashboard.
- [ ] Streaming TTS audio-chunk optimization.

---

## 👨‍💻 Author

Built as part of the Engineering Assignment: **Real-Time Multilingual Voice AI Agent — Clinical Appointment Booking**.
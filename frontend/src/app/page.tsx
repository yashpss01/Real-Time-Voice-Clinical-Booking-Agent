"use client";

import React, { useState, useEffect, useRef } from "react";

// Types for scheduling displays
interface Doctor {
  id: string;
  name: string;
  specialization: string;
  languages: string[];
}

interface Appointment {
  id: string;
  doctor_name: string;
  specialization: string;
  patient_name: string;
  patient_phone: string;
  slot: string;
  status: string;
}

interface CampaignAlert {
  appointment_id: string;
  patient_name: string;
  phone: string;
  message: string;
  language: string;
}

interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
}

export default function ClinicalDashboard() {
  // Session details
  const [sessionId, setSessionId] = useState<string>("");
  const [phone, setPhone] = useState<string>("9999999999");
  
  // Connection states
  const [status, setStatus] = useState<"disconnected" | "connecting" | "idle" | "processing" | "speaking">("disconnected");
  
  // Audio state references
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [userTranscript, setUserTranscript] = useState<string>("");
  const [assistantTranscript, setAssistantTranscript] = useState<string>("");
  const [reasoningText, setReasoningText] = useState<string>("");
  const [stepLogs, setStepLogs] = useState<string[]>([]);
  const [conversationHistory, setConversationHistory] = useState<TranscriptEntry[]>([]);

  // Telemetry items
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [campaignAlerts, setCampaignAlerts] = useState<CampaignAlert[]>([]);
  const [isCampaignRunning, setIsCampaignRunning] = useState<boolean>(false);

  // Web Audio & WebSocket API refs
  const socketRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  
  // Playback audio elements
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioChunksBufferRef = useRef<Blob[]>([]);

  // Generate random Session ID on mount
  useEffect(() => {
    setSessionId(`session_${Math.floor(1000 + Math.random() * 9000)}`);
    fetchDoctors();
    fetchAppointments();
  }, []);

  const fetchDoctors = async () => {
    try {
      const backendUrl = window.location.port === "3000" ? "http://localhost:8000" : "";
      const res = await fetch(`${backendUrl}/api/doctors`);
      if (res.ok) setDoctors(await res.json());
    } catch (e) {
      console.error("Failed fetching doctors:", e);
    }
  };

  const fetchAppointments = async () => {
    try {
      const backendUrl = window.location.port === "3000" ? "http://localhost:8000" : "";
      const res = await fetch(`${backendUrl}/api/appointments`);
      if (res.ok) setAppointments(await res.json());
    } catch (e) {
      console.error("Failed fetching appointments:", e);
    }
  };

  const triggerCampaign = async () => {
    setIsCampaignRunning(true);
    try {
      const backendUrl = window.location.port === "3000" ? "http://localhost:8000" : "";
      const res = await fetch(`${backendUrl}/api/campaign/reminder`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCampaignAlerts(data.alerts || []);
        fetchAppointments();
      }
    } catch (e) {
      console.error("Campaign failed:", e);
    } finally {
      setIsCampaignRunning(false);
    }
  };

  // Connect Voice WebSocket
  const startSession = async () => {
    if (isRecording) return;
    
    setStatus("connecting");
    setIsRecording(true);
    audioChunksBufferRef.current = [];

    // Initialize Web Audio context at 16kHz sample rate
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
      sampleRate: 16000
    });
    audioContextRef.current = audioContext;

    // Secure SSL/TLS WebSocket route creation
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    
    // Direct routing fallback to default FastAPI port 8000 during local development
    const wsHost = host.includes("3000") ? "localhost:8000" : host;
    const wsUrl = `${protocol}//${wsHost}/ws/stream/${sessionId}?phone=${phone}`;
    
    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;
    
    socket.binaryType = "arraybuffer";

    socket.onopen = async () => {
      console.log("WebSocket connected. Capturing mic input...");
      setStatus("idle");

      try {
        // Request Microphone access
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true
          }
        });
        mediaStreamRef.current = stream;

        const source = audioContext.createMediaStreamSource(stream);
        
        // Downsample audio packets incrementally using ScriptProcessorNode
        const scriptProcessor = audioContext.createScriptProcessor(2048, 1, 1);
        scriptProcessorRef.current = scriptProcessor;

        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        scriptProcessor.onaudioprocess = (event) => {
          if (socket.readyState !== WebSocket.OPEN) return;

          const float32Samples = event.inputBuffer.getChannelData(0);
          
          // Convert [-1.0, 1.0] samples to Int16 PCM bytes
          const buffer = new ArrayBuffer(float32Samples.length * 2);
          const view = new DataView(buffer);
          let offset = 0;
          for (let i = 0; i < float32Samples.length; i++, offset += 2) {
            let s = Math.max(-1, Math.min(1, float32Samples[i]));
            view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
          }

          // Send binary raw PCM packet to backend VAD
          socket.send(buffer);
        };
      } catch (err) {
        console.error("Mic access denied:", err);
        stopSession();
      }
    };

    socket.onmessage = (event) => {
      // 1. Handle outgoing TTS audio chunks (binary packets)
      if (event.data instanceof ArrayBuffer) {
        setStatus("speaking");
        const blob = new Blob([event.data], { type: "audio/mpeg" });
        audioChunksBufferRef.current.push(blob);
        return;
      }

      // 2. Handle text telemetry events
      try {
        const payload = JSON.parse(event.data);
        
        if (payload.type === "processing") {
          // Assistant is thinking
          setStatus("processing");
          // Stop any active local audio playback immediately on user speak (Barge-In)
          stopLocalPlayback();
        } else if (payload.type === "idle") {
          setStatus("idle");
        } else if (payload.type === "interrupted") {
          setStatus("idle");
          stopLocalPlayback();
          console.log("Assistant playback interrupted successfully.");
        } else if (payload.type === "audio_complete") {
          // Completed sentence TTS chunks, trigger immediate browser playback
          playBufferedAudio();
        } else if (payload.type === "transcript") {
          setStatus("idle");
          
          if (payload.user_text) {
            setUserTranscript(payload.user_text);
            setConversationHistory(prev => [...prev, { role: "user", text: payload.user_text }]);
          }
          if (payload.agent_text) {
            setAssistantTranscript(payload.agent_text);
            setConversationHistory(prev => [...prev, { role: "assistant", text: payload.agent_text }]);
          }
          if (payload.reasoning) {
            setReasoningText(payload.reasoning);
          }
          if (payload.step_logs) {
            setStepLogs(payload.step_logs);
          }
          
          // Re-fetch schedules to sync visual metrics if something got booked/cancelled
          fetchAppointments();
        }
      } catch (err) {
        console.error("Failed to parse socket message:", err);
      }
    };

    socket.onclose = () => {
      console.log("WebSocket connection closed.");
      stopSession();
    };

    socket.onerror = (e) => {
      console.error("WebSocket error:", e);
      stopSession();
    };
  };

  // Browser audio playback controllers
  const playBufferedAudio = () => {
    if (audioChunksBufferRef.current.length === 0) return;

    stopLocalPlayback();

    // Create complete sound blob from accumulated frames
    const audioBlob = new Blob(audioChunksBufferRef.current, { type: "audio/mpeg" });
    audioChunksBufferRef.current = []; // Reset chunks

    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);
    currentAudioRef.current = audio;

    audio.onended = () => {
      setStatus("idle");
      URL.revokeObjectURL(audioUrl);
    };

    audio.play().catch(err => {
      console.error("Audio playback failed:", err);
      setStatus("idle");
    });
  };

  const stopLocalPlayback = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
  };

  const stopSession = () => {
    setStatus("disconnected");
    setIsRecording(false);
    
    stopLocalPlayback();

    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
    }
  };

  // User speech barge-in manual interrupt
  const triggerBargeInInterrupt = () => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
    stopLocalPlayback();
    setStatus("idle");
  };

  return (
    <div className="flex flex-col min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* Header Deck */}
      <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center space-x-3">
          <div className="w-4 h-4 bg-emerald-400 rounded-full animate-ping" />
          <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
            Aura: Multilingual Real-Time Clinical Voice Assistant
          </h1>
        </div>
        <div className="flex items-center space-x-4">
          <span className="text-xs text-slate-400">Time: 2026-05-22 13:12 UTC</span>
          <div className={`px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider flex items-center space-x-2 ${
            status === "disconnected" ? "bg-slate-800 text-slate-400" :
            status === "connecting" ? "bg-amber-500/20 text-amber-300 animate-pulse" :
            status === "idle" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40" :
            status === "processing" ? "bg-cyan-500/20 text-cyan-400 animate-pulse border border-cyan-500/40" :
            "bg-fuchsia-500/20 text-fuchsia-400 border border-fuchsia-500/40"
          }`}>
            <span className={`w-2 h-2 rounded-full ${
              status === "disconnected" ? "bg-slate-500" :
              status === "connecting" ? "bg-amber-400" :
              status === "idle" ? "bg-emerald-400" :
              status === "processing" ? "bg-cyan-400" : "bg-fuchsia-400"
            }`} />
            <span>{status}</span>
          </div>
        </div>
      </header>

      {/* Main Container Dashboard */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-6 p-6 max-w-7xl w-full mx-auto">
        
        {/* Left Side Column: Control cockpit and Voice Panel */}
        <section className="lg:col-span-1 flex flex-col space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl flex flex-col items-center justify-between space-y-6 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/10 rounded-full blur-3xl" />
            
            <h2 className="text-lg font-bold text-slate-200 self-start">Interactive Control Deck</h2>

            {/* Config parameters */}
            <div className="w-full space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">Patient Phone</label>
                <input
                  type="text"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  disabled={isRecording}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 text-slate-100 disabled:opacity-50"
                  placeholder="e.g. 9999999999"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">Session Key ID</label>
                <input
                  type="text"
                  value={sessionId}
                  onChange={(e) => setSessionId(e.target.value)}
                  disabled={isRecording}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 text-slate-100 disabled:opacity-50"
                  placeholder="session_id"
                />
              </div>
            </div>

            {/* Glowing Microphone Button */}
            <div className="py-6 flex flex-col items-center space-y-4 w-full">
              <button
                onClick={isRecording ? stopSession : startSession}
                className={`w-28 h-28 rounded-full flex items-center justify-center transition-all duration-500 cursor-pointer shadow-2xl relative ${
                  !isRecording ? "bg-slate-800 border-4 border-slate-700 hover:scale-105 hover:bg-slate-750" :
                  status === "connecting" ? "bg-amber-500 border-4 border-amber-400 animate-pulse scale-105" :
                  status === "processing" ? "bg-cyan-500 border-4 border-cyan-400 scale-105 animate-pulse shadow-cyan-500/50" :
                  status === "speaking" ? "bg-fuchsia-500 border-4 border-fuchsia-400 scale-105 shadow-fuchsia-500/50" :
                  "bg-emerald-500 border-4 border-emerald-400 scale-105 shadow-emerald-500/50"
                }`}
              >
                {/* Voice waveform canvas or icon */}
                {isRecording && (status === "speaking" || status === "processing") ? (
                  <div className="flex items-center space-x-1.5 justify-center">
                    <span className="w-1.5 h-8 bg-slate-950 rounded animate-bounce" style={{ animationDelay: '0.1s' }} />
                    <span className="w-1.5 h-12 bg-slate-950 rounded animate-bounce" style={{ animationDelay: '0.2s' }} />
                    <span className="w-1.5 h-6 bg-slate-950 rounded animate-bounce" style={{ animationDelay: '0.3s' }} />
                    <span className="w-1.5 h-10 bg-slate-950 rounded animate-bounce" style={{ animationDelay: '0.4s' }} />
                  </div>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor" className="w-10 h-10 text-slate-100">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z" />
                  </svg>
                )}
              </button>

              <span className="text-sm font-semibold tracking-wide text-slate-300">
                {!isRecording ? "Tap to Start Voice Session" : "Voice Stream Active"}
              </span>

              {isRecording && (
                <button
                  onClick={triggerBargeInInterrupt}
                  className="px-4 py-1.5 rounded-lg bg-red-500/20 text-red-400 border border-red-500/40 text-xs font-bold uppercase tracking-wider hover:bg-red-500/30 transition cursor-pointer"
                >
                  Force Interrupt Assistant
                </button>
              )}
            </div>

            {/* Conversation Dialog Flow display */}
            <div className="w-full bg-slate-950 border border-slate-800 rounded-xl p-4 h-64 overflow-y-auto space-y-4 select-none">
              <span className="text-xs font-semibold text-slate-500 uppercase block tracking-wider">Live Conversational Dialogue</span>
              {conversationHistory.length === 0 ? (
                <p className="text-xs text-slate-600 italic">No dialogue logged yet. Tap microphone above to speak.</p>
              ) : (
                conversationHistory.map((item, idx) => (
                  <div key={idx} className={`flex flex-col ${item.role === "user" ? "items-end" : "items-start"}`}>
                    <span className="text-[10px] text-slate-500 mb-0.5 font-bold uppercase">{item.role}</span>
                    <span className={`text-xs px-3.5 py-2 rounded-2xl max-w-[85%] leading-relaxed ${
                      item.role === "user" ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-tr-none" :
                      "bg-slate-850 text-slate-200 border border-slate-800 rounded-tl-none"
                    }`}>
                      {item.text}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>

        {/* Center Column: Live Telemetry Logs & System Reasoning */}
        <section className="lg:col-span-2 flex flex-col space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* STT/VAD Input log */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col space-y-3 shadow-xl">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">1. User Speech (STT Transcription)</span>
                <span className="w-2.5 h-2.5 bg-emerald-400 rounded-full animate-ping" />
              </div>
              <div className="bg-slate-950 rounded-xl p-4 h-28 border border-slate-800 overflow-y-auto text-sm leading-relaxed text-emerald-300">
                {userTranscript ? userTranscript : <span className="italic text-slate-600">Awaiting user vocal input...</span>}
              </div>
            </div>

            {/* Response translation output */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col space-y-3 shadow-xl">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">4. Assistant Localized Speech output</span>
              <div className="bg-slate-950 rounded-xl p-4 h-28 border border-slate-800 overflow-y-auto text-sm leading-relaxed text-slate-300">
                {assistantTranscript ? assistantTranscript : <span className="italic text-slate-600">No active syntheses...</span>}
              </div>
            </div>
          </div>

          {/* Reasoning telemetries */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col space-y-3 shadow-xl flex-1">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">2 & 3. Clinical Decision Reasoning Pipeline</span>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 flex-1">
              {/* English reasoning path */}
              <div className="md:col-span-2 flex flex-col space-y-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Aura Internal English Reasoning path</span>
                <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 flex-1 text-xs text-slate-400 font-mono overflow-y-auto leading-relaxed select-text">
                  {reasoningText ? reasoningText : <span className="italic text-slate-700">No active decisions buffered.</span>}
                </div>
              </div>

              {/* Step executions */}
              <div className="md:col-span-1 flex flex-col space-y-2">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">LangGraph state log</span>
                <div className="bg-slate-950 border border-slate-800 rounded-xl p-3 flex-1 text-[11px] text-cyan-400 font-mono overflow-y-auto space-y-1">
                  {stepLogs.length === 0 ? (
                    <span className="italic text-slate-700">Awaiting turns...</span>
                  ) : (
                    stepLogs.map((log, idx) => (
                      <div key={idx} className="flex items-center space-x-1.5 border-b border-slate-900 pb-1">
                        <span className="text-slate-600">❯</span>
                        <span>{log}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Database Display Deck Grid */}
      <section className="bg-slate-900/60 border-t border-slate-850 px-6 py-8">
        <div className="max-w-7xl mx-auto space-y-8">
          
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="flex items-center space-x-2">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5 text-emerald-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 1.028-.394 2.027-1.127 2.76A4.5 4.5 0 0 1 15.625 10.5H7.5A2.25 2.25 0 0 1 5.25 8.25V7.5a2.25 2.25 0 0 1 2.25-2.25h8.25c1.028 0 2.027.394 2.76 1.127l.127.128c.371.371.602.873.602 1.37ZM20.25 15.625c0 1.028-.394 2.027-1.127 2.76A4.5 4.5 0 0 1 15.625 19.5H7.5A2.25 2.25 0 0 1 5.25 17.25v-.75a2.25 2.25 0 0 1 2.25-2.25h8.25c1.028 0 2.027.394 2.76 1.127l.127.128c.371.371.602.873.602 1.37ZM2.25 12h19.5" />
              </svg>
              <h2 className="text-lg font-bold tracking-tight text-slate-200">Supabase Persistent Schema Display</h2>
            </div>
            
            <button
              onClick={triggerCampaign}
              disabled={isCampaignRunning}
              className="flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 font-bold rounded-xl text-xs uppercase tracking-wider transition shadow-lg cursor-pointer disabled:opacity-50"
            >
              {isCampaignRunning ? "Running..." : "Trigger Outbound Campaign Scheduler"}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            {/* Doctors List card */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
              <span className="text-xs font-bold text-slate-400 uppercase block tracking-wider">Clinical Doctors (PostgreSQL)</span>
              <div className="space-y-3 h-64 overflow-y-auto">
                {doctors.length === 0 ? (
                  <p className="text-xs text-slate-600 italic">No doctors populated. Restart backend server.</p>
                ) : (
                  doctors.map((doc) => (
                    <div key={doc.id} className="bg-slate-950 border border-slate-850 rounded-xl p-3.5 space-y-1.5">
                      <h4 className="text-xs font-bold text-slate-200">{doc.name}</h4>
                      <p className="text-[11px] text-emerald-400 font-semibold">{doc.specialization}</p>
                      <div className="flex space-x-1.5">
                        {doc.languages.map((lang, lidx) => (
                          <span key={lidx} className="text-[9px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 uppercase font-bold">{lang}</span>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Booked Appointments calendar list */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
              <span className="text-xs font-bold text-slate-400 uppercase block tracking-wider">Live Appointment Calendar Bookings</span>
              <div className="space-y-3 h-64 overflow-y-auto">
                {appointments.length === 0 ? (
                  <p className="text-xs text-slate-600 italic">No slots scheduled yet.</p>
                ) : (
                  appointments.map((appt) => (
                    <div key={appt.id} className="bg-slate-950 border border-slate-850 rounded-xl p-3 flex flex-col space-y-1.5 relative">
                      <div className="absolute top-3 right-3 w-2 h-2 bg-emerald-400 rounded-full" />
                      <h4 className="text-xs font-bold text-slate-200">{appt.patient_name}</h4>
                      <p className="text-[10px] text-slate-500">{appt.patient_phone}</p>
                      <div className="border-t border-slate-900 pt-2 space-y-1">
                        <p className="text-[11px] text-cyan-400">Dr. {appt.doctor_name} ({appt.specialization})</p>
                        <p className="text-[10px] text-slate-400 font-mono bg-slate-900 px-2 py-0.5 rounded self-start inline-block">
                          {new Date(appt.slot).toLocaleString("en-US", {
                            weekday: "short",
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit"
                          })}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Campaign Alert Outputs */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
              <span className="text-xs font-bold text-slate-400 uppercase block tracking-wider">Outbound Reminder Alert Feed</span>
              <div className="space-y-3 h-64 overflow-y-auto">
                {campaignAlerts.length === 0 ? (
                  <p className="text-xs text-slate-600 italic">No alerts dispatched. Click "Trigger Campaign Scheduler" above to check reminders.</p>
                ) : (
                  campaignAlerts.map((alert, aidx) => (
                    <div key={aidx} className="bg-slate-950 border border-amber-500/20 rounded-xl p-3.5 space-y-1 relative">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] bg-amber-500/10 text-amber-300 px-2 py-0.5 rounded uppercase font-bold">24H REMINDER</span>
                        <span className="text-[10px] text-slate-500 uppercase font-bold">{alert.language}</span>
                      </div>
                      <h4 className="text-xs font-bold text-slate-200">{alert.patient_name} ({alert.phone})</h4>
                      <p className="text-[11px] text-amber-200 leading-relaxed bg-amber-500/5 border border-amber-500/10 p-2 rounded-lg italic">
                        "{alert.message}"
                      </p>
                    </div>
                  ))
                )}
              </div>
            </div>

          </div>
        </div>
      </section>
    </div>
  );
}

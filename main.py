import sys
from pathlib import Path

# Ensure backend directory is on path so "services" and "routers" resolve when run from project root
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import profile, company_profile, leads, analysis, notes, chat, compare, lead_discovery, messaging, webhooks

app = FastAPI(title="DealFlow AI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile.router)
app.include_router(company_profile.router)
app.include_router(leads.router)
app.include_router(analysis.router)
app.include_router(notes.router)
app.include_router(chat.router)
app.include_router(compare.router)
app.include_router(lead_discovery.router)
app.include_router(messaging.router)
app.include_router(webhooks.router)


@app.get("/health")
def health():
    return {"status": "ok"}


import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import re

app = FastAPI(title="AI-Fake Blocker API")

# Allow requests from the extension and any domain (simplify for MVP; tighten later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Item(BaseModel):
    text: Optional[str] = ""
    meta: Optional[dict] = None

class ScoreRequest(BaseModel):
    items: List[Item]

@app.get("/")
def root():
    return {"ok": True, "message": "AI-Fake Blocker API running"}

def score_text(t: str):
    t = (t or "").strip()
    if not t:
        return 50, ["No text"]
    words = re.findall(r"\w+", t)
    score = 50
    reasons = ["Baseline heuristic"]
    if len(words) > 80:
        score += 10; reasons.append("Long post")
    if "as an ai" in t.lower():
        score += 20; reasons.append("LLM-style disclaimer")
    return max(0, min(100, score)), reasons

@app.post("/score")
def score(req: ScoreRequest):
    results = []
    for it in req.items:
        sc, rs = score_text((it.text or "")[:1000])
        results.append({"score": int(sc), "reasons": rs})
    return {"results": results}

if __name__ == "__main__":
    # Uvicorn entrypoint for local testing
    uvicorn.run(app, host="0.0.0.0", port=8000)

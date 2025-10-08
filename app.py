import os, random
from flask import Flask, request, jsonify, render_template_string, redirect, session
from flask_cors import CORS
from openai import OpenAI  # echte KI-Auswahl

# -------- Konfiguration --------
ADMIN_PASS = os.getenv("ADMIN_PASS", "passwort")    # Passwort fürs Dashboard
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")   # z. B. https://unibe.eu.qualtrics.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")    # OpenAI-Key

# Deine 3 finalen Antwortoptionen (KI & Mensch bekommen je ihre Liste)
AI_FEEDBACKS = [
    "In dieser Runde wurde ein substanzieller Teil korrekt gelöst. Mit gleicher Fokussierung ist eine weitere Steigerung wahrscheinlich.",
    "Die bearbeiteten Symbole zeigen soliden Aufgabenfortschritt. Halte das Tempo, dann steigt die Zahl korrekt gelöster Einträge.",
    "Die Ergebnisse deuten auf eine gute Arbeitsstrategie hin. Mit gleichbleibender Konzentration ist im nächsten Durchgang mehr möglich."
]
HUMAN_FEEDBACKS = [
    "Guter Fortschritt in dieser Runde – behalte deinen Rhythmus bei, dann ist eine Steigerung realistisch.",
    "Deine Struktur beim Bearbeiten funktioniert. Bleib dran, dann wächst die Anzahl korrekter Zuordnungen.",
    "Die Herangehensweise passt. Mit gleicher Konzentration kannst du im nächsten Durchlauf zulegen."
]

app = Flask(__name__)
app.secret_key = "change-me"
CORS(app, resources={r"/api/*": {"origins": [ALLOWED_ORIGIN]}}, supports_credentials=True)

oai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
STORE = {}  # key=(participant, round) → {"source","answers","status","feedback"}

def choose_ai_option(answers_text:str) -> int:
    # Erzwingt Ausgabe 1/2/3 per KI – Fallback: Zufall
    if not oai:
        return random.choice([1,2,3])
    system_msg = ("Du bist ein sachliches Feedbacksystem. "
                  "Wähle GENAU EINE Zahl (1,2 oder 3) als beste Option – ohne weitere Worte.")
    user_msg = (
        "Du hast drei vorgegebene Feedback-Optionen:\n"
        f"1) {AI_FEEDBACKS[0]}\n2) {AI_FEEDBACKS[1]}\n3) {AI_FEEDBACKS[2]}\n\n"
        "Kontext (Antworten/Leistungsauszug):\n" + (answers_text or "(kein Kontext)") + "\n\n"
        "Gib NUR die Ziffer der passenden Option zurück (1 oder 2 oder 3)."
    )
    try:
        resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":system_msg},
                      {"role":"user","content":user_msg}],
            temperature=0.0,
            max_tokens=3
        )
        raw = (resp.choices[0].message.content or "").strip()
        num = int(raw[0])
        if num in (1,2,3):
            return num
    except Exception:
        pass
    return random.choice([1,2,3])

@app.post("/api/feedback")
def api_feedback():
    data = request.get_json(force=True)
    participant = data.get("participant")
    rnd = int(data.get("round", 0))
    source = data.get("source")
    answers = data.get("answers", "")
    if not participant or rnd <= 0 or source not in ("ai","supervisor","control"):
        return jsonify({"error": "bad request"}), 400
    key = (participant, rnd)

    if source == "control":
        STORE[key] = {"source":source, "answers":answers, "status":"none", "feedback":""}
        return jsonify({"feedback": ""})

    if source == "ai":
        opt = choose_ai_option(answers)           # ← echte KI-Entscheidung
        fb = AI_FEEDBACKS[opt-1]
        STORE[key] = {"source":source, "answers":answers, "status":"ready", "feedback":fb}
        return jsonify({"feedback": fb, "option": opt})

    if source == "supervisor":
        STORE[key] = {"source":source, "answers":answers, "status":"pending", "feedback":None}
        return jsonify({"feedback": None, "status":"pending"})

    return jsonify({"feedback": ""})

@app.get("/api/feedback_status")
def api_feedback_status():
    participant = request.args.get("participant")
    rnd = request.args.get("round", type=int)
    key = (participant, rnd)
    item = STORE.get(key)
    if not item: return jsonify({"status":"not_found"})
    if item["status"] == "ready": return jsonify({"status":"ready","feedback":item["feedback"]})
    if item["status"] == "none":  return jsonify({"status":"none","feedback":""})
    return jsonify({"status":"pending","feedback":None})

# --------- sehr einfaches Human-Dashboard ----------
LOGIN_HTML = """
<!doctype html><meta charset="utf-8">
<h1>Supervisor Login</h1>
<form method="POST"><input name="password" type="password" placeholder="Passwort" required>
<button>Login</button></form>{{ msg or "" }}
"""
PANEL_HTML = """
<!doctype html><meta charset="utf-8">
<h1>Supervisor-Dashboard</h1>
<p>Für <b>supervisor</b>-Runden: wähle eine von 3 Optionen.</p>
<div id="list"></div>
<script>
async function load(){
  const r = await fetch('/admin/pending');
  const data = await r.json();
  const root = document.getElementById('list');
  if(!data.length){ root.innerHTML = '<p>Keine offenen Einträge.</p>'; return; }
  root.innerHTML = data.map(d => `
    <div style="border:1px solid #ddd;padding:10px;margin:10px 0">
      <b>${d.participant}</b> — Runde ${d.round}<br>
      <details><summary>Antworten ansehen</summary>
        <pre style="white-space:pre-wrap">${d.answers||"(leer)"}</pre>
      </details>
      <div style="margin-top:8px">
        <button onclick="send('${d.participant}',${d.round},1)">Option 1</button>
        <button onclick="send('${d.participant}',${d.round},2)">Option 2</button>
        <button onclick="send('${d.participant}',${d.round},3)">Option 3</button>
      </div>
    </div>`).join('');
}
async function send(p,r,opt){
  const res = await fetch('/admin/choose', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({participant:p, round:r, option:opt})});
  if(res.ok){ load(); } else { alert('Fehler beim Senden.'); }
}
load(); setInterval(load, 4000);
</script>
"""

@app.route("/admin", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASS:
            session["ok"] = True
            return redirect("/admin/panel")
        return render_template_string(LOGIN_HTML, msg="<p style='color:#c00'>Falsches Passwort.</p>")
    if session.get("ok"): return redirect("/admin/panel")
    return render_template_string(LOGIN_HTML, msg="")

@app.get("/admin/panel")
def admin_panel():
    if not session.get("ok"): return redirect("/admin")
    return render_template_string(PANEL_HTML)

@app.get("/admin/pending")
def admin_pending():
    if not session.get("ok"): return jsonify([]), 401
    out = []
    for (p, r), v in STORE.items():
        if v["status"] == "pending" and v["source"] == "supervisor":
            out.append({"participant":p, "round":r, "answers":v["answers"]})
    out.sort(key=lambda x: (x["participant"], x["round"]))
    return jsonify(out)

@app.post("/admin/choose")
def admin_choose():
    if not session.get("ok"): return jsonify({"error":"unauth"}), 401
    data = request.get_json(force=True)
    p = data.get("participant"); r = int(data.get("round",0)); opt = int(data.get("option",0))
    key = (p, r)
    if key not in STORE: return jsonify({"error":"not_found"}), 404
    if opt not in (1,2,3): return jsonify({"error":"bad_option"}), 400
    fb = HUMAN_FEEDBACKS[opt-1]
    STORE[key]["feedback"] = fb
    STORE[key]["status"] = "ready"
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)


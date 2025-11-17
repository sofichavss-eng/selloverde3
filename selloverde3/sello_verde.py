
import streamlit as st
import pandas as pd
import json, os, uuid, zipfile
from datetime import datetime
import matplotlib.pyplot as plt
import io

# Optional PDF (reportlab)
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

st.set_page_config(page_title="Sello Verde · Domino's", page_icon="🌿", layout="wide")

# Filenames (mismo nivel)
DATA_FILE = "sello_data.json"
CERT_FILE = "sello_certificados.json"
EVID_DIR = "sello_evidencias"

# ---------- CSS (estético A+B) ----------
st.markdown("""
<style>
body { background: #f7f9fb; }
[data-testid="stSidebar"] { background: linear-gradient(180deg,#ffffff,#f1fff1); }
.card { background: linear-gradient(180deg,#ffffff,#fcfffb); border-radius:14px; padding:14px; margin-bottom:12px; border-left:6px solid #2d6a4f; box-shadow:0 6px 20px rgba(25,50,40,0.06); }
h1,h2,h3 { color:#2d6a4f !important; font-weight:900 !important; }
div.stButton > button:first-child { background-color:#2d6a4f !important; color:white !important; border-radius:10px !important; padding:8px 14px !important; font-weight:700; }
.kpi { background:#fff; padding:12px; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.04); text-align:center; }
.small { font-size:12px; color:#666; }
</style>
""", unsafe_allow_html=True)

# ---------- Helpers: files ----------
def ensure_files():
    if not os.path.exists(EVID_DIR):
        os.makedirs(EVID_DIR)
    if not os.path.exists(DATA_FILE):
        base = {
            "sedes": {
                "Domino_Miraflores": {"nombre":"Domino's - Miraflores","municipio":"Miraflores","registros":[]},
                "Domino_SanIsidro": {"nombre":"Domino's - San Isidro","municipio":"San Isidro","registros":[]},
                "Domino_LimaCentro": {"nombre":"Domino's - Lima Centro","municipio":"Lima","registros":[]}
            }
        }
        with open(DATA_FILE,"w",encoding="utf-8") as f:
            json.dump(base,f,indent=2,ensure_ascii=False)
    if not os.path.exists(CERT_FILE):
        with open(CERT_FILE,"w",encoding="utf-8") as f:
            json.dump([],f,indent=2,ensure_ascii=False)

def load_data():
    with open(DATA_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def load_certs():
    with open(CERT_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

def save_certs(c):
    with open(CERT_FILE,"w",encoding="utf-8") as f:
        json.dump(c,f,indent=2,ensure_ascii=False)

# ---------- Scoring: extended ----------
MAP_LVL = {"low":1.0, "medium":0.6, "high":0.2}
DEFAULT_WEIGHTS = {"waste":0.20,"energy":0.15,"water":0.15,"recycle":0.15,"carbon":0.10,"oil":0.10,"hygiene":0.10}

def compute_score_full(rec, weights=None):
    if weights is None:
        weights = DEFAULT_WEIGHTS
    # waste: we map low/med/high
    w = MAP_LVL.get(rec.get("waste_level","medium"),0.6)
    # energy: if numeric kWh provided, map to low/med/high by thresholds
    e_val = rec.get("energy_kwh", None)
    if e_val is None:
        e = MAP_LVL.get(rec.get("energy_level","medium"),0.6)
    else:
        # thresholds can be adjusted; here simple heuristic
        if e_val <= 500: e = 1.0
        elif e_val <= 1200: e = 0.6
        else: e = 0.2
    # water: liters
    water_val = rec.get("water_liters", None)
    if water_val is None:
        wat = MAP_LVL.get(rec.get("water_level","medium"),0.6)
    else:
        if water_val <= 2000: wat = 1.0
        elif water_val <= 5000: wat = 0.6
        else: wat = 0.2
    # recycle percent (0..1)
    recycle_pct = rec.get("recycle_percent", None)
    if recycle_pct is None:
        recy = MAP_LVL.get(rec.get("recycle_level","medium"),0.6)
    else:
        if recycle_pct >= 0.6: recy = 1.0
        elif recycle_pct >= 0.3: recy = 0.6
        else: recy = 0.2
    # carbon: kgCO2
    carbon = rec.get("carbon_kg", None)
    if carbon is None:
        carb = 0.6
    else:
        if carbon <= 500: carb = 1.0
        elif carbon <= 1200: carb = 0.6
        else: carb = 0.2
    # oil handling: boolean (delivered to gestor)
    oil_ok = 1.0 if rec.get("oil_delivered", False) else 0.2
    # hygiene score: percent 0..1
    hygiene_pct = rec.get("hygiene_pct", None)
    if hygiene_pct is None:
        hyg = 0.6
    else:
        if hygiene_pct >= 0.9: hyg = 1.0
        elif hygiene_pct >= 0.7: hyg = 0.6
        else: hyg = 0.2

    score = (weights["waste"]*w + weights["energy"]*e + weights["water"]*wat +
             weights["recycle"]*recy + weights["carbon"]*carb + weights["oil"]*oil_ok + weights["hygiene"]*hyg) * 100
    return round(score,1)

def level_from_score(s):
    if s >= 76: return "Oro"
    if s >= 41: return "Plata"
    return "Bronce"

# ---------- Visual helpers ----------
def plot_trend_scores(sede):
    months = [r["month"] for r in sede["registros"]]
    scores = [compute_score_full(r) for r in sede["registros"]]
    if not months:
        return None
    fig, ax = plt.subplots(figsize=(6,2.2))
    ax.plot(months, scores, marker='o', color="#2d6a4f", linewidth=2)
    ax.set_ylim(0,100)
    ax.set_ylabel("Score")
    ax.grid(alpha=0.2)
    plt.xticks(rotation=30)
    plt.tight_layout()
    return fig

def df_from_sede(sede):
    rows=[]
    for r in reversed(sede["registros"][-12:]):
        rows.append({
            "Mes": r["month"],
            "Score": compute_score_full(r),
            "kWh": r.get("energy_kwh") or r.get("energy_level"),
            "Agua(L)": r.get("water_liters") or r.get("water_level"),
            "Recycle%": r.get("recycle_percent") or r.get("recycle_level"),
            "Oil(L)": r.get("oil_liters",0),
            "Higiene%": r.get("hygiene_pct") or "-",
            "Evid": "Sí" if r.get("evidence") else "No",
            "ID": r["id"]
        })
    return pd.DataFrame(rows)

# ---------- Utility: zip evidences ----------
def zip_evidences_for_sede(sede_key):
    files = []
    sede = data["sedes"][sede_key]
    for r in sede["registros"]:
        if r.get("evidence"):
            files.append(r["evidence"])
    if not files:
        return None
    zipname = f"{sede_key}_evidencias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(zipname, 'w') as zf:
        for f in files:
            if os.path.exists(f):
                zf.write(f, arcname=os.path.basename(f))
    return zipname

# ---------- Certificate PDF (better layout) ----------
def create_certificate_pdf(record, sede_name, nivel, out_path):
    if not REPORTLAB_AVAILABLE:
        return False, "reportlab no instalado"
    c = canvas.Canvas(out_path, pagesize=letter)
    # header
    c.setFillColorRGB(0.17,0.42,0.31)  # verde
    c.rect(0,730,612,70, fill=1)
    c.setFillColorRGB(1,1,1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(36,750, "SELLO VERDE · CERTIFICADO")
    c.setFont("Helvetica", 10)
    c.drawString(36,735, f"Sede: {sede_name}")
    c.setFillColorRGB(0,0,0)
    c.drawString(36,700, f"Nivel: {nivel}")
    c.drawString(36,680, f"Score: {compute_score_full(record)}")
    c.drawString(36,660, f"Fecha emisión: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    c.drawString(36,640, "Emitido por: Inspector (Demo)")
    c.save()
    return True, out_path

# ---------- Start app ----------
ensure_files()
data = load_data()
certs = load_certs()

# Header
col1,col2 = st.columns([1,4])
with col1:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=80)
with col2:
    st.markdown("<h1>🌿 Sello Verde · Domino's (FULL)</h1>", unsafe_allow_html=True)
    st.markdown("<div class='small'>Operación Responsable · Estado ↔ Empresa</div>", unsafe_allow_html=True)
st.markdown("---")

# Sidebar + KPIs
st.sidebar.header("Menú")
role = st.sidebar.radio("Entrar como", ["Empresa (Domino's)","Estado (Inspector)"])
st.sidebar.markdown("---")
# compute global stats
all_sedes = data["sedes"]
scores_all=[]
for s in all_sedes.values():
    for r in s["registros"]:
        scores_all.append(compute_score_full(r))
avg_score = round(sum(scores_all)/len(scores_all),1) if scores_all else "-"
st.sidebar.markdown(f"<div class='kpi'><strong>🏷️ Sedes:</strong><br>{len(all_sedes)}</div>", unsafe_allow_html=True)
st.sidebar.markdown(f"<div class='kpi' style='margin-top:8px'><strong>📄 Registros:</strong><br>{sum(len(s['registros']) for s in all_sedes.values())}</div>", unsafe_allow_html=True)
st.sidebar.markdown(f"<div class='kpi' style='margin-top:8px'><strong>📊 Score avg:</strong><br>{avg_score}</div>", unsafe_allow_html=True)

if role == "Estado (Inspector)":
    pwd = st.sidebar.text_input("Contraseña inspector:", type="password")
    if pwd != "inspect2025":
        st.sidebar.error("Contraseña incorrecta")
        st.stop()

# ---------- Empresa view ----------
def empresa_view():
    st.subheader("🏢 Panel Empresa — Registrar datos completos")
    sede_keys = list(data["sedes"].keys())
    sel = st.selectbox("Selecciona sede:", sede_keys, format_func=lambda k: data["sedes"][k]["nombre"])
    sede = data["sedes"][sel]

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### 📅 Datos del mes (completo)")
    colA, colB = st.columns([2,1])
    with colA:
        month = st.date_input("Mes a reportar (elige día del mes):", value=pd.to_datetime("today")).strftime("%Y-%m")
        # energy numeric
        energy_kwh = st.number_input("Consumo eléctrico (kWh) — este mes (ej: 850):", min_value=0.0, value=800.0, step=1.0)
        water_liters = st.number_input("Consumo de agua (litros) — este mes (ej: 3000):", min_value=0.0, value=2500.0, step=1.0)
    with colB:
        st.markdown("**Residuos y reciclaje**")
        waste_level = st.selectbox("Evaluación residuos (bajo/medio/alto):", ["low","medium","high"], index=1, format_func=lambda x: {"low":"Bajo","medium":"Medio","high":"Alto"}[x])
        card1,card2 = st.columns([1,1])
        with card1:
            carton_kg = st.number_input("Cartón (kg) reciclado este mes:", min_value=0.0, value=50.0, step=0.1)
            plastico_kg = st.number_input("Plástico (kg) reciclado:", min_value=0.0, value=5.0, step=0.1)
        with card2:
            organico_kg = st.number_input("Orgánico (kg):", min_value=0.0, value=20.0, step=0.1)
            oil_liters = st.number_input("Aceite usado (litros):", min_value=0.0, value=10.0, step=0.1)
        # compute recycle percent heuristic
        total_waste_est = max(1.0, carton_kg + plastico_kg + organico_kg + 10.0)  # add baseline
        recycle_percent = round((carton_kg + plastico_kg) / total_waste_est, 2)

    st.markdown("</div>", unsafe_allow_html=True)

    # Hygiene checklist simplified
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### 🧼 Control de higiene (checklist semanal resumido)")
    c1 = st.checkbox("Cámaras frigoríficas: OK", value=True)
    c2 = st.checkbox("Pisos/cocina: OK", value=True)
    c3 = st.checkbox("Lavamanos y jaboneras: OK", value=True)
    c4 = st.checkbox("Utensilios desinfectados: OK", value=True)
    c5 = st.checkbox("Gestión de residuos: OK", value=True)
    hygiene_pct = round(sum([c1,c2,c3,c4,c5])/5,2)
    st.markdown(f"Higiene (estimada): **{int(hygiene_pct*100)}%**")
    # temperatures
    st.markdown("**Control de temperaturas**")
    temp_freezer = st.number_input("Temperatura freezer (°C):", value=-18.0, step=0.1)
    temp_fridge = st.number_input("Temperatura refrigerador (°C):", value=4.0, step=0.1)
    temp_ok = True
    if not (-25 <= temp_freezer <= -15): temp_ok = False
    if not (1 <= temp_fridge <= 6): temp_ok = False
    st.markdown("</div>", unsafe_allow_html=True)

    # Carbon simple estimator (very rough): energy_kwh * factor + fuel km * factor (we don't have km so skip)
    carbon_est = round(0.475 * energy_kwh + 0.0, 1)  # 0.475 kgCO2 per kWh as example

    # Evidence upload and category
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### 📸 Evidencias y comprobantes")
    ev_cat = st.selectbox("Categoría de evidencia:", ["general","residuos","aceite","factura_proveedor","higiene"])
    up = st.file_uploader("Subir evidencia (foto/pdf):", type=["png","jpg","jpeg","pdf"])
    ev_path = None
    if up:
        fn = f"{sel}_{ev_cat}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{up.name}"
        path = os.path.join(EVID_DIR, fn)
        with open(path, "wb") as f:
            f.write(up.getbuffer())
        ev_path = path
        st.success("Evidencia guardada ✅")
    st.markdown("</div>", unsafe_allow_html=True)

    # Save record
    if st.button("Guardar registro completo"):
        rec = {
            "id": str(uuid.uuid4())[:8],
            "month": month,
            "energy_kwh": float(energy_kwh),
            "water_liters": float(water_liters),
            "waste_level": waste_level,
            "carton_kg": float(carton_kg),
            "plastico_kg": float(plastico_kg),
            "organico_kg": float(organico_kg),
            "oil_liters": float(oil_liters),
            "oil_delivered": False,  # toggle later when delivered to gestor
            "recycle_percent": recycle_percent,
            "hygiene_pct": hygiene_pct,
            "temp_freezer": float(temp_freezer),
            "temp_fridge": float(temp_fridge),
            "temp_ok": temp_ok,
            "carbon_kg": carbon_est,
            "practices": {"cajas_biodegradables": True},  # placeholder
            "evidence": ev_path,
            "created_at": datetime.now().isoformat()
        }
        sede["registros"].append(rec)
        save_data(data)
        st.success("Registro guardado (completo).")
        st.experimental_rerun()

    st.markdown("---")
    # History table & edit (reuse df_from_sede)
    st.subheader("🧾 Historial y edición")
    df = df_from_sede(sede)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        sel_id = st.selectbox("Selecciona ID para ver/editar:", df["ID"].tolist())
        rec_obj = next((r for r in sede["registros"] if r["id"]==sel_id), None)
        if rec_obj:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("### ✏️ Ver detalles")
            st.write(rec_obj)
            if st.button("Marcar aceite como entregado al gestor (comprobante)"):
                rec_obj["oil_delivered"] = True
                save_data(data)
                st.success("Marcado como entregado.")
                st.experimental_rerun()
            if st.button("Eliminar registro"):
                sede["registros"] = [r for r in sede["registros"] if r["id"]!=sel_id]
                save_data(data)
                st.success("Registro eliminado.")
                st.experimental_rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("Sin registros aún para esta sede.")

    # Trend chart
    fig = plot_trend_scores(sede)
    if fig:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.subheader("📈 Tendencia de Score")
        st.pyplot(fig)
        st.markdown("</div>", unsafe_allow_html=True)

    # Export evidences zip
    st.markdown("---")
    st.subheader("📁 Exportar evidencias")
    zipfile_path = zip_evidences_for_sede(sel)
    if zipfile_path:
        with open(zipfile_path,"rb") as f:
            st.download_button("📥 Descargar evidencias (ZIP)", f, file_name=zipfile_path)
    else:
        st.info("No hay evidencias para comprimir.")

    # Alerts
    st.markdown("---")
    st.subheader("⚠️ Alertas automáticas")
    last = sede["registros"][-1] if sede["registros"] else None
    if last:
        score = compute_score_full(last)
        if not last.get("temp_ok"):
            st.error("Temperaturas fuera de rango! Revisar refrigeración.")
        if last.get("oil_liters",0) > 20 and not last.get("oil_delivered"):
            st.warning("Aceite usado alto y no entregado al gestor (recomendado entregar).")
        if score < 50:
            st.error(f"Puntaje bajo: {score}. Acción recomendada: plan de mejora.")
        else:
            st.success(f"Puntaje: {score} — OK")
    else:
        st.info("Sin registros — crea uno para activar alertas.")

# ---------- Estado view ----------
def estado_view():
    st.subheader("🏛️ Panel Estado — Supervisión completa")
    # Table overview
    rows=[]
    for key,s in data["sedes"].items():
        last = s["registros"][-1] if s["registros"] else None
        score = compute_score_full(last) if last else None
        level = level_from_score(score) if last else "Sin datos"
        rows.append({"id":key,"Sede":s["nombre"],"Municipio":s["municipio"],"Último mes": last["month"] if last else "-", "Score":score or "-", "Nivel":level})
    df_ov = pd.DataFrame(rows).sort_values(by="Score", ascending=False, na_position="last")
    st.dataframe(df_ov, use_container_width=True)

    st.markdown("---")
    st.markdown("### 🔎 Revisar y emitir sello")
    sel = st.selectbox("Selecciona sede:", list(data["sedes"].keys()), format_func=lambda k: data["sedes"][k]["nombre"])
    sede = data["sedes"][sel]
    if sede["registros"]:
        last = sede["registros"][-1]
        score = compute_score_full(last)
        nivel = level_from_score(score)
        color = {"Oro":"#ffd700","Plata":"#adb5bd","Bronce":"#c08457"}[nivel]
        st.markdown(f"<div class='card'><h3>🏅 {sede['nombre']}</h3><p><strong>Mes:</strong> {last['month']} &nbsp; <strong>Score:</strong> {score} &nbsp; <strong>Nivel:</strong> <span style='color:{color}'>{nivel}</span></p><div style='background:#e6e6e6;border-radius:10px;height:16px;'><div style='width:{score}%;background:{color};height:16px;border-radius:10px;'></div></div></div>", unsafe_allow_html=True)
        # show small indicators
        st.markdown("**Indicadores clave:**")
        cols = st.columns(4)
        cols[0].metric("kWh", last.get("energy_kwh", "-"))
        cols[1].metric("Agua (L)", last.get("water_liters", "-"))
        cols[2].metric("Aceite (L)", last.get("oil_liters", "-"))
        cols[3].metric("Recycle %", str(last.get("recycle_percent", "-")))

        if last.get("evidence") and os.path.exists(last["evidence"]):
            st.image(last["evidence"], width=300)

        if st.button("Emitir Sello Verde (registrar)"):
            reg = {"id":str(uuid.uuid4())[:8],"sede_id":sel,"sede_nombre":sede["nombre"],"score":score,"nivel":nivel,"fecha":datetime.now().strftime("%d/%m/%Y %H:%M"),"emitido_por":"Inspector (PRO)"}
            certs.append(reg)
            save_certs(certs)
            st.success("Sello emitido y registrado.")
            # PDF
            if REPORTLAB_AVAILABLE:
                pdf_path = f"cert_{reg['id']}.pdf"
                ok,res = create_certificate_pdf(last, sede["nombre"], nivel, pdf_path)
                if ok:
                    with open(pdf_path,"rb") as f:
                        st.download_button("📥 Descargar PDF Sello", f, file_name=pdf_path)
                else:
                    st.info("PDF error: "+str(res))
            else:
                st.info("Instala reportlab para PDF (opcional).")
    else:
        st.info("Sin registros para esta sede.")

    st.markdown("---")
    st.subheader("📜 Historial Sellos")
    if certs:
        st.dataframe(pd.DataFrame(certs))
        csv = pd.DataFrame(certs).to_csv(index=False).encode("utf-8")
        st.download_button("📥 Descargar historial sellos (CSV)", csv, "sellos.csv", "text/csv")
    else:
        st.info("No hay sellos emitidos aún.")

# Main routing
if role == "Empresa (Domino's)":
    empresa_view()
else:
    estado_view()

st.markdown("---")
st.caption("🌿 Sello Verde · Domino's · Versión FULL — Proyecto académico 2025")
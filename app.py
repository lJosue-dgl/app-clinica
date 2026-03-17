from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import sqlite3
import os
import re
import pandas as pd
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from ocr_imagen import extract_text_from_image
from ocr_pdf import extract_text_from_pdf
from lab_parser import parse_lab_results

app = Flask(__name__)
app.secret_key = "supersecretkey"

DATABASE = "metabolic.db"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_FOLDER = os.path.join(BASE_DIR, "exports")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

# CAMBIA ESTO POR TU BUCKET REAL
GCS_BUCKET_NAME = "app-clinica-ocr-josue"

os.makedirs(EXPORT_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ----------------------------
# DATABASE
# ----------------------------
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        national_id TEXT NOT NULL UNIQUE,
        birth_date TEXT,
        sex TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lab_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        exam_date TEXT NOT NULL,
        fasting_glucose REAL,
        hba1c REAL,
        triglycerides REAL,
        hdl REAL,
        ldl REAL,
        alt_tgp REAL,
        ast_tgo REAL,
        source TEXT DEFAULT 'manual',
        FOREIGN KEY (patient_id) REFERENCES patients (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS doctors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """)

    conn.commit()

    # crear doctor por defecto si no existe
    existing_doctor = conn.execute(
        "SELECT * FROM doctors WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not existing_doctor:
        hashed_password = generate_password_hash("admin123")
        conn.execute(
            "INSERT INTO doctors (username, password) VALUES (?, ?)",
            ("admin", hashed_password)
        )
        conn.commit()

    conn.close()


# ----------------------------
# AUTH DECORATOR
# ----------------------------
def doctor_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "doctor_id" not in session:
            flash("Please log in as doctor first.", "warning")
            return redirect(url_for("doctor_login"))
        return f(*args, **kwargs)
    return decorated_function


# ----------------------------
# HELPERS
# ----------------------------
def safe_filename(text):
    text = text.strip()
    text = text.replace(" ", "_")
    text = re.sub(r'[^A-Za-z0-9_\-áéíóúÁÉÍÓÚñÑ]', '', text)
    return text

def calculate_age(birth_date_str):
    if not birth_date_str:
        return None

    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
        today = date.today()

        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
        return age
    except:
        return None

def export_patient_to_excel(patient_id):
    conn = get_db_connection()

    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()

    results = conn.execute("""
        SELECT exam_date, fasting_glucose, hba1c, triglycerides, hdl, ldl, alt_tgp, ast_tgo, source
        FROM lab_results
        WHERE patient_id = ?
        ORDER BY exam_date ASC
    """, (patient_id,)).fetchall()

    conn.close()

    if not patient:
        return None

    df = pd.DataFrame(results, columns=[
        "Exam Date",
        "Fasting Glucose",
        "HbA1c",
        "Triglycerides",
        "HDL",
        "LDL",
        "ALT (TGP)",
        "AST (TGO)",
        "Source"
    ])

    safe_name = safe_filename(patient["full_name"])
    filename = f"{safe_name}_{patient['id']}.xlsx"
    filepath = os.path.join(EXPORT_FOLDER, filename)

    df.to_excel(filepath, index=False)
    return filepath


# ----------------------------
# HOME
# ----------------------------
@app.route("/")
def home():
    return render_template("home.html")


# ----------------------------
# REGISTER PATIENT
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        national_id = request.form["national_id"].strip()
        birth_date = request.form["birth_date"]
        sex = request.form["sex"]

        if not full_name or not national_id:
            flash("Name and ID are required.", "danger")
            return redirect(url_for("register"))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO patients (full_name, national_id, birth_date, sex)
                VALUES (?, ?, ?, ?)
            """, (full_name, national_id, birth_date, sex))
            conn.commit()

            patient_id = cursor.lastrowid
            conn.close()

            flash("Patient registered successfully.", "success")
            return redirect(url_for("patient_portal", patient_id=patient_id))

        except sqlite3.IntegrityError:
            flash("This national ID already exists.", "danger")
            return redirect(url_for("register"))

    return render_template("register.html")

# ----------------------------
# EXISTING PATIENT ACCESS
# ----------------------------
@app.route("/existing_patient", methods=["GET", "POST"])
def existing_patient():
    if request.method == "POST":
        national_id = request.form["national_id"].strip()

        if not national_id:
            flash("National ID is required.", "danger")
            return redirect(url_for("existing_patient"))

        conn = get_db_connection()
        patient = conn.execute(
            "SELECT * FROM patients WHERE national_id = ?",
            (national_id,)
        ).fetchone()
        conn.close()

        if not patient:
            flash("Patient not found. Please register first.", "danger")
            return redirect(url_for("existing_patient"))

        return redirect(url_for("patient_portal", patient_id=patient["id"]))

    return render_template("existing_patient.html")

# ----------------------------
# PATIENT PORTAL
# ----------------------------
@app.route("/patient/<int:patient_id>")
def patient_portal(patient_id):
    conn = get_db_connection()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()
    conn.close()

    if not patient:
        flash("Patient not found.", "danger")
        return redirect(url_for("home"))

    age = calculate_age(patient["birth_date"])

    return render_template("patient_portal.html", patient=patient, age=age)


# ----------------------------
# MANUAL UPLOAD
# ----------------------------
@app.route("/upload_manual/<int:patient_id>", methods=["GET", "POST"])
def upload_manual(patient_id):
    conn = get_db_connection()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()

    if not patient:
        conn.close()
        flash("Patient not found.", "danger")
        return redirect(url_for("home"))

    age = calculate_age(patient["birth_date"])

    if request.method == "POST":
        exam_date = request.form["exam_date"]

        def safe_float(value):
            return float(value) if value.strip() else None

        fasting_glucose = safe_float(request.form.get("fasting_glucose", ""))
        hba1c = safe_float(request.form.get("hba1c", ""))
        triglycerides = safe_float(request.form.get("triglycerides", ""))
        hdl = safe_float(request.form.get("hdl", ""))
        ldl = safe_float(request.form.get("ldl", ""))
        alt_tgp = safe_float(request.form.get("alt_tgp", ""))
        ast_tgo = safe_float(request.form.get("ast_tgo", ""))

        if not exam_date:
            flash("Exam date is required.", "danger")
            conn.close()
            return redirect(url_for("upload_manual", patient_id=patient_id))

        conn.execute("""
            INSERT INTO lab_results
            (patient_id, exam_date, fasting_glucose, hba1c, triglycerides, hdl, ldl, alt_tgp, ast_tgo, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            patient_id, exam_date, fasting_glucose, hba1c,
            triglycerides, hdl, ldl, alt_tgp, ast_tgo, "manual"
        ))
        conn.commit()
        conn.close()

        export_patient_to_excel(patient_id)

        flash("Lab results saved successfully.", "success")
        return redirect(url_for("patient_portal", patient_id=patient_id))

    conn.close()
    return render_template("upload_manual.html", patient=patient, age=age)

# ----------------------------
# OCR UPLOAD IMAGE / PDF
# ----------------------------
@app.route("/upload_file/<int:patient_id>", methods=["GET", "POST"])
def upload_file(patient_id):
    conn = get_db_connection()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()

    if not patient:
        conn.close()
        flash("Patient not found.", "danger")
        return redirect(url_for("home"))

    age = calculate_age(patient["birth_date"])

    if request.method == "POST":
        exam_date = request.form["exam_date"]
        file = request.files.get("file")

        if not exam_date:
            flash("Exam date is required.", "danger")
            conn.close()
            return redirect(url_for("upload_file", patient_id=patient_id))

        if not file or file.filename == "":
            flash("Please upload an image or PDF file.", "danger")
            conn.close()
            return redirect(url_for("upload_file", patient_id=patient_id))

        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        ext = os.path.splitext(filename)[1].lower()

        try:
            if ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
                text = extract_text_from_image(filepath)
            elif ext == ".pdf":
                text = extract_text_from_pdf(filepath, GCS_BUCKET_NAME)
            else:
                flash("Unsupported file format.", "danger")
                conn.close()
                return redirect(url_for("upload_file", patient_id=patient_id))

            results = parse_lab_results(text)

            conn.execute("""
                INSERT INTO lab_results
                (patient_id, exam_date, fasting_glucose, hba1c, triglycerides, hdl, ldl, alt_tgp, ast_tgo, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                patient_id,
                exam_date,
                results["glucose"],
                results["hba1c"],
                results["triglycerides"],
                results["hdl"],
                results["ldl"],
                results["alt_tgp"],
                results["ast_tgo"],
                "ocr"
            ))
            conn.commit()
            conn.close()

            export_patient_to_excel(patient_id)

            flash("Lab results extracted and saved successfully.", "success")
            return redirect(url_for("patient_portal", patient_id=patient_id))

        except Exception as e:
            conn.close()
            flash(f"OCR error: {str(e)}", "danger")
            return redirect(url_for("upload_file", patient_id=patient_id))

    conn.close()
    return render_template("upload_file.html", patient=patient, age=age)


# ----------------------------
# DOCTOR LOGIN
# ----------------------------
@app.route("/doctor_login", methods=["GET", "POST"])
def doctor_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db_connection()
        doctor = conn.execute(
            "SELECT * FROM doctors WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if doctor and check_password_hash(doctor["password"], password):
            session["doctor_id"] = doctor["id"]
            session["doctor_username"] = doctor["username"]
            flash("Login successful.", "success")
            return redirect(url_for("doctor_dashboard"))

        flash("Invalid username or password.", "danger")
        return redirect(url_for("doctor_login"))

    return render_template("doctor_login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Session closed.", "info")
    return redirect(url_for("home"))


# ----------------------------
# DOCTOR DASHBOARD
# ----------------------------
@app.route("/doctor_dashboard")
@doctor_login_required
def doctor_dashboard():
    conn = get_db_connection()
    patients = conn.execute("SELECT * FROM patients ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("doctor_dashboard.html", patients=patients)


# ----------------------------
# PATIENT CLINICAL DASHBOARD
# ----------------------------
@app.route("/dashboard/<int:patient_id>")
@doctor_login_required
def dashboard(patient_id):
    conn = get_db_connection()

    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()

    results = conn.execute("""
        SELECT * FROM lab_results
        WHERE patient_id = ?
        ORDER BY exam_date ASC
    """, (patient_id,)).fetchall()

    conn.close()

    if not patient:
        flash("Patient not found.", "danger")
        return redirect(url_for("doctor_dashboard"))

    chart_dates = [r["exam_date"] for r in results]
    glucose_values = [r["fasting_glucose"] for r in results]
    hba1c_values = [r["hba1c"] for r in results]
    tg_values = [r["triglycerides"] for r in results]
    hdl_values = [r["hdl"] for r in results]
    ldl_values = [r["ldl"] for r in results]
    alt_values = [r["alt_tgp"] for r in results]
    ast_values = [r["ast_tgo"] for r in results]

    return render_template(
        "dashboard.html",
        patient=patient,
        results=results,
        chart_dates=chart_dates,
        glucose_values=glucose_values,
        hba1c_values=hba1c_values,
        tg_values=tg_values,
        hdl_values=hdl_values,
        ldl_values=ldl_values,
        alt_values=alt_values,
        ast_values=ast_values
    )


# ----------------------------
# EXPORT EXCEL
# ----------------------------
@app.route("/export/<int:patient_id>")
@doctor_login_required
def export(patient_id):
    conn = get_db_connection()
    patient = conn.execute(
        "SELECT * FROM patients WHERE id = ?",
        (patient_id,)
    ).fetchone()
    conn.close()

    if not patient:
        flash("Patient not found.", "danger")
        return redirect(url_for("doctor_dashboard"))

    filepath = export_patient_to_excel(patient_id)

    if not filepath or not os.path.exists(filepath):
        flash("The Excel file could not be generated.", "danger")
        return redirect(url_for("dashboard", patient_id=patient_id))

    filename = os.path.basename(filepath)
    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
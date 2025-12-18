import os
import secrets
from datetime import datetime, timedelta, date
from functools import wraps
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, abort,
    send_from_directory, make_response
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

# ======================================================
# FLASK APP (THIS FIXES YOUR GUNICORN ERROR)
# ======================================================

app = Flask(__name__)

# ======================================================
# CONFIG
# ======================================================

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///academic_assist.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["ALLOWED_EXTENSIONS"] = {"pdf", "png", "jpg", "jpeg", "doc", "docx"}

db = SQLAlchemy(app)

# ======================================================
# MODELS
# ======================================================

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    email = db.Column(db.String(150))
    contact = db.Column(db.String(50))
    university = db.Column(db.String(150))
    assignment_type = db.Column(db.String(100))
    subject = db.Column(db.String(150))
    due_date = db.Column(db.Date)
    details = db.Column(db.Text)
    assignment_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuizRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    email = db.Column(db.String(150))
    contact = db.Column(db.String(50))
    university = db.Column(db.String(150))
    subject = db.Column(db.String(150))
    quiz_type = db.Column(db.String(100))
    test_date = db.Column(db.Date)
    topics = db.Column(db.Text)
    quiz_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ExamRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    email = db.Column(db.String(150))
    contact = db.Column(db.String(50))
    university = db.Column(db.String(150))
    subject = db.Column(db.String(150))
    exam_type = db.Column(db.String(100))
    exam_date = db.Column(db.Date)
    topics = db.Column(db.Text)
    exam_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ======================================================
# HELPERS
# ======================================================

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]

def admin_login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def ensure_dirs():
    for d in ["assignments", "quizzes", "exams", "payments"]:
        os.makedirs(f"static/uploads/{d}", exist_ok=True)

# ======================================================
# ROUTES
# ======================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        admin = Admin.query.filter_by(
            username=request.form["username"],
            password=request.form["password"]
        ).first()

        if admin:
            session["admin_id"] = admin.id
            return redirect(url_for("dashboard"))

        flash("Invalid credentials", "danger")

    return render_template("login.html")


@app.route("/dashboard")
@admin_login_required
def dashboard():
    return render_template(
        "dashboard.html",
        assignments=Assignment.query.all(),
        quizzes=QuizRequest.query.all(),
        exams=ExamRequest.query.all()
    )


@app.route("/download/<folder>/<filename>")
@admin_login_required
def download_file(folder, filename):
    path = f"static/uploads/{folder}"
    return send_from_directory(path, secure_filename(filename), as_attachment=True)


@app.route("/submit-assignment", methods=["POST"])
def submit_assignment():
    file = request.files.get("file")
    filename = None

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(f"static/uploads/assignments/{filename}")

    record = Assignment(
        name=request.form["name"],
        email=request.form["email"],
        contact=request.form["contact"],
        university=request.form["university"],
        assignment_type=request.form["assignment_type"],
        subject=request.form["subject"],
        due_date=datetime.strptime(request.form["due_date"], "%Y-%m-%d"),
        details=request.form["details"],
        assignment_file=filename
    )

    db.session.add(record)
    db.session.commit()

    session["assignment_id"] = record.id
    return redirect(url_for("payment"))


@app.route("/payment")
def payment():
    return render_template("payment.html")


@app.route("/upload-proof", methods=["POST"])
def upload_proof():
    proof = request.files.get("proof")

    if proof and allowed_file(proof.filename):
        filename = secure_filename(proof.filename)
        proof.save(f"static/uploads/payments/{filename}")

        a = Assignment.query.get(session.get("assignment_id"))
        if a:
            a.proof_of_payment = filename
            a.status = "Payment Submitted"
            db.session.commit()

    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ======================================================
# INIT
# ======================================================

with app.app_context():
    db.create_all()
    ensure_dirs()

    if not Admin.query.filter_by(username="admin").first():
        db.session.add(Admin(username="admin", password="admin123"))
        db.session.commit()

# ======================================================
# ENTRY POINT (IMPORTANT)
# ======================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

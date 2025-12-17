from flask import send_from_directory, abort, send_file, make_response
from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta, date
from sqlalchemy import text
from werkzeug.utils import secure_filename
from functools import wraps
import pytz
import os
from flask_sqlalchemy import SQLAlchemy
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

app = Flask(__name__)

# Configure the app FIRST
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Required for session

# File upload configuration
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'txt'}

# Database Configuration - Use SQLite for local development
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Use PostgreSQL if DATABASE_URL is set, otherwise use SQLite locally
if DATABASE_URL:
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Use SQLite for local development - no PostgreSQL server needed
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, 'academic_assist.db')}"

# Now create the SQLAlchemy instance AFTER app is configured
db = SQLAlchemy(app)


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    
    # Student details
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    university = db.Column(db.String(150), nullable=False)
    
    # Assignment details
    assignment_type = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    details = db.Column(db.Text, nullable=False)
    
    # Files
    assignment_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    
    # Status
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuizRequest(db.Model):
    __tablename__ = "quiz_requests"

    id = db.Column(db.Integer, primary_key=True)
    
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    university = db.Column(db.String(150))
    
    subject = db.Column(db.String(150), nullable=False)
    quiz_type = db.Column(db.String(100), nullable=False)
    test_date = db.Column(db.Date, nullable=False)
    topics = db.Column(db.Text)
    
    quiz_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ExamRequest(db.Model):
    __tablename__ = "exam_requests"

    id = db.Column(db.Integer, primary_key=True)
    
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    university = db.Column(db.String(150), nullable=False)
    
    subject = db.Column(db.String(150), nullable=False)
    exam_type = db.Column(db.String(100), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    topics = db.Column(db.Text)
    
    exam_file = db.Column(db.String(255))
    proof_of_payment = db.Column(db.String(255))
    
    status = db.Column(db.String(50), default="Pending Payment")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Admin(db.Model):
    __tablename__ = "admins"
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# Add datetime filter to Jinja2
@app.template_filter('datetime')
def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    if value is None:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            return value
    return value.strftime(format)


@app.template_filter('dateonly')
def format_date(value, format='%Y-%m-%d'):
    if value is None:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            return value
    return value.strftime(format)


@app.template_filter('is_expired')
def is_expired(due_date):
    if not due_date:
        return True
    if isinstance(due_date, str):
        due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
    return due_date < date.today()


@app.route("/")
def home():
    return render_template("index.html")


@app.route('/download/<service>/<filename>')
def download_file(service, filename):
    folder_map = {
        "assignments": "static/uploads/assignments",
        "quizzes": "static/uploads/quizzes",
        "exams": "static/uploads/exams",
        "payments": "static/uploads/payments"
    }
    
    folder = folder_map.get(service)
    if not folder:
        abort(404)
    
    # Ensure the directory exists
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
        abort(404)  # File still doesn't exist even after creating directory
    
    try:
        # Sanitize the filename
        filename = secure_filename(filename)
        return send_from_directory(folder, filename, as_attachment=True)
    except FileNotFoundError:
        abort(404)


@app.route("/download-pdf/assignment/<int:id>")
@admin_login_required
def download_assignment_pdf(id):
    assignment = Assignment.query.get_or_404(id)
    
    # Create a PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6,
        spaceBefore=12
    )
    
    normal_style = styles["Normal"]
    
    # Title
    elements.append(Paragraph("Assignment Details", title_style))
    elements.append(Spacer(1, 20))
    
    # Student Information
    elements.append(Paragraph("Student Information", heading_style))
    student_data = [
        ["Name:", assignment.name],
        ["Email:", assignment.email],
        ["Contact:", assignment.contact],
        ["University:", assignment.university]
    ]
    
    student_table = Table(student_data, colWidths=[1.5*inch, 4*inch])
    student_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(student_table)
    elements.append(Spacer(1, 20))
    
    # Assignment Details
    elements.append(Paragraph("Assignment Details", heading_style))
    assignment_data = [
        ["Assignment Type:", assignment.assignment_type],
        ["Subject:", assignment.subject],
        ["Due Date:", assignment.due_date.strftime('%Y-%m-%d')],
        ["Status:", assignment.status],
        ["Created:", assignment.created_at.strftime('%Y-%m-%d %H:%M:%S')]
    ]
    
    assignment_table = Table(assignment_data, colWidths=[1.5*inch, 4*inch])
    assignment_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(assignment_table)
    elements.append(Spacer(1, 20))
    
    # Assignment Description
    elements.append(Paragraph("Assignment Description", heading_style))
    elements.append(Paragraph(assignment.details, normal_style))
    
    # Build PDF
    doc.build(elements)
    
    buffer.seek(0)
    
    # Create response
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=assignment_{id}_details.pdf'
    
    return response


@app.route("/download-pdf/quiz/<int:id>")
@admin_login_required
def download_quiz_pdf(id):
    quiz = QuizRequest.query.get_or_404(id)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6,
        spaceBefore=12
    )
    
    normal_style = styles["Normal"]
    
    # Title
    elements.append(Paragraph("Quiz Request Details", title_style))
    elements.append(Spacer(1, 20))
    
    # Student Information
    elements.append(Paragraph("Student Information", heading_style))
    student_data = [
        ["Name:", quiz.name],
        ["Email:", quiz.email],
        ["Contact:", quiz.contact],
        ["University:", quiz.university or "Not specified"]
    ]
    
    student_table = Table(student_data, colWidths=[1.5*inch, 4*inch])
    student_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(student_table)
    elements.append(Spacer(1, 20))
    
    # Quiz Details
    elements.append(Paragraph("Quiz Details", heading_style))
    quiz_data = [
        ["Quiz Type:", quiz.quiz_type],
        ["Subject:", quiz.subject],
        ["Test Date:", quiz.test_date.strftime('%Y-%m-%d')],
        ["Status:", quiz.status],
        ["Created:", quiz.created_at.strftime('%Y-%m-%d %H:%M:%S')]
    ]
    
    quiz_table = Table(quiz_data, colWidths=[1.5*inch, 4*inch])
    quiz_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(quiz_table)
    elements.append(Spacer(1, 20))
    
    # Topics
    if quiz.topics:
        elements.append(Paragraph("Topics to Cover", heading_style))
        elements.append(Paragraph(quiz.topics, normal_style))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=quiz_{id}_details.pdf'
    
    return response


@app.route("/download-pdf/exam/<int:id>")
@admin_login_required
def download_exam_pdf(id):
    exam = ExamRequest.query.get_or_404(id)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=6,
        spaceBefore=12
    )
    
    normal_style = styles["Normal"]
    
    # Title
    elements.append(Paragraph("Exam Request Details", title_style))
    elements.append(Spacer(1, 20))
    
    # Student Information
    elements.append(Paragraph("Student Information", heading_style))
    student_data = [
        ["Name:", exam.name],
        ["Email:", exam.email],
        ["Contact:", exam.contact],
        ["University:", exam.university]
    ]
    
    student_table = Table(student_data, colWidths=[1.5*inch, 4*inch])
    student_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(student_table)
    elements.append(Spacer(1, 20))
    
    # Exam Details
    elements.append(Paragraph("Exam Details", heading_style))
    exam_data = [
        ["Exam Type:", exam.exam_type],
        ["Subject:", exam.subject],
        ["Exam Date:", exam.exam_date.strftime('%Y-%m-%d')],
        ["Status:", exam.status],
        ["Created:", exam.created_at.strftime('%Y-%m-%d %H:%M:%S')]
    ]
    
    exam_table = Table(exam_data, colWidths=[1.5*inch, 4*inch])
    exam_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(exam_table)
    elements.append(Spacer(1, 20))
    
    # Topics
    if exam.topics:
        elements.append(Paragraph("Topics to Cover", heading_style))
        elements.append(Paragraph(exam.topics, normal_style))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=exam_{id}_details.pdf'
    
    return response


@app.route("/download-all-pdf/<service_type>")
@admin_login_required
def download_all_pdf(service_type):
    if service_type == "assignments":
        items = Assignment.query.order_by(Assignment.due_date.desc()).all()
        title = "All Assignments Report"
        filename = "all_assignments_report.pdf"
    elif service_type == "quizzes":
        items = QuizRequest.query.order_by(QuizRequest.test_date.desc()).all()
        title = "All Quizzes Report"
        filename = "all_quizzes_report.pdf"
    elif service_type == "exams":
        items = ExamRequest.query.order_by(ExamRequest.exam_date.desc()).all()
        title = "All Exams Report"
        filename = "all_exams_report.pdf"
    else:
        abort(404)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=1,  # Center alignment
        spaceAfter=20
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=10,
        spaceAfter=6,
        spaceBefore=12
    )
    
    # Title
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Create table data
    if service_type == "assignments":
        table_data = [["ID", "Name", "Subject", "Due Date", "Status", "Created"]]
        for item in items:
            table_data.append([
                str(item.id),
                item.name[:20] + "..." if len(item.name) > 20 else item.name,
                item.subject[:15] + "..." if len(item.subject) > 15 else item.subject,
                item.due_date.strftime('%Y-%m-%d'),
                item.status,
                item.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
    else:
        table_data = [["ID", "Name", "Subject", "Date", "Status", "Created"]]
        date_field = "test_date" if service_type == "quizzes" else "exam_date"
        for item in items:
            table_data.append([
                str(item.id),
                item.name[:20] + "..." if len(item.name) > 20 else item.name,
                item.subject[:15] + "..." if len(item.subject) > 15 else item.subject,
                getattr(item, date_field).strftime('%Y-%m-%d'),
                item.status,
                item.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
    
    # Create table
    table = Table(table_data, colWidths=[0.5*inch, 1.5*inch, 1.5*inch, 1*inch, 1.2*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    # Summary
    status_count = {}
    for item in items:
        status_count[item.status] = status_count.get(item.status, 0) + 1
    
    elements.append(Paragraph("Summary", heading_style))
    for status, count in status_count.items():
        elements.append(Paragraph(f"{status}: {count} requests", styles['Normal']))
    
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"Total Requests: {len(items)}", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        
        # Use the Admin model instead of raw SQL
        admin = Admin.query.filter_by(username=username, password=password).first()
        
        if admin:
            session["admin_id"] = admin.id
            session["username"] = admin.username
            flash("Logged in successfully!", "success")
            return redirect(url_for("dashboard"))
        
        flash("Invalid username or password", "danger")
    
    return render_template("login.html")


@app.route("/dashboard")
@admin_login_required
def dashboard():
    from datetime import date
    import os
    
    # Get today's date
    today = date.today()
    
    # Get all records ordered by date
    assignments = Assignment.query.order_by(Assignment.due_date.desc()).all()
    quizzes = QuizRequest.query.order_by(QuizRequest.test_date.desc()).all()
    exams = ExamRequest.query.order_by(ExamRequest.exam_date.desc()).all()
    
    # Add file existence info to each record
    for a in assignments:
        a.assignment_file_exists = False
        a.payment_file_exists = False
        
        if a.assignment_file:
            file_path = os.path.join("static/uploads/assignments", a.assignment_file)
            a.assignment_file_exists = os.path.exists(file_path)
        
        if a.proof_of_payment:
            payment_path = os.path.join("static/uploads/payments", a.proof_of_payment)
            a.payment_file_exists = os.path.exists(payment_path)
    
    for q in quizzes:
        q.quiz_file_exists = False
        q.payment_file_exists = False
        
        if q.quiz_file:
            file_path = os.path.join("static/uploads/quizzes", q.quiz_file)
            q.quiz_file_exists = os.path.exists(file_path)
        
        if q.proof_of_payment:
            payment_path = os.path.join("static/uploads/payments", q.proof_of_payment)
            q.payment_file_exists = os.path.exists(payment_path)
    
    for e in exams:
        e.exam_file_exists = False
        e.payment_file_exists = False
        
        if e.exam_file:
            file_path = os.path.join("static/uploads/exams", e.exam_file)
            e.exam_file_exists = os.path.exists(file_path)
        
        if e.proof_of_payment:
            payment_path = os.path.join("static/uploads/payments", e.proof_of_payment)
            e.payment_file_exists = os.path.exists(payment_path)
    
    # Count active (not expired) records
    active_assignments_count = Assignment.query.filter(
        Assignment.due_date >= today
    ).count()
    
    active_quizzes_count = QuizRequest.query.filter(
        QuizRequest.test_date >= today
    ).count()
    
    active_exams_count = ExamRequest.query.filter(
        ExamRequest.exam_date >= today
    ).count()
    
    # Statistics for dashboard
    stats = {
        'total_assignments': len(assignments),
        'total_quizzes': len(quizzes),
        'total_exams': len(exams),
        'pending_payments': Assignment.query.filter_by(status="Pending Payment").count() +
                           QuizRequest.query.filter_by(status="Pending Payment").count() +
                           ExamRequest.query.filter_by(status="Pending Payment").count(),
        'active_assignments': active_assignments_count,
        'active_quizzes': active_quizzes_count,
        'active_exams': active_exams_count,
        'total_active': active_assignments_count + active_quizzes_count + active_exams_count,
        'total_expired': (len(assignments) + len(quizzes) + len(exams)) - 
                        (active_assignments_count + active_quizzes_count + active_exams_count)
    }
    
    return render_template("dashboard.html",
                           assignments=assignments,
                           quizzes=quizzes,
                           exams=exams,
                           today=today,
                           stats=stats)


@app.route("/assignment-assistance")
def assignment_assistance():
    return render_template("assignment_assistance.html")


@app.route("/submit-assignment", methods=["POST"])
def submit_assignment():
    file = request.files.get("file")
    filename = None
    
    if file and file.filename and allowed_file(file.filename):
        os.makedirs("static/uploads/assignments", exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(f"static/uploads/assignments/{filename}")
    
    assignment = Assignment(
        name=request.form["name"],
        email=request.form["email"],
        contact=request.form["contact"],
        university=request.form["university"],
        assignment_type=request.form["assignment_type"],
        subject=request.form["subject"],
        due_date=datetime.strptime(request.form["due_date"], "%Y-%m-%d").date(),
        details=request.form["details"],
        assignment_file=filename
    )
    
    db.session.add(assignment)
    db.session.commit()
    
    # Store assignment ID in session
    session["assignment_id"] = assignment.id
    session["service_type"] = "Assignment Assistance"
    session["request_time"] = datetime.now().isoformat()
    
    flash("Assignment submitted successfully! Please proceed to payment.", "success")
    return redirect(url_for("payment"))


@app.route("/payment")
def payment():
    return render_template("payment.html")


@app.route("/upload-proof", methods=["POST"])
def upload_proof():
    proof = request.files.get("proof")
    filename = None
    
    if proof and proof.filename and allowed_file(proof.filename):
        os.makedirs("static/uploads/payments", exist_ok=True)
        filename = secure_filename(proof.filename)
        proof.save(os.path.join("static/uploads/payments", filename))
    
    service_type = session.get("service_type", "Assignment Assistance")
    
    if service_type == "Quiz Assistance":
        quiz_id = session.get("quiz_id")
        if quiz_id:
            quiz = QuizRequest.query.get_or_404(quiz_id)
            quiz.proof_of_payment = filename
            quiz.status = "Payment Submitted"
            db.session.commit()
            flash("Payment proof uploaded successfully!", "success")
    
    elif service_type == "Exam Assistance":
        exam_id = session.get("exam_id")
        if exam_id:
            exam = ExamRequest.query.get_or_404(exam_id)
            exam.proof_of_payment = filename
            exam.status = "Payment Submitted"
            db.session.commit()
            flash("Payment proof uploaded successfully!", "success")
    
    else:  # Assignment Assistance
        assignment_id = session.get("assignment_id")
        if assignment_id:
            assignment = Assignment.query.get_or_404(assignment_id)
            assignment.proof_of_payment = filename
            assignment.status = "Payment Submitted"
            db.session.commit()
            flash("Payment proof uploaded successfully!", "success")
    
    session["payment_time"] = datetime.now().isoformat()
    
    return redirect(url_for("queue_tracking"))


@app.route("/queue-tracking")
def queue_tracking():
    if 'request_id' not in session:
        request_id = f"AA-{datetime.now().strftime('%Y%m%d')}-{os.urandom(3).hex()[:6].upper()}"
        session['request_id'] = request_id
    
    if 'request_time' in session:
        request_time = datetime.fromisoformat(session['request_time'])
    else:
        request_time = datetime.now()
    
    if 'payment_time' in session:
        payment_time = datetime.fromisoformat(session['payment_time'])
    else:
        payment_time = datetime.now()
    
    estimated_start = payment_time + timedelta(hours=2)
    estimated_completion = estimated_start + timedelta(hours=24)
    
    return render_template(
        "queue_tracking.html",
        request_id=session['request_id'],
        request_time=request_time,
        payment_time=payment_time,
        estimated_start=estimated_start,
        estimated_completion=estimated_completion
    )


@app.route("/quiz-assistance")
def quiz_assistance():
    return render_template("quiz_assistance.html")


@app.route("/exam-assistance")
def exam_assistance():
    return render_template("exam_assistance.html")


@app.route("/submit-exam", methods=["POST"])
def submit_exam():
    file = request.files.get("file")
    filename = None
    
    if file and file.filename and allowed_file(file.filename):
        os.makedirs("static/uploads/exams", exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(f"static/uploads/exams/{filename}")
    
    exam = ExamRequest(
        name=request.form["name"],
        email=request.form["email"],
        contact=request.form["contact"],
        university=request.form["university"],
        subject=request.form["subject"],
        exam_type=request.form["exam_type"],
        exam_date=datetime.strptime(request.form["exam_date"], "%Y-%m-%d").date(),
        topics=request.form.get("topics"),
        exam_file=filename
    )
    
    db.session.add(exam)
    db.session.commit()
    
    session["exam_id"] = exam.id
    session["service_type"] = "Exam Assistance"
    session["request_time"] = datetime.now().isoformat()
    
    flash("Exam request submitted successfully! Please proceed to payment.", "success")
    return redirect(url_for("payment"))


@app.route("/submit-quiz", methods=["POST"])
def submit_quiz():
    file = request.files.get("file")
    filename = None
    
    if file and file.filename and allowed_file(file.filename):
        os.makedirs("static/uploads/quizzes", exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(f"static/uploads/quizzes/{filename}")
    
    quiz = QuizRequest(
        name=request.form.get("name"),
        email=request.form.get("email"),
        contact=request.form.get("contact"),
        university=request.form.get("university"),
        subject=request.form.get("subject"),
        quiz_type=request.form.get("quiz_type"),
        test_date=datetime.strptime(request.form.get("test_date"), "%Y-%m-%d").date(),
        topics=request.form.get("topics"),
        quiz_file=filename
    )
    
    db.session.add(quiz)
    db.session.commit()
    
    session["quiz_id"] = quiz.id
    session["service_type"] = "Quiz Assistance"
    session["request_time"] = datetime.now().isoformat()
    
    flash("Quiz request submitted successfully! Please proceed to payment.", "success")
    return redirect(url_for("payment"))


@app.route("/update-status/<service>/<int:id>", methods=["POST"])
@admin_login_required
def update_status(service, id):
    new_status = request.form.get("status")
    
    if service == "assignment":
        item = Assignment.query.get_or_404(id)
    elif service == "quiz":
        item = QuizRequest.query.get_or_404(id)
    elif service == "exam":
        item = ExamRequest.query.get_or_404(id)
    else:
        abort(404)
    
    if new_status:
        item.status = new_status
    
    db.session.commit()
    
    flash(f"{service.capitalize()} status updated successfully!", "success")
    return redirect(url_for("dashboard"))


@app.route("/delete/<service>/<int:id>", methods=["POST"])
@admin_login_required
def delete_record(service, id):
    if service == "assignment":
        item = Assignment.query.get_or_404(id)
    elif service == "quiz":
        item = QuizRequest.query.get_or_404(id)
    elif service == "exam":
        item = ExamRequest.query.get_or_404(id)
    else:
        abort(404)
    
    db.session.delete(item)
    db.session.commit()
    
    flash(f"{service.capitalize()} deleted successfully!", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# Create admin user if doesn't exist
def create_default_admin():
    with app.app_context():
        admin_exists = Admin.query.filter_by(username="admin").first()
        if not admin_exists:
            default_admin = Admin(username="admin", password="admin123")
            db.session.add(default_admin)
            db.session.commit()
            print("Default admin created: username='admin', password='admin123'")


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page Not Found</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                color: white;
            }
            h1 {
                font-size: 3em;
                margin-bottom: 20px;
            }
            a {
                color: #4cc9f0;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>404 - Page Not Found</h1>
        <p>The requested resource could not be found.</p>
        <p><a href="/dashboard">Return to Dashboard</a></p>
    </body>
    </html>
    """, 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Internal Server Error</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
                color: white;
            }
            h1 {
                font-size: 3em;
                margin-bottom: 20px;
            }
            a {
                color: #4cc9f0;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>500 - Internal Server Error</h1>
        <p>Something went wrong on our end. Please try again later.</p>
        <p><a href="/dashboard">Return to Dashboard</a></p>
    </body>
    </html>
    """, 500


# Create database tables and default admin
with app.app_context():
    db.create_all()
    create_default_admin()


if __name__ == "__main__":
    # Create upload directories if they don't exist
    upload_dirs = [
        "static/uploads/assignments",
        "static/uploads/quizzes", 
        "static/uploads/exams",
        "static/uploads/payments"
    ]
    
    for directory in upload_dirs:
        os.makedirs(directory, exist_ok=True)
        print(f"✓ Directory created/verified: {directory}")
    
  
    
    app.run(debug=True, host='0.0.0.0', port=5000)
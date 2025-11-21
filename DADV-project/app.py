import os
import cv2
import sqlite3
import mediapipe as mp
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from fpdf import FPDF

# ------------------- APP CONFIG -------------------
app = Flask(__name__)
app.secret_key = "vyorix_secret_key"

UPLOAD_FOLDER = os.path.join("static", "uploads")
RESULT_FOLDER = os.path.join("static", "results")
PDF_FOLDER = os.path.join("static", "pdfs")

for folder in [UPLOAD_FOLDER, RESULT_FOLDER, PDF_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["RESULT_FOLDER"] = RESULT_FOLDER
app.config["PDF_FOLDER"] = PDF_FOLDER

# ------------------- MEDIAPIPE SETUP -------------------
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

@app.route("/")
def title():
    return render_template("title.html")

# ------------------- ROUTES -------------------
@app.route("/index")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect(url_for("pose"))
        else:
            flash("Invalid username or password", "danger")
            return render_template("login.html")

    return render_template("login.html")


@app.route("/index")
def index():
    return render_template("index.html")

@app.route("/pose")
def pose():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("pose_backend.html")


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


# ------------------- POSE BACKEND -------------------
@app.route("/pose_backend", methods=["GET", "POST"])
def pose_backend():
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            return render_template("pose_backend.html", message="⚠️ Please upload a file.")

        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()

        if file_ext not in [".jpg", ".jpeg", ".png", ".mp4"]:
            return render_template("pose_backend.html", message="⚠️ Unsupported file type.")

        upload_path = os.path.join(UPLOAD_FOLDER, filename)
        result_filename = f"pose_{filename}"
        result_path = os.path.join(RESULT_FOLDER, result_filename)
        file.save(upload_path)

        # ---------- IMAGE PROCESS ----------
        if file_ext in [".jpg", ".jpeg", ".png"]:
            img = cv2.imread(upload_path)
            if img is None:
                return render_template("pose_backend.html", message="⚠️ Failed to read image file.")
            
            with mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5) as pose_model:
                results = pose_model.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                if results.pose_landmarks:
                    mp_drawing.draw_landmarks(img, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
            cv2.imwrite(result_path, img)

            # Generate PDF
            pdf_filename = filename.rsplit(".", 1)[0] + "_pose.pdf"
            pdf_path = os.path.join(PDF_FOLDER, pdf_filename)
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=14)
            pdf.cell(200, 10, txt="Pose Estimation Report", ln=True, align="C")
            pdf.image(result_path, x=30, y=40, w=150)
            current_y = pdf.get_y() + 160
            pdf.set_y(current_y + 160)
            pdf.set_font("Arial", size=12)

            # ----- Explanation -----
            pdf.multi_cell(
                0, 8,
                "The green and red dotted points represent pose landmarks detected by MediaPipe. "
                "These landmarks show major body joints such as the shoulders, elbows, wrists, hips, "
                "knees, and ankles. Green lines indicate body connections that form the posture shape."
            )

            pdf.ln(4)

            # ----- Legend Box -----
            pdf.set_font("Arial", size=12)
            pdf.cell(0, 8, "Legend:", ln=True)

            pdf.set_font("Arial", size=11)
            pdf.multi_cell(
                0, 6,
                "-> Green circles/lines : Body connections & detected joints\n"
                "-> Red circles        : Critical joint positions\n"
            )

            pdf.ln(4)

            # ----- Joint Table -----
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Main Body Joints Detected:", ln=True)

            pdf.set_font("Arial", size=11)
            pdf.multi_cell(
                0, 6,
                "-> Nose, Eyes, Ears\n"
                "-> Shoulders (Left & Right)\n"
                "-> Elbows (Left & Right)\n"
                "-> Wrists (Left & Right)\n"
                "-> Hips (Left & Right)\n"
                "-> Knees (Left & Right)\n"
                "-> Ankles (Left & Right)"
)

            pdf.output(pdf_path)

            return render_template(
                "pose_backend.html",
                result_img=result_filename,
                input_img=filename,
                pdf_path_img=pdf_filename,
                result_vid=None,
                input_vid=None,
                pdf_path_vid=None,
                message="✅ Image processed successfully!"
            )

        # ---------- VIDEO PROCESS ----------
        elif file_ext == ".mp4":
            cap = cv2.VideoCapture(upload_path)
            if not cap.isOpened():
                return render_template("pose_backend.html", message="⚠️ Cannot open video file.")

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # ✅ Browser-friendly codec
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 120:
                fps = 25
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            result_path_temp = os.path.join(RESULT_FOLDER, f"temp_{filename}")
            out = cv2.VideoWriter(result_path_temp, fourcc, fps, (width, height))

            frame_count = 0
            with mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose_model:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = pose_model.process(frame_rgb)

                    if results.pose_landmarks:
                        mp_drawing.draw_landmarks(
                            frame,
                            results.pose_landmarks,
                            mp_pose.POSE_CONNECTIONS,
                            mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
                            mp_drawing.DrawingSpec(color=(255, 0, 0), thickness=2)
                        )

                    out.write(frame)
                    frame_count += 1

            cap.release()
            out.release()

            # --- ADD THIS FFmpeg FIX ---
            import subprocess
            final_output = result_path
            cmd = [
                "ffmpeg", "-y",
                "-i", result_path_temp,
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                final_output
            ]
            subprocess.run(cmd)
        
            

            # ✅ Delete temp file 
            if os.path.exists(result_path_temp): 
                os.remove(result_path_temp)

                print(f"✅ Video processed: {frame_count} frames  → {final_output}")
            

            # Generate PDF
            pdf_filename = filename.rsplit(".", 1)[0] + "_pose.pdf"
            pdf_path = os.path.join(PDF_FOLDER, pdf_filename)
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=14)
            pdf.cell(200, 10, txt="Pose Estimation Video Report", ln=True, align="C")
            pdf.cell(200, 10, txt=f"Processed video: {result_filename}", ln=True)
            pdf.ln(10)
            pdf.set_font("Arial", size=12)

            # ----- Explanation -----
            pdf.multi_cell(
                0, 8,
                "The green and red dotted points represent pose landmarks detected frame-by-frame "
                "using MediaPipe. These landmarks show major joints like shoulders, elbows, wrists, "
                "hips, knees, and ankles. The drawing lines represent body posture in motion."
            )

            pdf.ln(4)

            # ----- Legend Box -----
            pdf.set_font("Arial", size=12)
            pdf.cell(0, 8, "Legend:", ln=True)

            pdf.set_font("Arial", size=11)
            pdf.multi_cell(
                0, 6,
                "* Green circles/lines : Body connections across frames\n"
                "* Red circles        : Critical joint positions\n"
            )

            pdf.ln(4)

            # ----- Joint Table -----
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Main Body Joints Detected:", ln=True)

            pdf.set_font("Arial", size=11)
            pdf.multi_cell(
                0, 6,
                "* Nose, Eyes, Ears\n"
                "* Shoulders (Left & Right)\n"
                "* Elbows (Left & Right)\n"
                "* Wrists (Left & Right)\n"
                "* Hips (Left & Right)\n"
                "* Knees (Left & Right)\n"
                "* Ankles (Left & Right)"
            )

            pdf.output(pdf_path)

            return render_template(
                "pose_backend.html",
                result_vid=result_filename,
                input_vid=filename,
                pdf_path_vid=pdf_filename,
                result_img=None,
                input_img=None,
                pdf_path_img=None,
                message=f"✅ Video processed successfully! ({frame_count} frames)"
            )

    return render_template("pose_backend.html", message=None)


# ------------------- FILE DOWNLOAD -------------------
@app.route("/download/<filename>")
def download_file(filename):
    for folder in [RESULT_FOLDER, PDF_FOLDER]:
        file_path = os.path.join(folder, filename)
        if os.path.exists(file_path):
            return send_from_directory(folder, filename, as_attachment=True)
    return "File not found", 404


# ------------------- MAIN -------------------
if __name__ == "__main__":
    app.run(debug=True)

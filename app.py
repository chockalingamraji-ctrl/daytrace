
import hashlib
import io
import json
import uuid
import calendar
import os
import tempfile
import urllib.request

from datetime import date, datetime, time

import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from supabase import create_client
from fpdf import FPDF


# ---------- Page setup and Supabase connection ----------

st.set_page_config(
    page_title="DayTrace",
    page_icon="📘",
    layout="wide",
)

try:
    supabase = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )

    supabase.table("daily_records").select("id").limit(1).execute()

except Exception as e:
    st.error(f"Supabase connection failed: {e}")
    st.stop()


WHOLE_DAY = "Whole day"

TIME_SLOTS = [
    "8:20–8:50 AM", "8:50–9:20 AM", "9:20–9:50 AM",
    "9:50–10:20 AM", "10:20–10:50 AM", "10:50–11:20 AM",
    "11:20–11:50 AM", "11:50 AM–12:20 PM", "12:20–12:50 PM",
    "12:50–1:20 PM", "1:20–1:50 PM", "1:50–2:20 PM",
    "2:20–2:50 PM", "2:50–3:20 PM", "3:20–3:50 PM",
    "3:50–4:20 PM", "4:20–4:40 PM",
]

ACTIVITIES = [
    "Teaching", "Lesson Planning", "Correction / Assessment",
    "Classroom Preparation", "Meetings", "Student Support",
    "Administrative Work", "Parent Communication",
    "English training for teachers", "Training", "Staff record",
    "Workbook correction", "Preparing progress report",
    "Progress report writing", "Break", "Other School Duty",
]

TEACHING_SUBJECTS = [
    "Language", "Math", "GA", "Flip/Tamil", "School Cinema",
    "Water play", "Art", "Activity", "Outdoor play",
    "Material play/computer science", "Story/computer science",
]


# ---------- Supabase database functions ----------

def load_data():
    """Load all activity records, including records beyond the first 1,000."""

    records = []
    page_size = 1000
    start = 0

    while True:
        response = (
            supabase.table("daily_records")
            .select("*")
            .order("activity_date")
            .range(start, start + page_size - 1)
            .execute()
        )

        rows = response.data or []

        for r in rows:
            records.append({
                "id": r["id"],
                "date": r["activity_date"],
                "teacher": r["teacher"],
                "time": r.get("time_slot") or "",
                "activity": r["activity"],
                "reviewed": r.get("reviewed", False),
                "reviewed_at": r.get("reviewed_at"),
            })

        if len(rows) < page_size:
            break

        start += page_size

    return {
        "daily_records": records,
        "reviewed_slots": {},
    }


def save_record(record):
    """Insert one activity into Supabase."""

    supabase.table("daily_records").insert({
        "teacher": record["teacher"],
        "activity": record["activity"],
        "activity_date": record["date"],
        "time_slot": record.get("time", ""),
        "reviewed": record.get("reviewed", False),
        "reviewed_at": record.get("reviewed_at"),
    }).execute()


def update_record(record):
    """Update the review status of one activity."""

    supabase.table("daily_records").update({
        "reviewed": record.get("reviewed", False),
        "reviewed_at": record.get("reviewed_at"),
    }).eq("id", record["id"]).execute()


def delete_record(record_id):
    """Delete one activity."""

    supabase.table("daily_records").delete().eq(
        "id", record_id
    ).execute()


def delete_all_records():
    """Delete all activity records."""

    supabase.table("daily_records").delete().neq(
        "id", "00000000-0000-0000-0000-000000000000"
    ).execute()


def restore_backup(restored_data):
    """Validate and restore a DayTrace JSON backup."""

    if not isinstance(restored_data, dict):
        raise ValueError("The backup must contain a JSON object.")

    records = restored_data.get("daily_records")

    if not isinstance(records, list):
        raise ValueError("The backup does not contain a valid activity list.")

    rows_to_restore = []

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("An activity record is invalid.")

        teacher = str(record.get("teacher", "")).strip()
        activity = str(record.get("activity", "")).strip()
        record_date = str(record.get("date", "")).strip()

        if not teacher or not activity or not record_date:
            raise ValueError("A record is missing required information.")

        date.fromisoformat(record_date)

        record_id = record.get("id") or str(uuid.uuid4())
        uuid.UUID(str(record_id))

        rows_to_restore.append({
            "id": str(record_id),
            "teacher": teacher,
            "activity": activity,
            "activity_date": record_date,
            "time_slot": str(record.get("time") or ""),
            "reviewed": bool(record.get("reviewed", False)),
            "reviewed_at": record.get("reviewed_at"),
        })

    delete_all_records()

    batch_size = 500

    for start in range(0, len(rows_to_restore), batch_size):
        batch = rows_to_restore[start:start + batch_size]

        if batch:
            supabase.table("daily_records").insert(batch).execute()


# ---------- Supabase Storage: monthly reports ----------

def upload_monthly_report(path, pdf_bytes):
    """Upload a new PDF to the private monthly-reports bucket."""

    return (
        supabase.storage
        .from_("monthly-reports")
        .upload(
            path=path,
            file=pdf_bytes,
            file_options={
                "content-type": "application/pdf",
                "upsert": "false",
            },
        )
    )


def list_monthly_reports(folder):
    """List saved PDF reports inside a month folder."""

    return (
        supabase.storage
        .from_("monthly-reports")
        .list(
            folder,
            {
                "limit": 1000,
                "offset": 0,
                "sortBy": {
                    "column": "name",
                    "order": "desc",
                },
            },
        )
    ) or []


def download_monthly_report(path):
    """Download a PDF from the private bucket."""

    return (
        supabase.storage
        .from_("monthly-reports")
        .download(path)
    )


# ---------- Tamil font for PDF reports ----------

def get_tamil_font_path():
    """
    Download Noto Sans Tamil and create a static font file
    for reliable Tamil text rendering in the PDF.
    """

    font_path = os.path.join(
        tempfile.gettempdir(),
        "daytrace_noto_sans_tamil.ttf",
    )

    if os.path.exists(font_path) and os.path.getsize(font_path) > 50000:
        return font_path

    font_url = (
        "https://raw.githubusercontent.com/google/fonts/main/"
        "ofl/notosanstamil/NotoSansTamil%5Bwdth%2Cwght%5D.ttf"
    )

    request = urllib.request.Request(
        font_url,
        headers={"User-Agent": "DayTrace"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        font_bytes = response.read()

    if len(font_bytes) < 50000:
        raise RuntimeError("The Tamil font could not be downloaded correctly.")

    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font = TTFont(io.BytesIO(font_bytes))

    if "fvar" in font:
        axis_values = {}

        for axis in font["fvar"].axes:
            if axis.axisTag == "wght":
                axis_values["wght"] = min(
                    max(400, axis.minValue),
                    axis.maxValue,
                )

            elif axis.axisTag == "wdth":
                axis_values["wdth"] = min(
                    max(100, axis.minValue),
                    axis.maxValue,
                )

        if axis_values:
            font = instantiateVariableFont(
                font,
                axis_values,
                inplace=True,
            )

    font.save(font_path)

    return font_path


# ---------- PDF generation ----------

class MonthlyReportPDF(FPDF):

    def footer(self):
        self.set_y(-12)
        self.set_font("DayTraceTamil", size=8)
        self.set_text_color(100, 116, 139)

        self.cell(
            0,
            8,
            text=f"Page {self.page_no()}",
            align="R",
        )


def create_monthly_pdf(records, month_number, year):
    """Create a teacher-wise monthly PDF report."""

    font_path = get_tamil_font_path()

    pdf = MonthlyReportPDF(
        orientation="P",
        unit="mm",
        format="A4",
    )

    pdf.set_margins(15, 18, 15)
    pdf.set_auto_page_break(auto=True, margin=18)

    pdf.add_font(
        family="DayTraceTamil",
        fname=font_path,
    )

    # HarfBuzz shaping is required for correct Indic-script rendering.
    pdf.set_text_shaping(use_shaping_engine=True)

    pdf.add_page()

    month_name = calendar.month_name[month_number]

    total = len(records)
    reviewed = sum(1 for r in records if r.get("reviewed"))
    pending = total - reviewed

    teacher_groups = {}

    for record in records:
        teacher = clean_name(
            record.get("teacher", "Unknown teacher")
        ) or "Unknown teacher"

        teacher_groups.setdefault(teacher, []).append(record)

    pdf.set_text_color(79, 70, 229)
    pdf.set_font("DayTraceTamil", size=19)
    pdf.multi_cell(0, 10, text="DayTrace")

    pdf.set_text_color(30, 41, 59)
    pdf.set_font("DayTraceTamil", size=14)
    pdf.multi_cell(
        0,
        8,
        text="Monthly Teacher Activity Report",
    )

    pdf.set_text_color(71, 85, 105)
    pdf.set_font("DayTraceTamil", size=10)

    pdf.multi_cell(
        0,
        7,
        text=f"Reporting month: {month_name} {year}",
    )

    pdf.multi_cell(
        0,
        7,
        text=(
            "Generated on: "
            + datetime.now().strftime("%d %b %Y, %I:%M %p")
        ),
    )

    pdf.ln(3)

    pdf.set_text_color(30, 41, 59)
    pdf.set_font("DayTraceTamil", size=11)

    pdf.multi_cell(
        0,
        7,
        text=f"Teachers: {len(teacher_groups)}",
    )

    pdf.multi_cell(
        0,
        7,
        text=f"Total activities: {total}",
    )

    pdf.multi_cell(
        0,
        7,
        text=f"Reviewed: {reviewed}",
    )

    pdf.multi_cell(
        0,
        7,
        text=f"Pending review: {pending}",
    )

    pdf.ln(4)

    if not records:
        pdf.set_font("DayTraceTamil", size=11)
        pdf.multi_cell(
            0,
            7,
            text="No activities were recorded during this month.",
        )

    for teacher in sorted(teacher_groups, key=str.casefold):

        items = teacher_groups[teacher]

        teacher_reviewed = sum(
            1 for r in items if r.get("reviewed")
        )

        teacher_pending = len(items) - teacher_reviewed

        pdf.set_text_color(79, 70, 229)
        pdf.set_font("DayTraceTamil", size=13)

        pdf.multi_cell(
            0,
            8,
            text=teacher,
        )

        pdf.set_text_color(71, 85, 105)
        pdf.set_font("DayTraceTamil", size=9)

        pdf.multi_cell(
            0,
            6,
            text=(
                f"Activities: {len(items)} | "
                f"Reviewed: {teacher_reviewed} | "
                f"Pending: {teacher_pending}"
            ),
        )

        items = sorted(
            items,
            key=lambda r: (
                r.get("date", ""),
                r.get("time", ""),
            ),
        )

        for record in items:

            try:
                record_date = date.fromisoformat(
                    record.get("date", "")
                ).strftime("%d %b %Y")
            except ValueError:
                record_date = record.get("date", "")

            time_slot = record.get("time") or "Time not specified"
            activity = record.get("activity", "")
            status = (
                "Reviewed"
                if record.get("reviewed")
                else "Pending review"
            )

            pdf.set_text_color(30, 41, 59)
            pdf.set_font("DayTraceTamil", size=9)

            pdf.multi_cell(
                0,
                6,
                text=(
                    f"{record_date} | {time_slot}\n"
                    f"Activity: {activity}\n"
                    f"Status: {status}"
                ),
            )

            pdf.ln(2)

        pdf.ln(3)

    return bytes(pdf.output())


# ---------- Load records ----------

try:
    data = load_data()

except Exception as e:
    st.error(f"Could not load activity records: {e}")
    st.stop()


# ---------- Helpers ----------

def fmt_time(t):
    return t.strftime("%I:%M %p").lstrip("0")


def clean_name(name):
    return " ".join(name.split())


def same_person(a, b):
    return clean_name(a).casefold() == clean_name(b).casefold()


def section_head_passcode():
    try:
        return st.secrets["SECTION_HEAD_PASSCODE"]
    except Exception:
        return None


def transcribe_audio(audio_bytes, language_code):
    """Convert a recorded voice note into text."""

    recognizer = sr.Recognizer()

    with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
        audio_data = recognizer.record(source)

    return recognizer.recognize_google(
        audio_data,
        language=language_code,
    )


# ---------- Header ----------

st.markdown("""
<style>
.hero {
    background: linear-gradient(120deg, #4f46e5, #8b5cf6);
    padding: 26px;
    border-radius: 18px;
    color: white;
}
.hero h1, .hero p {
    color: white;
}
</style>

<div class="hero">
    <h1>📘 DayTrace</h1>
    <p>Your school day, organised and reviewed.</p>
</div>
""", unsafe_allow_html=True)


# ---------- Sidebar: role, name and date ----------

role = st.sidebar.radio(
    "I am a",
    ["Teacher", "Section Head"],
)

is_head = False
teacher_name = ""

if role == "Teacher":

    teacher_name = clean_name(
        st.sidebar.text_input("👤 Your name")
    )

else:

    expected = section_head_passcode()

    if expected is None:
        st.sidebar.error(
            "SECTION_HEAD_PASSCODE is missing. "
            "Please configure it in Secrets."
        )
        st.stop()

    entered = st.sidebar.text_input(
        "🔑 Section head passcode",
        type="password",
    )

    if entered == expected:
        is_head = True

    elif entered:
        st.sidebar.error("Wrong passcode.")


work_date = st.sidebar.date_input(
    "📅 Select workday",
    date.today(),
)

selected_date = work_date.isoformat()

day_records = [
    r for r in data["daily_records"]
    if r.get("date") == selected_date
]


# ==========================================================
# TEACHER VIEW
# ==========================================================

if role == "Teacher":

    if not teacher_name:
        st.info("Enter your name in the sidebar to start recording.")
        st.stop()

    mine = [
        r for r in day_records
        if same_person(r.get("teacher", ""), teacher_name)
    ]

    mine_reviewed = sum(
        1 for r in mine if r.get("reviewed")
    )

    a, b, c = st.columns(3)

    a.metric("My activities", len(mine))
    b.metric("Reviewed by section head", mine_reviewed)
    c.metric("Waiting for review", len(mine) - mine_reviewed)

    tab1, tab2 = st.tabs([
        "✍️ Record Activity",
        "🗓️ My Timeline",
    ])

    # ---------- Record Activity tab ----------

    with tab1:

        st.subheader("Record a school activity")

        mode = st.radio(
            "How do you want to enter the time?",
            ["Choose a slot", "Enter my own time", WHOLE_DAY],
            horizontal=True,
        )

        activity = st.selectbox(
            "Activity",
            ACTIVITIES,
        )

        subject = None

        if activity == "Teaching":

            subject = st.selectbox(
                "Teaching subject",
                TEACHING_SUBJECTS,
            )

        # ---------- Voice input ----------

        st.write("🎤 Voice input")

        voice_language = st.selectbox(
            "Choose the language for voice transcription",
            {
                "English": "en-IN",
                "Tamil": "ta-IN",
            },
        )

        audio = mic_recorder(
            start_prompt="Start Recording",
            stop_prompt="Stop Recording",
            key="voice_note",
        )

        if audio and audio.get("bytes"):

            audio_bytes = audio["bytes"]

            audio_hash = hashlib.sha256(
                audio_bytes
            ).hexdigest()

            language_code = {
                "English": "en-IN",
                "Tamil": "ta-IN",
            }[voice_language]

            transcription_id = (
                audio_hash + language_code
            )

            if st.session_state.get("last_transcription_id") != transcription_id:

                try:
                    with st.spinner("Transcribing your voice note..."):

                        transcript = transcribe_audio(
                            audio_bytes,
                            language_code,
                        )

                    previous_text = st.session_state.get(
                        "activity_description",
                        "",
                    ).strip()

                    if previous_text:
                        st.session_state["activity_description"] = (
                            previous_text + " " + transcript
                        )

                    else:
                        st.session_state["activity_description"] = transcript

                    st.session_state["last_transcription_id"] = (
                        transcription_id
                    )

                    st.success(
                        "Voice transcription added to the description."
                    )

                except sr.UnknownValueError:
                    st.warning(
                        "The recording could not be understood. "
                        "Please try recording again."
                    )

                except sr.RequestError:
                    st.error(
                        "The transcription service is unavailable. "
                        "Please check the internet connection and try again."
                    )

                except Exception as e:
                    st.error(f"Voice transcription failed: {e}")

        description = st.text_input(
            "Description (optional)",
            key="activity_description",
        )

        # ---------- Activity form ----------

        with st.form("activity_form", clear_on_submit=True):

            slot = None
            start = None
            end = None

            if mode == "Choose a slot":

                slot = st.selectbox(
                    "Time slot",
                    TIME_SLOTS,
                )

            elif mode == "Enter my own time":

                col1, col2 = st.columns(2)

                start = col1.time_input(
                    "From",
                    value=time(8, 20),
                    step=300,
                )

                end = col2.time_input(
                    "To",
                    value=time(8, 50),
                    step=300,
                )

            else:

                st.info(
                    "This activity will be saved for the whole day."
                )

            submitted = st.form_submit_button(
                "Save Activity",
                type="primary",
            )

        if submitted:

            error = None

            if mode == "Enter my own time":

                if end <= start:
                    error = "The end time must be after the start time."

                time_label = (
                    f"{fmt_time(start)}–{fmt_time(end)}"
                )

            elif mode == WHOLE_DAY:

                time_label = WHOLE_DAY

            else:

                time_label = slot

            if subject:
                activity_name = f"Teaching – {subject}"

            else:
                activity_name = activity

            description_text = description.strip()

            if activity == "Other School Duty":

                if not description_text:
                    error = "Please describe the other school duty."

                else:
                    activity_name = (
                        f"Other School Duty: {description_text}"
                    )

            elif description_text:

                activity_name += f": {description_text}"

            if error:
                st.warning(error)

            else:

                try:
                    save_record({
                        "date": selected_date,
                        "teacher": teacher_name,
                        "time": time_label,
                        "activity": activity_name,
                        "reviewed": False,
                    })

                    st.session_state["activity_description"] = ""
                    st.session_state.pop("last_transcription_id", None)

                    st.success("Activity saved!")
                    st.rerun()

                except Exception as e:
                    st.error(f"Could not save the activity: {e}")

    # ---------- My Timeline tab ----------

    with tab2:

        st.subheader(f"My Timeline — {selected_date}")

        if not mine:

            st.info(
                "No activities recorded for this date yet."
            )

        else:

            for record in mine:

                with st.container(border=True):

                    status = (
                        "✅ Reviewed"
                        if record.get("reviewed")
                        else "⏳ Not reviewed"
                    )

                    st.markdown(
                        f"**🕒 {record.get('time', '')}** · {status}"
                    )

                    st.write(
                        record.get("activity", "")
                    )

            if st.button(
                "Clear my unreviewed activities for this date"
            ):

                try:
                    for record in mine:
                        if not record.get("reviewed"):
                            delete_record(record["id"])

                    st.success("Unreviewed activities cleared.")
                    st.rerun()

                except Exception as e:
                    st.error(f"Could not clear activities: {e}")


# ==========================================================
# SECTION HEAD VIEW
# ==========================================================

else:

    if not is_head:
        st.info(
            "Enter the section head passcode in the sidebar."
        )
        st.stop()

    total = len(day_records)

    done = sum(
        1 for r in day_records if r.get("reviewed")
    )

    teachers = sorted({
        r.get("teacher", "Unknown teacher")
        for r in day_records
    })

    a, b, c, d = st.columns(4)

    a.metric("Teachers", len(teachers))
    b.metric("Activities recorded", total)
    c.metric("Reviewed", f"{done}/{total}")

    d.metric(
        "Review progress",
        f"{done * 100 // total if total else 0}%",
    )

    st.progress(
        done / total if total else 0.0
    )

    tab1, tab2, tab3 = st.tabs([
        "✅ Review Workday",
        "💾 Backup",
        "📄 Monthly Reports",
    ])

    # ---------- Review Workday tab ----------

    with tab1:

        st.subheader(f"Review — {selected_date}")

        if not day_records:

            st.info(
                "No teacher has recorded activities for this date yet."
            )

        for teacher in teachers:

            items = [
                r for r in day_records
                if r.get("teacher", "Unknown teacher") == teacher
            ]

            n_done = sum(
                1 for r in items if r.get("reviewed")
            )

            with st.expander(
                f"👤 {teacher} — {n_done}/{len(items)} reviewed",
                expanded=n_done < len(items),
            ):

                for r in items:

                    left, right = st.columns([5, 2])

                    with left:

                        st.markdown(
                            f"**🕒 {r.get('time', '')}**"
                        )

                        st.write(
                            r.get("activity", "")
                        )

                    with right:

                        if r.get("reviewed"):

                            st.caption("✅ Reviewed")

                            if st.button(
                                "Undo",
                                key=f"undo_{r['id']}",
                            ):

                                try:
                                    r["reviewed"] = False
                                    r["reviewed_at"] = None

                                    update_record(r)
                                    st.rerun()

                                except Exception as e:
                                    st.error(
                                        f"Could not undo review: {e}"
                                    )

                        else:

                            if st.button(
                                "Mark as reviewed",
                                key=f"rev_{r['id']}",
                                type="primary",
                            ):

                                try:
                                    r["reviewed"] = True

                                    r["reviewed_at"] = (
                                        datetime.now().isoformat(
                                            timespec="seconds"
                                        )
                                    )

                                    update_record(r)
                                    st.rerun()

                                except Exception as e:
                                    st.error(
                                        f"Could not update review: {e}"
                                    )

                    st.divider()

                if n_done < len(items):

                    if st.button(
                        f"Mark all of {teacher}'s activities as reviewed",
                        key=f"all_{selected_date}_{teacher}",
                    ):

                        try:
                            now = datetime.now().isoformat(
                                timespec="seconds"
                            )

                            for r in items:

                                if not r.get("reviewed"):

                                    r["reviewed"] = True
                                    r["reviewed_at"] = now

                                    update_record(r)

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Could not mark all activities as reviewed: {e}"
                            )

    # ---------- Backup tab ----------

    with tab2:

        st.subheader("Backup all teachers' data")

        backup = json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )

        st.download_button(
            "⬇️ Download backup",
            data=backup,
            file_name="daytrace_backup.json",
            mime="application/json",
        )

        st.divider()

        st.subheader("Restore from a backup")

        uploaded = st.file_uploader(
            "Choose a DayTrace JSON backup",
            type=["json"],
        )

        if uploaded is not None:

            if st.button("Restore backup"):

                try:
                    restored = json.load(uploaded)

                    restore_backup(restored)

                    st.success(
                        "Backup restored to Supabase!"
                    )

                    st.rerun()

                except (
                    ValueError,
                    TypeError,
                    AttributeError,
                    json.JSONDecodeError,
                ) as e:

                    st.error(
                        f"Please choose a valid DayTrace backup. Details: {e}"
                    )

                except Exception as e:

                    st.error(
                        f"Could not restore the backup: {e}"
                    )

        st.divider()

        st.subheader("🗑️ Delete all data")

        st.caption(
            "Removes every teacher's entries. "
            "Download a backup first if you want to keep a copy."
        )

        confirm = st.checkbox(
            "Yes, I want to delete everything"
        )

        if st.button(
            "Delete all data",
            disabled=not confirm,
        ):

            try:
                delete_all_records()

                st.success("All data deleted.")
                st.rerun()

            except Exception as e:
                st.error(f"Could not delete data: {e}")

    # ---------- Monthly Reports tab ----------

    with tab3:

        st.subheader("Monthly Teacher Activity Reports")

        st.write(
            "Generate a combined monthly PDF for all teachers. "
            "Reports are saved in your private Supabase Storage bucket."
        )

        available_years = {
            date.today().year
        }

        for record in data["daily_records"]:

            try:
                available_years.add(
                    date.fromisoformat(record["date"]).year
                )

            except (ValueError, TypeError, KeyError):
                pass

        year_options = sorted(
            available_years,
            reverse=True,
        )

        year = st.selectbox(
            "Select year",
            year_options,
            key="monthly_report_year",
        )

        month_options = [
            calendar.month_name[m]
            for m in range(1, 13)
        ]

        month_name = st.selectbox(
            "Select month",
            month_options,
            index=date.today().month - 1,
            key="monthly_report_month",
        )

        month_number = month_options.index(month_name) + 1

        month_folder = f"{year}-{month_number:02d}"

        month_records = []

        for record in data["daily_records"]:

            try:
                record_date = date.fromisoformat(
                    record.get("date", "")
                )

                if (
                    record_date.year == year
                    and record_date.month == month_number
                ):
                    month_records.append(record)

            except (ValueError, TypeError):
                continue

        month_reviewed = sum(
            1 for r in month_records if r.get("reviewed")
        )

        month_pending = len(month_records) - month_reviewed

        m1, m2, m3 = st.columns(3)

        m1.metric(
            "Teachers",
            len({
                clean_name(r.get("teacher", ""))
                for r in month_records
            }),
        )

        m2.metric(
            "Activities",
            len(month_records),
        )

        m3.metric(
            "Pending review",
            month_pending,
        )

        st.divider()

        if not month_records:

            st.info(
                "No activities have been recorded for this month. "
                "You can still download reports saved earlier."
            )

        if st.button(
            "📄 Generate and save monthly PDF",
            type="primary",
            disabled=not month_records,
            key=f"generate_monthly_{month_folder}",
        ):

            try:

                with st.spinner(
                    "Preparing your monthly report..."
                ):

                    pdf_bytes = create_monthly_pdf(
                        month_records,
                        month_number,
                        year,
                    )

                    timestamp = datetime.now().strftime(
                        "%Y%m%d_%H%M%S"
                    )

                    filename = (
                        f"DayTrace_{month_folder}_{timestamp}.pdf"
                    )

                    storage_path = (
                        f"{month_folder}/{filename}"
                    )

                    upload_monthly_report(
                        storage_path,
                        pdf_bytes,
                    )

                    st.session_state["latest_monthly_report"] = {
                        "folder": month_folder,
                        "path": storage_path,
                        "filename": filename,
                        "bytes": pdf_bytes,
                    }

                st.success(
                    "Monthly report generated and saved successfully!"
                )

            except Exception as e:

                st.error(
                    f"Could not generate or save the monthly report: {e}"
                )

        latest_report = st.session_state.get(
            "latest_monthly_report"
        )

        if (
            latest_report
            and latest_report.get("folder") == month_folder
        ):

            st.download_button(
                "⬇️ Download the newly generated PDF",
                data=latest_report["bytes"],
                file_name=latest_report["filename"],
                mime="application/pdf",
                key=f"latest_pdf_{month_folder}",
            )

        st.divider()

        st.subheader("Previously saved monthly reports")

        try:

            saved_objects = list_monthly_reports(
                month_folder
            )

            saved_names = sorted(
                [
                    item["name"]
                    for item in saved_objects
                    if item.get("name", "").lower().endswith(".pdf")
                ],
                reverse=True,
            )

            if not saved_names:

                st.info(
                    "No saved PDF reports were found for this month."
                )

            else:

                selected_report = st.selectbox(
                    "Choose a saved report",
                    saved_names,
                    key=f"saved_report_{month_folder}",
                )

                if selected_report:

                    selected_path = (
                        f"{month_folder}/{selected_report}"
                    )

                    try:

                        with st.spinner("Loading saved report..."):

                            saved_pdf = download_monthly_report(
                                selected_path
                            )

                        st.download_button(
                            "⬇️ Download selected saved report",
                            data=saved_pdf,
                            file_name=selected_report,
                            mime="application/pdf",
                            key=f"download_saved_{month_folder}_{selected_report}",
                        )

                    except Exception as e:

                        st.error(
                            f"Could not download the saved report: {e}"
                        )

        except Exception as e:

            st.error(
                f"Could not retrieve saved monthly reports: {e}"
            )


# ---------- Footer ----------

st.divider()
st.caption("DayTrace | Teacher Workday Tracker")




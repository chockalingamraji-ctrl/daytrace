import json
import uuid
from datetime import date, datetime, time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="DayTrace", page_icon="📘", layout="wide")

DATA_FILE = Path("daytrace_data.json")
WHOLE_DAY = "Whole day"

TIME_SLOTS = [
    "8:20–8:50 AM", "8:50–9:20 AM", "9:20–9:50 AM",
    "9:50–10:20 AM", "10:20–10:50 AM", "10:50–11:20 AM",
    "11:20–11:50 AM", "11:50 AM–12:20 PM", "12:20–12:50 PM",
    "12:50–1:20 PM", "1:20–1:50 PM", "1:50–2:20 PM",
    "2:20–2:50 PM", "2:50–3:20 PM", "3:20–3:50 PM",
    "3:50–4:20 PM", "4:20–4:40 PM"
]

ACTIVITIES = [
    "Teaching", "Lesson Planning", "Correction / Assessment",
    "Classroom Preparation", "Meetings", "Student Support",
    "Administrative Work", "Parent Communication",
    "English training for teachers", "Training", "Staff record",
    "Workbook correction", "Preparing progress report",
    "Progress report writing",
    "Break", "Other School Duty"
]

TEACHING_SUBJECTS = [
    "Language", "Math", "GA", "Flip/Tamil", "School Cinema",
    "Water play", "Art", "Activity", "Outdoor play",
    "Material play/computer science", "Story/computer science"
]


# ---------- storage (one shared file for every teacher) ----------

def normalise(saved):
    """Make sure every record has an id, a teacher and a reviewed flag."""
    records, changed = [], False
    for r in saved.get("daily_records", []):
        if not isinstance(r, dict):
            continue
        for key, default in (
            ("id", None), ("teacher", "Unknown teacher"), ("reviewed", False)
        ):
            if key not in r:
                r[key] = uuid.uuid4().hex if key == "id" else default
                changed = True
        records.append(r)
    data = {
        "daily_records": records,
        "reviewed_slots": saved.get("reviewed_slots", {}),
    }
    return data, changed


def save_data(data):
    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_data():
    saved = {}
    if DATA_FILE.exists():
        try:
            saved = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
    data, changed = normalise(saved)
    if changed:
        save_data(data)  # keep generated ids stable
    return data


# Loaded fresh on every run so all teachers and the section head
# always see the same, latest data.
data = load_data()


# ---------- helpers ----------

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


# ---------- header ----------

st.markdown("""
<style>
.hero {
    background: linear-gradient(120deg, #4f46e5, #8b5cf6);
    padding: 26px;
    border-radius: 18px;
    color: white;
}
.hero h1, .hero p { color: white; }
</style>
<div class="hero">
<h1>📘 DayTrace</h1>
<p>Your school day, organised and reviewed.</p>
</div>
""", unsafe_allow_html=True)

# ---------- sidebar: role, name, date ----------

role = st.sidebar.radio("I am a", ["Teacher", "Section Head"])
is_head = False
teacher_name = ""

if role == "Teacher":
    teacher_name = clean_name(st.sidebar.text_input("👤 Your name"))
else:
    expected = section_head_passcode()
    if expected is None:
        expected = "sectionhead"
        st.sidebar.warning(
            "No SECTION_HEAD_PASSCODE secret set. Using the default "
            "passcode 'sectionhead'. Please set your own."
        )
    entered = st.sidebar.text_input("🔑 Section head passcode", type="password")
    if entered == expected:
        is_head = True
    elif entered:
        st.sidebar.error("Wrong passcode.")

work_date = st.sidebar.date_input("📅 Select workday", date.today())
selected_date = work_date.isoformat()

day_records = [
    r for r in data["daily_records"] if r.get("date") == selected_date
]

# ---------- Teacher view ----------

if role == "Teacher":
    if not teacher_name:
        st.info("Enter your name in the sidebar to start recording.")
        st.stop()

    mine = [r for r in day_records if same_person(r.get("teacher", ""), teacher_name)]
    mine_reviewed = sum(1 for r in mine if r.get("reviewed"))

    a, b, c = st.columns(3)
    a.metric("My activities", len(mine))
    b.metric("Reviewed by section head", mine_reviewed)
    c.metric("Waiting for review", len(mine) - mine_reviewed)

    tab1, tab2 = st.tabs(["✍️ Record Activity", "🗓️ My Timeline"])

    with tab1:
        st.subheader("Record a school activity")

        mode = st.radio(
            "How do you want to enter the time?",
            ["Choose a slot", "Enter my own time", WHOLE_DAY],
            horizontal=True,
        )

        # Kept outside the form so the sub-options appear right away
        activity = st.selectbox("Activity", ACTIVITIES)
        subject = None
        if activity == "Teaching":
            subject = st.selectbox("Teaching subject", TEACHING_SUBJECTS)

        with st.form("activity_form", clear_on_submit=True):
            slot = start = end = None
            if mode == "Choose a slot":
                slot = st.selectbox("Time slot", TIME_SLOTS)
            elif mode == "Enter my own time":
                col1, col2 = st.columns(2)
                start = col1.time_input("From", value=time(8, 20), step=300)
                end = col2.time_input("To", value=time(8, 50), step=300)
            else:
                st.info("This will be saved for the whole day.")

            description = st.text_input("Description (optional)")
            submitted = st.form_submit_button("Save Activity", type="primary")

        if submitted:
            error = None
            if mode == "Enter my own time":
                if end <= start:
                    error = "The end time must be after the start time."
                time_label = f"{fmt_time(start)}–{fmt_time(end)}"
            elif mode == WHOLE_DAY:
                time_label = WHOLE_DAY
            else:
                time_label = slot

            if subject:
                activity = f"Teaching – {subject}"

            if activity == "Other School Duty":
                if not description.strip():
                    error = "Please describe the other school duty."
                else:
                    activity = f"Other School Duty: {description.strip()}"
            elif description.strip():
                activity = f"{activity}: {description.strip()}"

            if error:
                st.warning(error)
            else:
                data["daily_records"].append({
                    "id": uuid.uuid4().hex,
                    "date": selected_date,
                    "teacher": teacher_name,
                    "time": time_label,
                    "activity": activity,
                    "reviewed": False,
                })
                save_data(data)
                st.success("Activity saved!")
                st.rerun()

    with tab2:
        st.subheader(f"My Timeline — {selected_date}")
        if not mine:
            st.info("No activities recorded for this date yet.")
        else:
            for record in mine:
                with st.container(border=True):
                    status = "✅ Reviewed" if record.get("reviewed") else "⏳ Not reviewed"
                    st.markdown(f"**🕒 {record.get('time', '')}**  ·  {status}")
                    st.write(record.get("activity", ""))

            if st.button("Clear my unreviewed activities for this date"):
                data["daily_records"] = [
                    r for r in data["daily_records"]
                    if not (
                        r.get("date") == selected_date
                        and same_person(r.get("teacher", ""), teacher_name)
                        and not r.get("reviewed")
                    )
                ]
                save_data(data)
                st.rerun()

# ---------- Section head view ----------

else:
    if not is_head:
        st.info("Enter the section head passcode in the sidebar.")
        st.stop()

    total = len(day_records)
    done = sum(1 for r in day_records if r.get("reviewed"))
    teachers = sorted({r.get("teacher", "Unknown teacher") for r in day_records})

    a, b, c, d = st.columns(4)
    a.metric("Teachers", len(teachers))
    b.metric("Activities recorded", total)
    c.metric("Reviewed", f"{done}/{total}")
    d.metric("Review progress", f"{done * 100 // total if total else 0}%")
    st.progress(done / total if total else 0.0)

    tab1, tab2 = st.tabs(["✅ Review Workday", "💾 Backup"])

    with tab1:
        st.subheader(f"Review — {selected_date}")
        if not day_records:
            st.info("No teacher has recorded activities for this date yet.")

        for teacher in teachers:
            items = [r for r in day_records if r.get("teacher", "Unknown teacher") == teacher]
            n_done = sum(1 for r in items if r.get("reviewed"))
            with st.expander(
                f"👤 {teacher} — {n_done}/{len(items)} reviewed",
                expanded=n_done < len(items),
            ):
                for r in items:
                    left, right = st.columns([5, 2])
                    with left:
                        st.markdown(f"**🕒 {r.get('time', '')}**")
                        st.write(r.get("activity", ""))
                    with right:
                        if r.get("reviewed"):
                            st.caption("✅ Reviewed")
                            if st.button("Undo", key=f"undo_{r['id']}"):
                                r["reviewed"] = False
                                r.pop("reviewed_at", None)
                                save_data(data)
                                st.rerun()
                        else:
                            if st.button(
                                "Mark as reviewed",
                                key=f"rev_{r['id']}",
                                type="primary",
                            ):
                                r["reviewed"] = True
                                r["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
                                save_data(data)
                                st.rerun()
                    st.divider()

                if n_done < len(items):
                    if st.button(
                        f"Mark all of {teacher}'s activities as reviewed",
                        key=f"all_{selected_date}_{teacher}",
                    ):
                        now = datetime.now().isoformat(timespec="seconds")
                        for r in items:
                            if not r.get("reviewed"):
                                r["reviewed"] = True
                                r["reviewed_at"] = now
                        save_data(data)
                        st.rerun()

    with tab2:
        st.subheader("Backup all teachers' data")
        backup = json.dumps(data, indent=2, ensure_ascii=False)
        st.download_button(
            "⬇️ Download backup",
            data=backup,
            file_name="daytrace_backup.json",
            mime="application/json",
        )

        uploaded = st.file_uploader("Restore from a JSON backup", type=["json"])
        if uploaded is not None and st.button("Restore backup"):
            try:
                restored = json.load(uploaded)
                if not isinstance(restored.get("daily_records", []), list):
                    raise ValueError("Invalid activity list")
                if not isinstance(restored.get("reviewed_slots", {}), dict):
                    raise ValueError("Invalid review data")
                new_data, _ = normalise(restored)
                save_data(new_data)
                st.success("Backup restored!")
                st.rerun()
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
                st.error("Please choose a valid DayTrace backup.")

        st.divider()
        st.subheader("🗑️ Delete all data")
        st.caption("Removes every teacher's entries. Download a backup first if you want to keep a copy.")
        confirm = st.checkbox("Yes, I want to delete everything")
        if st.button("Delete all data", disabled=not confirm):
            save_data({"daily_records": [], "reviewed_slots": {}})
            st.success("All data deleted.")
            st.rerun()

st.divider()
st.caption("DayTrace | Teacher Workday Tracker")


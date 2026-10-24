
import json
from pathlib import Path
from datetime import date

import streamlit as st

st.set_page_config(page_title="DayTrace", page_icon="📘", layout="wide")

DATA_FILE = Path("daytrace_data.json")

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
    "Break", "Other School Duty"
]

def load_data():
    if DATA_FILE.exists():
        try:
            saved = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return {
                "daily_records": saved.get("daily_records", []),
                "reviewed_slots": saved.get("reviewed_slots", {})
            }
        except (OSError, json.JSONDecodeError):
            pass
    return {"daily_records": [], "reviewed_slots": {}}

if "daytrace" not in st.session_state:
    st.session_state.daytrace = load_data()

data = st.session_state.daytrace

def save_data():
    DATA_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

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

work_date = st.sidebar.date_input("📅 Select workday", date.today())
selected_date = work_date.isoformat()

records = [
    r for r in data["daily_records"]
    if isinstance(r, dict) and r.get("date") == selected_date
]
reviews = data["reviewed_slots"].setdefault(selected_date, {})

reviewed_count = sum(
    1 for slot in TIME_SLOTS
    if reviews.get(slot, "Not Reviewed") != "Not Reviewed"
)

a, b, c, d = st.columns(4)
a.metric("Activities recorded", len(records))
b.metric("Time slots", len(TIME_SLOTS))
c.metric("Slots reviewed", f"{reviewed_count}/{len(TIME_SLOTS)}")
d.metric("Review progress", f"{reviewed_count * 100 // len(TIME_SLOTS)}%")

st.progress(reviewed_count / len(TIME_SLOTS))

tab1, tab2, tab3, tab4 = st.tabs([
    "✍️ Record Activity", "✅ Review Workday",
    "🗓️ Daily Timeline", "💾 Backup"
])

with tab1:
    st.subheader("Record a school activity")
    with st.form("activity_form", clear_on_submit=True):
        time_slot = st.selectbox("Time slot", TIME_SLOTS)
        activity = st.selectbox("Activity", ACTIVITIES)
        description = st.text_input("Description (optional)")
        submitted = st.form_submit_button("Save Activity", type="primary")

    if submitted:
        if activity == "Other School Duty":
            if not description.strip():
                st.warning("Please describe the other school duty.")
                st.stop()
            activity = f"Other School Duty: {description.strip()}"
        elif description.strip():
            activity = f"{activity}: {description.strip()}"

        data["daily_records"].append({
            "date": selected_date,
            "time": time_slot,
            "activity": activity
        })
        save_data()
        st.success("Activity saved!")
        st.rerun()

with tab2:
    st.subheader("Review your workday")
    with st.form("review_form"):
        choices = {}
        for i, slot in enumerate(TIME_SLOTS):
            current = reviews.get(slot, "Not Reviewed")
            options = ["Not Reviewed", "Reviewed", "Not Applicable"]
            choices[slot] = st.selectbox(
                slot, options,
                index=options.index(current) if current in options else 0,
                key=f"review_{selected_date}_{i}"
            )
        save_reviews = st.form_submit_button("Save Review Progress")

    if save_reviews:
        data["reviewed_slots"][selected_date] = choices
        save_data()
        st.success("Review progress saved!")
        st.rerun()

with tab3:
    st.subheader(f"Daily Timeline — {selected_date}")
    if not records:
        st.info("No activities recorded for this date yet.")
    else:
        for record in records:
            with st.container(border=True):
                st.markdown(f"**🕒 {record.get('time', '')}**")
                st.write(record.get("activity", ""))

        if st.button("Clear activities for this date"):
            data["daily_records"] = [
                r for r in data["daily_records"]
                if not (
                    isinstance(r, dict)
                    and r.get("date") == selected_date
                )
            ]
            save_data()
            st.rerun()

with tab4:
    st.subheader("Backup your data")
    backup = json.dumps(data, indent=2, ensure_ascii=False)
    st.download_button(
        "⬇️ Download backup",
        data=backup,
        file_name="daytrace_backup.json",
        mime="application/json"
    )

    uploaded = st.file_uploader("Restore from a JSON backup", type=["json"])
    if uploaded is not None and st.button("Restore backup"):
        try:
            restored = json.load(uploaded)
            if not isinstance(restored.get("daily_records", []), list):
                raise ValueError("Invalid activity list")
            if not isinstance(restored.get("reviewed_slots", {}), dict):
                raise ValueError("Invalid review data")
            data["daily_records"] = restored.get("daily_records", [])
            data["reviewed_slots"] = restored.get("reviewed_slots", {})
            save_data()
            st.success("Backup restored!")
            st.rerun()
        except (ValueError, TypeError, json.JSONDecodeError):
            st.error("Please choose a valid DayTrace backup.")

st.divider()
st.caption("DayTrace | Teacher Workday Tracker")

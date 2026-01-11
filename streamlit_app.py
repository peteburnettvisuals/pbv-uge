import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime

# --- CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="UGE: Architect Command")

# Session State Initialization (Squad Pattern)
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 100,
        "inventory": ["Command Terminal", "Echo Shard"],
        "messages": [],
        "current_chapter_id": "1",
        "chat_session": None,
        # THE SQUAD DOSSIER
        "squad": {
            "SAM": {"role": "Negotiator", "neg": 95, "force": 25, "tech": 35, "status": "Active"},
            "DAVE": {"role": "Enforcer", "neg": 10, "force": 90, "tech": 10, "status": "Active"},
            "MIKE": {"role": "Specialist", "neg": 50, "force": 35, "tech": 85, "status": "Active"}
        },
        "efficiency_score": 1000
    })

# --- UTILITY FUNCTIONS ---
BUCKET_NAME = "uge-repository-cu32"

@st.cache_resource
def get_gcs_client():
    from google.oauth2 import service_account
    from google.cloud import storage
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def get_image_url(filename):
    if not filename: return ""
    try:
        client = get_gcs_client()
        blob = client.bucket(BUCKET_NAME).blob(f"cinematics/{filename}")
        return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))
    except: return ""

# --- AI ENGINE LOGIC (Architect / C2 Style) ---
def get_dm_response(prompt):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"temperature": 0.4})

    # Load XML Truth
    tree = ET.parse("game_sheet.xml")
    root = tree.getroot()
    
    chapter_data = root.find(f"chapter[@id='{st.session_state.current_chapter_id}']")
    
    if st.session_state.chat_session is None:
        # THE COMMANDER PROTOCOLS
        sys_instr = f"""
        {root.find("synopsis").text}
        
        YOU ARE: The 'Comms Net' relaying feeds from SAM, DAVE, and MIKE.
        PLAYER IS: COMMANDER.
        
        UNIT PROFILES:
        - SAM: Cynical, logical. High Negotiation (95), Low Force (25). Needs a 'Plan'.
        - DAVE: Surly, brief. High Force (90), Low Negotiation (10). Needs 'Orders'.
        - MIKE: ADHD, tech-obsessed. High Tech (85), Low Force (35). Needs 'Focus'.

        OPERATIONAL PROTOCOLS:
        1. MULTIPLEXED FEED: Report status from both Tavern and Herb Shop simultaneously.
        2. COMPETENCY FRICTION: If Architect sends DAVE to negotiate, describe a 'Full Metal Jacket' failure. Append [MANA_BURN: 15].
        3. RADIO TAGS: Prepend messages with [SAM], [DAVE], or [MIKE].
        4. UNIT ACQUISITION: Use [ADD_ITEM: Name] for gear.
        5. MISSION END: Use [CHAPTER_COMPLETE] only when objectives in both threads are met.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    response_text = st.session_state.chat_session.send_message(prompt).text

    # --- TAG PROCESSING ---
    if "[MANA_BURN:" in response_text:
        penalty = int(re.search(r"\[MANA_BURN:\s*(\d+)\]", response_text).group(1))
        st.session_state.mana = max(0, st.session_state.mana - penalty)
        st.session_state.efficiency_score -= (penalty * 10)
        st.toast(f"OPERATIONAL FRICTION: -{penalty}% Mana")

    if "[CHAPTER_COMPLETE]" in response_text:
        st.session_state.current_chapter_id = str(int(st.session_state.current_chapter_id) + 1)
        response_text = response_text.replace("[CHAPTER_COMPLETE]", "").strip()
        st.toast("SECTOR SECURED: Moving to Next Objective.")

    return response_text

# --- UI LAYOUT ---
with st.sidebar:
    st.header("🦅 BLACK RAVEN C2")
    
    # MISSION RESET BUTTON
    if st.button("🚨 ABORT MISSION (RESET)"):
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.session_state.mana = 100
        st.session_state.inventory = ["Command Terminal", "Echo Shard"]
        st.rerun()

    st.divider()
    
    # DYNAMIC SQUAD TRACKER
    st.subheader("📍 DEPLOYMENT STATUS")
    # We pull the last known location from the AI history or a state variable
    # For now, we'll use a placeholder that you can update via regex in get_dm_response
    cols = st.columns(3)
    with cols[0]: st.caption("SAM"); st.write("🟢 Square")
    with cols[1]: st.caption("DAVE"); st.write("🟡 Square")
    with cols[2]: st.caption("MIKE"); st.write("🔵 Square")
    
    st.divider()
    st.subheader("👥 SQUAD DOSSIERS")
    st.subheader("👥 SQUAD DOSSIERS")
    unit_view = st.radio("Access Unit Data:", ["SAM", "DAVE", "MIKE"], horizontal=True)
    
    # Mapping to your local .png files
    if unit_view == "DAVE":
        st.image("dave.png", use_container_width=True) 
        st.warning("SPECIALTY: FORCE (90) | WEAKNESS: NEG (10)")
    elif unit_view == "SAM":
        st.image("sam.png", use_container_width=True)
        st.success("SPECIALTY: NEG (95) | WEAKNESS: FORCE (25)")
    else:
        st.image("mike.png", use_container_width=True)
        st.info("SPECIALTY: TECH (85) | WEAKNESS: FORCE (35)")

    st.divider()
    st.subheader("📊 EFFICIENCY: " + str(st.session_state.efficiency_score))

# --- MAIN TERMINAL ---
chat_container = st.container(height=650, border=True)
with chat_container:
    if not st.session_state.messages:
        with st.spinner("Establishing Multiplex Link..."):
            init = get_dm_response("Architect on deck. Initialize squad feeds.")
            st.session_state.messages.append({"role": "assistant", "content": init})
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

if prompt := st.chat_input("Issue Commands (e.g., 'Sam, initiate bribe. Dave, cover her.')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = get_dm_response(prompt)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()
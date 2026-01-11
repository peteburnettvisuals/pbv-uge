import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime

# --- CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="UGE: Architect Command")

# Unified Session State Initialization
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 100,
        "inventory": ["Command Terminal", "Echo Shard"],
        "messages": [],
        "current_chapter_id": "1",
        "chat_session": None,
        "efficiency_score": 1000,
        # SQUAD DATA
        "locations": {"SAM": "Square", "DAVE": "Square", "MIKE": "Square"},
        "last_locations": {"SAM": "Square", "DAVE": "Square", "MIKE": "Square"},
        "idle_turns": {"SAM": 0, "DAVE": 0, "MIKE": 0},
        "squad": {
            "SAM": {"role": "Negotiator", "neg": 95, "force": 25, "tech": 35, "status": "Active"},
            "DAVE": {"role": "Enforcer", "neg": 10, "force": 90, "tech": 10, "status": "Active"},
            "MIKE": {"role": "Specialist", "neg": 50, "force": 35, "tech": 85, "status": "Active"}
        }
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
        1. NO HEADERS: Never use "Tavern Thread" or "Herb Shop" headers. 
        2. UNIT TAGS: Every transmission MUST start with [SAM], [DAVE], or [MIKE].
        3. LOCATION MENTIONS: When a unit arrives at a new location, they must state it clearly in their first sentence (e.g., "[SAM]: Commander, I've reached the Tavern.") This feeds the auto-tracker.
        4. CHARACTER FRICTION: Maintain Sam's skepticism, Dave's aggression, and Mike's tech-distractions. 
        5. ALIGNMENT PENALTY: If Dave is ordered to use social skills, apply [MANA_BURN: 15] and narrate a failure.
        6. IDLE DAVE PROTOCOL: Monitor DAVE's idle_turns. 
        - 2 Turns Idle: He starts 'checking his gear' and interrupting the feed with grunts.
        - 3 Turns Idle: He begins making 'suggestions' (usually involving violence) to the other units on the net.
        - 4 Turns Idle: Significant frustration. He will attempt to provoke an NPC at his current location to 'see if they've got any spine.' [MANA_BURN: 10]
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    response_text = st.session_state.chat_session.send_message(prompt).text

    # --- AUTO-TRACKER LOGIC ---
    # Initialize locations if not present
    if "locations" not in st.session_state:
        st.session_state.locations = {"SAM": "Square", "DAVE": "Square", "MIKE": "Square"}

    # Look for: [NAME] (Location Name) or [NAME]: I am at Location
    for unit in ["SAM", "DAVE", "MIKE"]:
        # Regex looks for the unit tag and the first mention of a known location following it
        loc_match = re.search(rf"\[{unit}\].*?(Tavern|Herb Shop|Square|Mountain)", response_text, re.IGNORECASE)
        if loc_match:
            st.session_state.locations[unit] = loc_match.group(1).title()

    

    for unit in ["SAM", "DAVE", "MIKE"]:
        # If the regex confirms they are in the same spot as last turn
        if st.session_state.locations[unit] == st.session_state.last_locations[unit]:
            st.session_state.idle_turns[unit] += 1
        else:
            # Movement resets the clock!
            st.session_state.idle_turns[unit] = 0
            st.session_state.last_locations[unit] = st.session_state.locations[unit]
    
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
    
    if st.button("🚨 ABORT MISSION (RESET)"):
        st.session_state.messages = []
        st.session_state.chat_session = None
        st.session_state.mana = 100
        st.session_state.efficiency_score = 1000
        # Reset the tracker
        st.session_state.locations = {"SAM": "Square", "DAVE": "Square", "MIKE": "Square"}
        st.session_state.last_locations = {"SAM": "Square", "DAVE": "Square", "MIKE": "Square"}
        st.session_state.idle_turns = {"SAM": 0, "DAVE": 0, "MIKE": 0}
        st.rerun()

    st.divider()
    
    #Deployment Location Tracker
    st.subheader("📍 DEPLOYMENT STATUS")
    cols = st.columns(3)
    for i, unit in enumerate(["SAM", "DAVE", "MIKE"]):
        with cols[i]:
            st.caption(unit)
            # 1. Get the current idle count
            idle = st.session_state.idle_turns.get(unit, 0)
            
            # 2. Determine color based on tension (overwrites the fixed dots)
            if idle < 2: status_color = "🟢"
            elif idle < 4: status_color = "🟡"
            else: status_color = "🔴"
            
            # 3. Display the dynamic location
            loc = st.session_state.locations.get(unit, "Square")
            st.write(f"{status_color} {loc}")
    
    st.divider()
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
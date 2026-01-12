import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime
import folium
from streamlit_folium import st_folium


def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

local_css("style.css")

# --- CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="UGE: Architect Command")

# Unified Session State Initialization
if "viability" not in st.session_state:
    st.session_state.update({
        "viability": 100,      # Replaces Mana: Plausible Deniability
        "mission_time": 60,   # 60-minute window (0500-0600)
        "inventory": ["C2 Terminal", "Encrypted Uplink"], 
        "messages": [],
        "current_chapter_id": "1",
        "chat_session": None,
        "efficiency_score": 1000,
        "unlocked_intel": [],  # For the upcoming Asset Gallery
        
        # SQUAD DATA - Starting at the Insertion Point
        "locations": {"SAM": "Perimeter", "DAVE": "Perimeter", "MIKE": "Perimeter"},
        "idle_turns": {"SAM": 0, "DAVE": 0, "MIKE": 0},
        "squad": {
            "SAM": {"role": "Intel", "neg": 95, "force": 25, "tech": 35, "status": "Active"},
            "DAVE": {"role": "Point", "neg": 10, "force": 90, "tech": 10, "status": "Active"},
            "MIKE": {"role": "SIGINT", "neg": 50, "force": 35, "tech": 85, "status": "Active"}
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
    # 1. TACTICAL SAFETY & CONFIG
    # Refactored safety settings to prevent KeyErrors
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash', 
                                  generation_config={"temperature": 0.3},
                                  safety_settings=safety_settings)

    # 2. XML GROUND TRUTH
    tree = ET.parse("game_sheet.xml")
    root = tree.getroot()
    chapter_data = root.find(f"chapter[@id='{st.session_state.current_chapter_id}']")
    locations_xml = chapter_data.find("locations")
    location_list = [loc.get("name") for loc in locations_xml.findall("location")]
    
    if st.session_state.chat_session is None:
        sys_instr = f"""
        {root.find("synopsis").text}
        YOU ARE: Agency Comms Net. PLAYER: Commander.
        VALID LOCATIONS: {', '.join(location_list)}
        
        UNIT PROFILES:
        - SAM: Intel/Social. 95 Neg. Needs a plan.
        - DAVE: Direct Action. 90 Force. Needs ROE.
        - MIKE: SIGINT. 85 Tech. Needs focus.

        OPERATIONAL PROTOCOLS:
        1. UNIT TAGS: Start every transmission with [SAM], [DAVE], or [MIKE].
        2. TACTICAL MENTIONS: Units must state their location arrival in the first sentence.
        3. CONTENT: PG-13 Tactical Thriller style. Focus on outcomes.
        4. SQUAD FUSES: DAVE (Short: 3), SAM (Med: 5), MIKE (Long: 8).
        5. VIABILITY: High-visibility violence triggers [VIABILITY_BURN: X].
        6. INTERNAL PROTOCOL: You are a passive multiplexer. You NEVER issue orders to the Player. You only relay the voices of SAM, DAVE, and MIKE. You are the mirror, not the master.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    # 3. ADVANCE MISSION CLOCK
    #st.session_state.mission_time -= 1
    response_text = st.session_state.chat_session.send_message(prompt).text

    # 4. ENHANCED DYNAMIC TRACKER (Refactored for Modern Sites)
    for unit in ["SAM", "DAVE", "MIKE"]:
        dynamic_locs = "|".join(location_list + ["Perimeter", "Hub", "Office", "Bay"])
        pattern = rf"\[{unit}\].*?({dynamic_locs})"
        loc_match = re.search(pattern, response_text, re.IGNORECASE)
        if loc_match:
            st.session_state.locations[unit] = loc_match.group(1).title()

    # 5. METIER FULFILLMENT (Refactored for PMC Skills)
    for unit in ["SAM", "DAVE", "MIKE"]:
        st.session_state.idle_turns[unit] += 1
        metier_keywords = {
            "SAM": r"(bribe|interrogate|flip|negotiate|persuade|alias|intel|social)",
            "DAVE": r"(breach|neutralize|suppress|clear|secure|ordnance|shove|punch)",
            "MIKE": r"(hack|scramble|drone|decrypt|intercept|bypass|uplink|sensor)"
        }
        pattern = rf"\[{unit}\].*?{metier_keywords[unit]}"
        if re.search(pattern, response_text, re.IGNORECASE):
            st.session_state.idle_turns[unit] = 0
    
    # 6. TAG PROCESSING (Viability replaces Mana)
    if "[VIABILITY_BURN:" in response_text:
        penalty = int(re.search(r"\[VIABILITY_BURN:\s*(\d+)\]", response_text).group(1))
        st.session_state.viability = max(0, st.session_state.viability - penalty)
        st.toast(f"🚨 SIGNAL COMPROMISED: -{penalty}% Viability")

    return response_text

# --- UI LAYOUT ---
with st.sidebar:
    st.header("🦅 GUNDOG C2")
    
    # Dual-Metric HUD
    st.progress(st.session_state.viability / 100, text=f"PLAUSIBLE DENIABILITY: {st.session_state.viability}%")
    
    avg_morale = sum([100 - (t * 10) for t in st.session_state.idle_turns.values()]) / 3
    st.progress(avg_morale / 100, text=f"SQUAD MORALE: {int(avg_morale)}%")
    
    st.metric(label="MISSION CLOCK", value=f"{st.session_state.mission_time} MIN")
    
    # Fixed Abort Logic
    if st.button("🚨 ABORT MISSION (RESET)"):
        st.session_state.clear() # Clears everything to trigger a fresh boot
        st.rerun()

    st.divider()
    
    # Deployment Location Tracker (Fixed default to 'Perimeter')
    st.subheader("📍 DEPLOYMENT STATUS")
    cols = st.columns(3)
    for i, unit in enumerate(["SAM", "DAVE", "MIKE"]):
        with cols[i]:
            st.caption(unit)
            idle = st.session_state.idle_turns.get(unit, 0)
            status_color = "🟢" if idle < 2 else "🟡" if idle < 4 else "🔴"
            
            # Start at Perimeter instead of Square
            loc = st.session_state.locations.get(unit, "Perimeter") 
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

# Create the dual-column tactical view
col1, col2 = st.columns([0.4, 0.6])

with col1:
    st.markdown("### 📡 COMMS FEED")
    chat_container = st.container(height=650, border=True)
    with chat_container:
        # AUTO-SITREP: If there are no messages, trigger the start immediately
        if not st.session_state.messages:
            with st.spinner("Establishing Multiplex Link..."):
                # This triggers the sys_instr and gets the first squad report
                init_response = get_dm_response("Commander on deck. All units are currently at Costa Verde dock. Sam, Mike, Dave—give me a quick SITREP on your immediate surroundings before I deploy you. Let me know what locations you can see.")
                st.session_state.messages.append({"role": "assistant", "content": init_response})
                # st.rerun() is removed here to avoid an infinite loop during initial load

        # Display the comms log
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

with col2:
    st.markdown("### 🗺️ TACTICAL OVERVIEW: CRISTOBAL")
    # Initialize the Folium Map here
    m = folium.Map(location=[9.3492, -79.9150], zoom_start=15, tiles="CartoDB dark_matter")
    
    # Create custom icons from your URLs
    sam_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/sam-map1.png", icon_size=(45, 45))
    dave_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/dave-map1.png", icon_size=(45, 45))
    mike_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/mike-map1.png", icon_size=(45, 45))

    # Add to Puerto de Cristobal Map
    folium.Marker([9.3512, -79.9145], icon=sam_token, tooltip="SAM: ACTIVE").add_to(m)
    folium.Marker([9.3485, -79.9160], icon=dave_token, tooltip="DAVE: OVERWATCH").add_to(m)
    folium.Marker([9.3500, -79.9130], icon=mike_token, tooltip="MIKE: INFIL").add_to(m)

    # 1. Define the coordinates for the restricted area
    # This covers the primary docks and warehouse hub in Puerto de Cristobal
    restricted_zone = [
        [9.3525, -79.9165],
        [9.3525, -79.9130],
        [9.3470, -79.9130],
        [9.3470, -79.9175],
    ]

    # 2. Add the Polygon to the map
    folium.Polygon(
        locations=restricted_zone,
        color="#FF0000",       # Red border
        fill=True,
        fill_color="#FF0000",  # Red fill
        fill_opacity=0.2,      # Semi-transparent
        popup="HIGH SECURITY: CRISTOBAL PIERS",
        tooltip="DETECTION RISK: HIGH"
    ).add_to(m)
    
    st_folium(m, use_container_width=True)                

if prompt := st.chat_input("Issue Commands..."):
    # The clock only moves when the Commander acts
    st.session_state.mission_time -= 1 
    
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = get_dm_response(prompt)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()
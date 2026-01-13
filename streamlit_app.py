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
st.set_page_config(layout="wide", page_title="Gundogs C2: Cristobal Mission")



# 1. ENGINE UTILITIES
def load_mission(file_path):
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        mission_map = {}
        for poi in root.findall('.//poi'):
            poi_id = poi.get('id')
            mission_map[poi_id] = {
                "coords": [float(poi.find('lat').text), float(poi.find('lon').text)],
                "image": poi.find('image').text,
                "name": poi.find('name').text,
                "intel": poi.find('intel').text
            }
        return mission_map
    except Exception as e:
        st.error(f"Mission Data Corruption: {e}")
        return {}

# 2. GLOBAL INITIALIZATION
MISSION_DATA = load_mission('mission_data.xml')

# Parse objectives immediately for the Sidebar UI
def get_initial_objectives(file_path):
    tree = ET.parse(file_path)
    return {t.get('id'): (t.get('status').lower() == 'true') for t in tree.findall('.//task')}

if "objectives" not in st.session_state:
    st.session_state.objectives = get_initial_objectives('mission_data.xml')

# Unified Session State Initialization
if "viability" not in st.session_state:
    st.session_state.update({
        "viability": 100,
        "mission_time": 60,
        "messages": [],
        "chat_session": None,
        "efficiency_score": 1000,
        "locations": {"SAM": "South Quay", "DAVE": "South Quay", "MIKE": "South Quay"},
        "idle_turns": {"SAM": 0, "DAVE": 0, "MIKE": 0},
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

@st.cache_data(ttl=3600) # Cache for 1 hour to match the signed URL expiration
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

    # 2. XML GROUND TRUTH & OBJECTIVES
    # We pull the mission intent and objectives to keep the AI on rails
    mission_tree = ET.parse("mission_data.xml")
    mission_root = mission_tree.getroot()
    # Extract objectives directly from the tree we just opened
    st.session_state.objectives = {
        task.get('id'): (task.get('status').lower() == 'true') 
        for task in mission_root.findall('.//task')
    }
    intent = mission_root.find("intent")
    
    # Format objectives for the AI so it knows the "To-Do" list
    objs_text = ""
    for task in intent.findall(".//task"):
        status = "COMPLETED" if st.session_state.objectives.get(task.get('id')) else "PENDING"
        objs_text += f"- [{status}] {task.find('description').text} (ID: {task.get('id')})\n"

    # Map aliases for location adherence
    location_logic = ""
    for poi in mission_root.findall(".//poi"):
        name = poi.find('name').text
        aliases = poi.find('aliases').text if poi.find('aliases') is not None else ""
        location_logic += f"- {name} (Aliases: {aliases})\n"

    if st.session_state.chat_session is None:
        sys_instr = f"""
        THEATER: {intent.find("theater").text}
        SITUATION: {intent.find("situation").text}
        CONSTRAINTS: {intent.find("constraints").text}

        CANONICAL LOCATIONS & PERMITTED ALIASES:
        {location_logic}
        
        YOU ARE: The tactical multiplexer for Gundogs PMC.
        
        STRICT OPERATIONAL RULES:
        1. LOCATIONAL ADHERENCE: You only recognize the locations listed above. If the Commander orders a unit to a non-canonical location (e.g., 'Ice Cream Factory'), the unit must reply they have no intel on that coordinate and remain stationary.
        2. MOVEMENT: When a unit is ordered to a location or one of its aliases, you MUST start their dialogue with: "[UNIT] Moving to [CANONICAL NAME] / Arrived at [CANONICAL NAME]."
        3. OBJECTIVE TRACKING: When a unit performs an action that satisfies a 'PENDING' task (see logic in XML), you must output the tag [OBJECTIVE_MET: task_id] at the end of the transmission.
        4. NO HALLUCINATIONS: Do not invent new buildings or NPCs. Use the <intel> provided in the mission data.
        5. VOICE: 
           - SAM: Cynical, focuses on 'Negotiation/Logic'.
           - DAVE: Brief, focuses on 'Force'. 
           - MIKE: Tech-heavy, focuses on 'Signals/Hacking'.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    # 1. Prepare the Tactical Context String
    obj_status = ", ".join([f"{k}:{'DONE' if v else 'TODO'}" for k, v in st.session_state.objectives.items()])
    unit_locs = ", ".join([f"{u}@{loc}" for u, loc in st.session_state.locations.items()])
    
    # 2. Build the Enriched Prompt
    # This is "hidden" from the user but visible to the AI
    enriched_prompt = f"""
    [SYSTEM_STATE_UPDATE]
    TIME_REMAINING: {st.session_state.mission_time}m
    SQUAD_LOCATIONS: {unit_locs}
    OBJECTIVES: {obj_status}
    VIABILITY: {st.session_state.viability}%

    [COMMANDER_ORDERS]
    {prompt}
    """
    
    # 3. ADVANCE MISSION CLOCK
    #st.session_state.mission_time -= 1
    response_text = st.session_state.chat_session.send_message(enriched_prompt).text

    # 4. ENHANCED DYNAMIC TRACKER (Strict Canonical Adherence)
    # We build the search pattern from the actual XML data keys and names
    valid_names = [info['name'] for info in MISSION_DATA.values()]
    valid_ids = list(MISSION_DATA.keys())
    search_pattern = "|".join(set(valid_names + valid_ids))
    
    for unit in ["SAM", "DAVE", "MIKE"]:
        # Pattern looks for: [DAVE] ... Harbor Master Office
        pattern = rf"\[{unit}\].*?({search_pattern})"
        loc_match = re.search(pattern, response_text, re.IGNORECASE)
        
        if loc_match:
            detected_name = loc_match.group(1).lower().replace(" ", "_")
            
            # Match the detected string back to a valid POI ID
            for poi_id, info in MISSION_DATA.items():
                if detected_name == poi_id or detected_name == info['name'].lower().replace(" ", "_"):
                    st.session_state.locations[unit] = info['name']
                    break

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

    # 7. OBJECTIVE TRACKING (Flips the booleans based on AI confirmation)
    obj_pattern = r"\[OBJECTIVE_MET:\s*(obj_\w+)\]"
    obj_matches = re.findall(obj_pattern, response_text)
    
    for obj_id in obj_matches:
        if obj_id in st.session_state.objectives and not st.session_state.objectives[obj_id]:
            st.session_state.objectives[obj_id] = True
            st.toast(f"✅ TASK COMPLETE: {obj_id.replace('obj_', '').replace('_', ' ').upper()}")
            # Logic: If an objective is met, efficiency score goes up
            st.session_state.efficiency_score += 100

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

    # Add this to your Sidebar logic:
    st.subheader("📝 MISSION CHECKLIST")
    for obj_id, status in st.session_state.objectives.items():
        label = obj_id.replace('obj_', '').replace('_', ' ').title()
        if status:
            st.write(f"✅ ~~{label}~~")
        else:
            st.write(f"◻️ {label}")
    
    # Deployment Location Tracker (Fixed default to 'Perimeter')
    st.subheader("📍 DEPLOYMENT STATUS")
    cols = st.columns(3)
    for i, unit in enumerate(["SAM", "DAVE", "MIKE"]):
        with cols[i]:
            st.caption(unit)
            idle = st.session_state.idle_turns.get(unit, 0)
            status_color = "🟢" if idle < 2 else "🟡" if idle < 4 else "🔴"
            

     
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
    
    # 1. DEFINE ASSETS IMMEDIATELY (Fixes NameError)
    sam_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/sam-map1.png", icon_size=(45, 45))
    dave_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/dave-map1.png", icon_size=(45, 45))
    mike_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/mike-map1.png", icon_size=(45, 45))
    
    # 2. INITIALIZE MAP
    m = folium.Map(location=[9.3492, -79.9150], zoom_start=15, tiles="CartoDB dark_matter")
    
    # 3. MARK MISSION LOCATIONS (Cached & Clickable)
    for loc_id, info in MISSION_DATA.items():
        # Using the cached function to prevent the refresh loop
        loc_img_url = get_image_url(info["image"])
        
        popup_html = f"""
            <div style="width: 200px; background-color: #fff; padding: 10px; border: 1px solid #fff;">
                <h4 style="color: #111111; margin-top: 0;">{info['name'].upper()}</h4>
                <img src="{loc_img_url}" style="width: 100%; border: 1px solid #00FF00;">
                <p style="font-size: 11px; color: #111111; margin-top: 5px;">{info['intel']}</p>
            </div>
        """
        
        # Circle for visual demarkation
        folium.Circle(
            location=info["coords"],
            radius=50,
            color="#00FF00",
            weight=1,
            fill=True,
            fill_color="#00FF00",
            fill_opacity=0.1,
            interactive=False 
        ).add_to(m)

        # Invisible Marker for reliable popup triggering
        folium.Marker(
            location=info["coords"],
            icon=folium.DivIcon(html="""<div style="width: 40px; height: 40px; margin-left: -20px; margin-top: -20px;"></div>"""), 
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"INSPECT: {info['name']}"
        ).add_to(m)

    # 4. DYNAMIC SQUAD PLACEMENT (With Offsets)
    tokens = {"SAM": sam_token, "DAVE": dave_token, "MIKE": mike_token}
    offsets = {
        "SAM":  [0.00015, 0.00000], 
        "DAVE": [-0.00010, 0.00015],
        "MIKE": [-0.00010, -0.00015]
    }

    for unit, icon in tokens.items():
        current_loc_name = st.session_state.locations.get(unit, "Perimeter")
        loc_id = current_loc_name.lower().replace(" ", "_")
        loc_info = MISSION_DATA.get(loc_id, MISSION_DATA.get("perimeter"))
        
        base_coords = loc_info["coords"]
        offset = offsets.get(unit, [0, 0])
        final_coords = [base_coords[0] + offset[0], base_coords[1] + offset[1]]
        
        folium.Marker(
            final_coords, 
            icon=icon, 
            tooltip=f"{unit}: {current_loc_name.upper()}"
        ).add_to(m)
    
    # 5. RENDER (Stability settings)
    st_folium(m, use_container_width=True, key="tactical_map_v2", returned_objects=[])       

if prompt := st.chat_input("Issue Commands..."):
    # The clock only moves when the Commander acts
    st.session_state.mission_time -= 1 
    
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = get_dm_response(prompt)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()
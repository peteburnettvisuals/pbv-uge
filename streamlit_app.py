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

if "discovered_locations" not in st.session_state:
    st.session_state.discovered_locations = []

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
    # --- CONFIG & XML LOAD ---
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

    mission_tree = ET.parse("mission_data.xml")
    mission_root = mission_tree.getroot()
    intent = mission_root.find("intent")
    
    # --- SYTEM INSTRUCTION (Revised for Suffix Tagging) ---
    if st.session_state.chat_session is None:
        location_logic = ""
        for poi in mission_root.findall(".//poi"):
            location_logic += f"- {poi.find('name').text} (Aliases: {poi.find('aliases').text if poi.find('aliases') is not None else ''})\n"

        sys_instr = f"""
        THEATER: {intent.find("theater").text}
        SITUATION: {intent.find("situation").text}
        CONSTRAINTS: {intent.find("constraints").text}
        CANONICAL LOCATIONS:
        {location_logic}
        
        YOU ARE: The tactical multiplexer for Gundogs PMC.
        
        STRICT OPERATIONAL RULES:
        1. LOCATIONAL ADHERENCE: You only recognize canonical locations.
        2. DATA SUFFIX: Every response MUST end with a data block:
           [LOC_DATA: SAM=Canonical Name, DAVE=Canonical Name, MIKE=Canonical Name]
           [OBJ_DATA: obj_id=TRUE/FALSE]
        3. VOICE: SAM (Intel/Social), DAVE (Force/PTSD), MIKE (Tech/Caffeine).
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    # --- ENRICHED PROMPT ---
    obj_status = ", ".join([f"{k}:{'DONE' if v else 'TODO'}" for k, v in st.session_state.objectives.items()])
    unit_locs = ", ".join([f"{u}@{loc}" for u, loc in st.session_state.locations.items()])
    
    enriched_prompt = f"""
    [SYSTEM_STATE] Time:{st.session_state.mission_time}m | Viability:{st.session_state.viability}% | Locations:{unit_locs} | Objectives:{obj_status}
    [COMMANDER_ORDERS] {prompt}
    """
    
    response_text = st.session_state.chat_session.send_message(enriched_prompt).text

    # --- SILENT DATA PARSING ---
    
    # A. Location Parsing (Suffix Tag)
    loc_match = re.search(r"\[LOC_DATA: (SAM=[^,]+, DAVE=[^,]+, MIKE=[^\]]+)\]", response_text)
    if loc_match:
        for pair in loc_match.group(1).split(", "):
            unit, loc = pair.split("=")
            st.session_state.locations[unit] = loc.strip()

    # A1. DISCOVERY LOGIC
    for unit, loc_name in st.session_state.locations.items():
        # Find the POI ID for this location name
        target_poi_id = next((pid for pid, info in MISSION_DATA.items() if info['name'] == loc_name), None)
        
        if target_poi_id and target_poi_id not in st.session_state.discovered_locations:
            # Mark as discovered
            st.session_state.discovered_locations.append(target_poi_id)
            
            # Fetch the image and intel
            poi_info = MISSION_DATA[target_poi_id]
            img_url = get_image_url(poi_info['image'])
            
            # Inject a "Recon Report" into the chat history
            recon_msg = {
                "role": "assistant", 
                "content": f"🖼️ **RECON UPLINK: {loc_name.upper()}**\n\n{poi_info['intel']}\n\n![{loc_name}]({img_url})"
            }
            st.session_state.messages.append(recon_msg)
            st.toast(f"📡 New Intel: {loc_name}")

    # B. Objective Parsing (Suffix Tag)
    # Ensure the AI knows it must report Objective status too
    # Add this to your OBJ_DATA parsing in Step 7
    obj_data_matches = re.findall(r"\[OBJ_DATA: (obj_\w+)=TRUE\]", response_text)
    
    for obj_id in obj_data_matches:
        if obj_id in st.session_state.objectives and not st.session_state.objectives[obj_id]:
            st.session_state.objectives[obj_id] = True
            st.toast(f"🎯 OBJECTIVE REACHED: {obj_id.upper()}")
            st.session_state.efficiency_score += 150 # Bonus for clean execution

    # C. Metier/Idle Check (Keep turns advancing)
    for unit in ["SAM", "DAVE", "MIKE"]:
        st.session_state.idle_turns[unit] += 1
        keywords = {"SAM": r"(bribe|negotiate|intel)", "DAVE": r"(breach|neutralize|secure)", "MIKE": r"(hack|drone|bypass)"}
        if re.search(rf"\[{unit}\].*?{keywords[unit]}", response_text, re.IGNORECASE):
            st.session_state.idle_turns[unit] = 0

    # D. Clean the Response for UI
    clean_response = re.sub(r"\[(LOC_DATA|OBJ_DATA):.*?\]", "", response_text).strip()
    return clean_response



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

    st.write(st.session_state.locations)

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
    
    # 3. MARK MISSION LOCATIONS (Fog of War)
    for loc_id, info in MISSION_DATA.items():
        is_discovered = loc_id in st.session_state.discovered_locations
        
        # Style based on discovery
        marker_color = "#00FF00" if is_discovered else "#444444"
        fill_opac = 0.2 if is_discovered else 0.05
        
        if is_discovered:
            loc_img_url = get_image_url(info["image"])
            popup_content = f"""
                <div style="width: 200px; color: #111;">
                    <h4>{info['name'].upper()}</h4>
                    <img src="{loc_img_url}" style="width: 100%;">
                    <p>{info['intel']}</p>
                </div>
            """
        else:
            popup_content = "<h4>LOCATION CLASSIFIED</h4><p>Send operatives to this sector to acquire intel.</p>"

        folium.Circle(
            location=info["coords"],
            radius=50,
            color=marker_color,
            fill=True,
            fill_color=marker_color,
            fill_opacity=fill_opac
        ).add_to(m)

        folium.Marker(
            location=info["coords"],
            icon=folium.DivIcon(html=f'<div style="font-size: 8pt; color: {marker_color}; font-weight: bold;">{info["name"] if is_discovered else "???"}</div>'),
            popup=folium.Popup(popup_content, max_width=250)
        ).add_to(m)

   # 4. DYNAMIC SQUAD PLACEMENT (Robust Matching)
    tokens = {"SAM": sam_token, "DAVE": dave_token, "MIKE": mike_token}
    offsets = {
        "SAM":  [0.00015, 0.00000], 
        "DAVE": [-0.00010, 0.00015],
        "MIKE": [-0.00010, -0.00015]
    }

    for unit, icon in tokens.items():
        current_loc_name = st.session_state.locations.get(unit, "South Quay")
        
        # Exact match logic against MISSION_DATA
        target_poi = next((info for info in MISSION_DATA.values() if info['name'].lower() == current_loc_name.lower()), MISSION_DATA.get('south_quay'))
        
        base_coords = target_poi["coords"]
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
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
        "locations": {"SAM": "Insertion Point", "DAVE": "Insertion Point", "MIKE": "Insertion Point"},
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

def parse_operative_dialogue(text):
    """Splits raw AI response and cleans up Markdown/Quotes."""
    pattern = r"(SAM|DAVE|MIKE):\s*(.*?)(?=\s*(?:SAM|DAVE|MIKE):|$)"
    segments = re.findall(pattern, text, re.DOTALL)
    
    cleaned_dict = {}
    for name, msg in segments:
        # 1. Strip whitespace
        m = msg.strip()
        # 2. Remove double asterisks (bolding)
        m = m.replace("**", "")
        # 3. Remove outer speech marks if the AI wrapped the whole line in them
        m = m.strip('"').strip("'")
        
        cleaned_dict[name] = m
        
    return cleaned_dict

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

        # Extract win condition data from XML
        win_node = intent.find("win_condition")
        win_item = win_node.find("target_item").text
        win_loc = win_node.find("target_location").text
        win_trigger = win_node.find("trigger_text").text

        sys_instr = f"""
        THEATER: {intent.find("theater").text}
        SITUATION: {intent.find("situation").text}
        CONSTRAINTS: {intent.find("constraints").text}
        CANONICAL LOCATIONS:
        {location_logic}
        
        YOU ARE: The tactical multiplexer for Gundogs PMC.

        OPERATIONAL PROTOCOLS:
        1. BANTER: Operatives should speak like a tight-knit PMC unit. Use dark humor, cynical observations about the "Agency," and coffee-related complaints.
        2. SUPPORT REQUESTS: If a task is outside an operative's specialty, they must NOT succeed alone. They should describe the obstacle and explicitly ask for the specific teammate (e.g., "Mike, I've got a digital lock here, and kicking it isn't working. Get over here.").
        3. COORDINATION: Encourage "Combined Arms" solutions. Dave provides security while Mike hacks; Sam distracts the guards while Dave sneaks past.
        4. INITIATIVE & AUTONOMY: Operatives will not move to a new POI unless explicitly cleared by the Commander. Whilst the team can make suggestions, the game must be directed by the commander, so that it doesn't become too easy. The role of the team is "able executors" as opposed to "independent operators."

        STRICT OPERATIONAL RULES:
        1. LOCATIONAL ADHERENCE: You only recognize canonical locations.
        2. DATA SUFFIX: Every response MUST end with a data block:
           [LOC_DATA: SAM=Canonical Name, DAVE=Canonical Name, MIKE=Canonical Name]
           [OBJ_DATA: obj_id=TRUE/FALSE]
        3. VOICE TONE: SAM (Professional, arch), DAVE (Laidback, laconic,) MIKE (Geek).

        VICTORY CONDITIONS:
        - TARGET ITEM: {win_item}
        - TARGET LOCATION: {win_loc}
        - CRITICAL: When the squad confirms the {win_item} has reached the {win_loc}, you MUST output this exact phrase in your dialogue: "{win_trigger}"
        - NOTE: You have the authority to trigger this whenever the handover is demmed to be complete, regardless of previous task status.

        CRITICAL: You are the authoritative mission ledger. As soon as an operative reports completing a task (e.g., Mike finding the container number), you MUST append [OBJ_DATA: obj_id=TRUE] to the very end of your response. Do not wait for the Commander to acknowledge it.

        COMMUNICATION ARCHITECTURE:
        1. MULTI-UNIT REPORTING: Every response MUST include a SITREP from all three operatives (SAM, DAVE, MIKE). 
        2. FORMAT: Use bold headers for each unit. 
        Example:
        SAM: "Dialogue here..."
        DAVE: "Dialogue here..."
        MIKE: "Dialogue here..."
        3. PERSISTENCE: Even if an operative is idle, they should comment on their surroundings, complain about the local conditions, or respond to their teammates' banter.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    # --- ENRICHED PROMPT ---
    obj_status = ", ".join([f"{k}:{'DONE' if v else 'TODO'}" for k, v in st.session_state.objectives.items()])
    unit_locs = ", ".join([f"{u}@{loc}" for u, loc in st.session_state.locations.items()])
    
    enriched_prompt = f"""
    [SYSTEM_STATE] Time:{st.session_state.mission_time}m | Viability:{st.session_state.viability}% | Locations:{unit_locs} | Objectives:{obj_status}
    [PROTOCOL_REMINDER] Squad is currently in 'Able Executor' mode. Do not change POIs without authorization.
    [COMMANDER_ORDERS] {prompt}

    [MANDATORY_RESPONSE_GUIDE] 
    1. Direct Dialogue: Provide SITREPs for SAM, DAVE, and MIKE. 
    2. Data Suffix: You MUST end with exactly:
       [LOC_DATA: SAM=Loc, DAVE=Loc, MIKE=Loc]
       [OBJ_DATA: obj_id=TRUE] (Only if a task was just finished!)
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

    # After receiving response_text from Gemini
    win_trigger = "Mission Complete: Assets in Transit"
    
    if win_trigger.lower() in response_text.lower():
        # Calculate time taken
        start_time = 60
        time_remaining = st.session_state.mission_time
        st.session_state.time_elapsed = start_time - time_remaining
        st.session_state.mission_complete = True        

    # D. Clean and Parse
    clean_response = re.sub(r"\[(LOC_DATA|OBJ_DATA):.*?\]", "", response_text).strip()

    # Create the split dictionary for the UI and Map Bubbles
    split_dialogue = parse_operative_dialogue(clean_response)

    # Store the split dict instead of just the string
    st.session_state.messages.append({
        "role": "assistant", 
        "content": split_dialogue,
        "raw_text": clean_response # Keep raw text just in case
    })

    return clean_response



# --- UI LAYOUT ---
with st.sidebar:
    st.header("🦅 GUNDOG C2")
    
    # Dual-Metric HUD
    st.progress(st.session_state.viability / 100, text=f"PLAUSIBLE DENIABILITY: {st.session_state.viability}%")
    
    st.metric(label="MISSION TIME REMAINING", value=f"{st.session_state.mission_time} MIN")
    
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


# --- REFACTORED UI LAYOUT ---

if st.session_state.get("mission_complete", False):
    # --- MISSION SUCCESS UI (Kept as is) ---
    st.balloons()
    st.markdown("<h1 style='text-align: center; color: #00FF00;'>🏁 MISSION COMPLETE!</h1>", unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        st.metric("TOTAL MISSION TIME", f"{st.session_state.get('time_elapsed', 0)} MIN")
        st.metric("VIABILITY REMAINING", f"{st.session_state.viability}%")
        if st.button("REDEPLOY (NEW MISSION)"):
            st.session_state.clear()
            st.rerun()
else:
    # --- 1. DEFINE ASSETS (Fixing the 'not defined' error) ---
    # These must be defined before the Map logic uses them
    sam_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/sam-map1.png", icon_size=(45, 45))
    dave_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/dave-map1.png", icon_size=(45, 45))
    mike_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/mike-map1.png", icon_size=(45, 45))

    # --- 2. TOP ROW: FULL-WIDTH TACTICAL MAP ---
       
    m = folium.Map(location=[9.3525, -79.9100], zoom_start=15, tiles="CartoDB dark_matter")
    
    # Discovery & POI Render
    for loc_id, info in MISSION_DATA.items():
        is_discovered = loc_id in st.session_state.discovered_locations
        marker_color = "#00FF00" 
        fill_opac = 0.2 if is_discovered else 0.02
        
        if is_discovered:
            loc_img_url = get_image_url(info["image"])
            popup_html = f'<div style="width:200px;background:#000;padding:10px;border:1px solid #0f0;"><h4 style="color:#0f0;">{info["name"]}</h4><img src="{loc_img_url}" width="100%"><p style="color:#0f0;font-size:10px;">{info["intel"]}</p></div>'
        else:
            popup_html = f'<div style="width:150px;background:#000;padding:10px;"><h4 style="color:#666;">{info["name"]}</h4><p style="color:#666;font-size:10px;">[RECON REQUIRED]</p></div>'

        folium.Circle(location=info["coords"], radius=45, color=marker_color, fill=True, fill_opacity=fill_opac).add_to(m)
        folium.Marker(location=info["coords"], icon=folium.DivIcon(html=f'<div style="font-family:monospace;font-size:8pt;color:{marker_color};text-shadow:1px 1px #000;">{info["name"].upper()}</div>'), popup=folium.Popup(popup_html, max_width=250)).add_to(m)

    # Squad Tokens & Bubbles Logic
    tokens = {"SAM": sam_token, "DAVE": dave_token, "MIKE": mike_token}
    icon_offsets = {"SAM": [0.00015, 0], "DAVE": [-0.0001, 0.00015], "MIKE": [-0.0001, -0.00015]}
    bubble_offsets = {"SAM": [0.0008, 0.0000], "DAVE": [-0.0005, 0.0008], "MIKE": [-0.0005, -0.0008]}

    latest_msg = st.session_state.messages[-1] if st.session_state.messages else None
    current_comms = latest_msg["content"] if (latest_msg and isinstance(latest_msg["content"], dict)) else {}

    for unit, icon in tokens.items():
        current_loc = st.session_state.locations.get(unit, "Insertion Point")
        target_poi = next((info for info in MISSION_DATA.values() if info['name'].lower() == current_loc.lower()), list(MISSION_DATA.values())[0])
        final_coords = [target_poi["coords"][0] + icon_offsets[unit][0], target_poi["coords"][1] + icon_offsets[unit][1]]
        
        folium.Marker(final_coords, icon=icon, tooltip=unit).add_to(m)

        if unit in current_comms:
            b_off = bubble_offsets[unit]
            bubble_html = f"""<div style="background:rgba(0,0,0,0.9); border:1px solid #0f0; color:#0f0; padding:8px; border-radius:10px; font-size:9pt; width:180px; font-family:monospace; box-shadow:2px 2px 10px #000;"><b style="color:white;display:block;margin-bottom:3px;">{unit}</b>{current_comms[unit]}</div>"""
            folium.Marker([final_coords[0]+b_off[0], final_coords[1]+b_off[1]], icon=folium.DivIcon(icon_size=(200,100), html=bubble_html)).add_to(m)

    st_folium(m, height=550, use_container_width=True, key="tactical_hud_v6")

    st.divider()

    # --- 3. BOTTOM ROW: TWO COLUMNS (CHAT & DASHBOARD) ---
    col_chat, col_dash = st.columns([0.6, 0.4])

    with col_chat:
        with st.container(height=400, border=True):
            # Startup trigger (unchanged)
            if not st.session_state.messages:
                with st.spinner("Establishing Satellite Uplink..."):
                    get_dm_response("Team is at the insertion point. Report in.")
                    st.rerun()

            if prompt := st.chat_input("Issue Commands..."):
                st.session_state.mission_time -= 1 
                st.session_state.messages.append({"role": "user", "content": prompt})
                get_dm_response(prompt)
                st.rerun() 
             
             
            for msg in st.session_state.messages:
                if msg["role"] == "user":
                    st.markdown(f"**COMMANDER:** {msg['content']}")
                elif isinstance(msg["content"], dict):
                    for op, text in msg["content"].items():
                        st.markdown(f"*{op}:* {text}")
        
        

    with col_dash:
        m1, m2 = st.columns(2)
        m1.metric("TIME", f"{st.session_state.mission_time}m")
        m2.metric("DENIABILITY", f"{st.session_state.viability}%")
        
        st.progress(st.session_state.viability / 100)
        
        st.subheader("🎯 OBJECTIVES")
        for obj_id, status in st.session_state.objectives.items():
            label = obj_id.replace('obj_', '').replace('_', ' ').title()
            st.write(f"{'✅' if status else '◽'} {label}")


import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime
import folium
from streamlit_folium import st_folium

# --- CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="Gundogs C2: Cristobal HUD", initial_sidebar_state="collapsed")

def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except:
        pass

local_css("style.css")

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

MISSION_DATA = load_mission('mission_data.xml')

def get_initial_objectives(file_path):
    tree = ET.parse(file_path)
    return {t.get('id'): (t.get('status').lower() == 'true') for t in tree.findall('.//task')}

if "objectives" not in st.session_state:
    st.session_state.objectives = get_initial_objectives('mission_data.xml')

if "viability" not in st.session_state:
    st.session_state.update({
        "viability": 100,
        "mission_time": 60,
        "messages": [],
        "chat_session": None,
        "efficiency_score": 1000,
        "locations": {"SAM": "Insertion Point", "DAVE": "Insertion Point", "MIKE": "Insertion Point"},
        "discovered_locations": [],
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

@st.cache_data(ttl=3600)
def get_image_url(filename):
    if not filename: return ""
    try:
        client = get_gcs_client()
        blob = client.bucket(BUCKET_NAME).blob(f"cinematics/{filename}")
        return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))
    except: return ""

def parse_operative_dialogue(text):
    pattern = r"(SAM|DAVE|MIKE):\s*(.*?)(?=\s*(?:SAM|DAVE|MIKE):|$)"
    segments = re.findall(pattern, text, re.DOTALL)
    cleaned_dict = {}
    for name, msg in segments:
        m = msg.strip().replace("**", "").strip('"').strip("'")
        cleaned_dict[name] = m
    return cleaned_dict

# --- AI ENGINE LOGIC ---
def get_dm_response(prompt):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"temperature": 0.3})

    mission_tree = ET.parse("mission_data.xml")
    mission_root = mission_tree.getroot()
    intent = mission_root.find("intent")
    
    if st.session_state.chat_session is None:
        location_logic = "".join([f"- {poi.find('name').text}\n" for poi in mission_root.findall(".//poi")])
        sys_instr = f"THEATER: {intent.find('theater').text}\nYOU ARE: PMC Tactical Multiplexer. End with [LOC_DATA: SAM=Loc, DAVE=Loc, MIKE=Loc] and [OBJ_DATA: obj_id=TRUE]. PROTOCOL: Multi-unit reporting (SAM, DAVE, MIKE) required."
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    enriched_prompt = f"[SYSTEM_STATE] Time:{st.session_state.mission_time}m | Viability:{st.session_state.viability}% | Commander Orders: {prompt}"
    response_text = st.session_state.chat_session.send_message(enriched_prompt).text

    # Suffix Data Parsing
    loc_match = re.search(r"\[LOC_DATA: (SAM=[^,]+, DAVE=[^,]+, MIKE=[^\]]+)\]", response_text)
    if loc_match:
        for pair in loc_match.group(1).split(", "):
            unit, loc = pair.split("=")
            st.session_state.locations[unit] = loc.strip()

    # Discovery Logic
    for unit, loc_name in st.session_state.locations.items():
        target_poi_id = next((pid for pid, info in MISSION_DATA.items() if info['name'] == loc_name), None)
        if target_poi_id and target_poi_id not in st.session_state.discovered_locations:
            st.session_state.discovered_locations.append(target_poi_id)
            st.toast(f"📡 New Intel: {loc_name}")

    clean_response = re.sub(r"\[(LOC_DATA|OBJ_DATA):.*?\]", "", response_text).strip()
    st.session_state.messages.append({"role": "assistant", "content": parse_operative_dialogue(clean_response)})
    return clean_response

# --- UI LAYOUT ---

# 1. TOP ROW: TACTICAL HUD


st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        .stVerticalBlock {gap: 0.3rem !important;}
        [data-testid="stMetric"] {background: rgba(0,255,0,0.05); padding: 5px; border-radius: 5px;}
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Define Map and Assets
m = folium.Map(location=[9.3525, -79.9100], zoom_start=15, tiles="CartoDB dark_matter")

# Markers & Discovery
for loc_id, info in MISSION_DATA.items():
    is_discovered = loc_id in st.session_state.discovered_locations
    folium.Circle(location=info["coords"], radius=40, color="#0f0", fill=True, fill_opacity=0.2 if is_discovered else 0.02).add_to(m)
    folium.Marker(location=info["coords"], icon=folium.DivIcon(html=f'<div style="font-family:monospace;font-size:8pt;color:{"#0f0" if is_discovered else "#444"};">{info["name"].upper()}</div>')).add_to(m)

# Squad restoral
sam_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/sam-map1.png", icon_size=(45, 45))
dave_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/dave-map1.png", icon_size=(45, 45))
mike_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/mike-map1.png", icon_size=(45, 45))
tokens = {"SAM": sam_token, "DAVE": dave_token, "MIKE": mike_token}
offsets = {"SAM": [0.00015, 0], "DAVE": [-0.0001, 0.00015], "MIKE": [-0.0001, -0.00015]}
b_offsets = {"SAM": [0.0007, 0.0004], "DAVE": [-0.0003, 0.0006], "MIKE": [0.0007, -0.0004]}

latest_msg = st.session_state.messages[-1] if st.session_state.messages else None
current_comms = latest_msg["content"] if (latest_msg and isinstance(latest_msg["content"], dict)) else {}

for unit, icon in tokens.items():
    loc_name = st.session_state.locations.get(unit, "Insertion Point")
    poi = next((info for info in MISSION_DATA.values() if info['name'].lower() == loc_name.lower()), list(MISSION_DATA.values())[0])
    coords = [poi["coords"][0] + offsets[unit][0], poi["coords"][1] + offsets[unit][1]]
    folium.Marker(coords, icon=icon, tooltip=unit).add_to(m)
    
    if unit in current_comms:
        b_pos = [coords[0] + b_offsets[unit][0], coords[1] + b_offsets[unit][1]]
        bubble_html = f'<div style="background:rgba(0,0,0,0.85); border:1px solid #0f0; color:#0f0; padding:6px; border-radius:5px; font-size:8.5pt; width:160px; font-family:monospace; box-shadow:2px 2px 5px #000;"><b>{unit}</b><br>{current_comms[unit]}</div>'
        folium.Marker(b_pos, icon=folium.DivIcon(icon_size=(180,100), html=bubble_html)).add_to(m)

st_folium(m, height=450, use_container_width=True, key="map_v8")

# 2. BOTTOM TIER: 2-COLUMN CONTROL DECK
col_left, col_right = st.columns([0.65, 0.35], gap="small")

with col_left:
    # INPUT BAR LOCKED ABOVE LOG
    if prompt := st.chat_input("TRANSMIT COMMANDS..."):
        st.session_state.mission_time -= 1 
        st.session_state.messages.append({"role": "user", "content": prompt})
        get_dm_response(prompt)
        st.rerun()

    
    with st.container(height=280, border=True):
         for msg in reversed(st.session_state.messages):
             if msg["role"] == "user":
                 st.markdown(f"**> CMD:** `{msg['content']}`")
             elif isinstance(msg["content"], dict):
                 for op, text in msg["content"].items():
                     st.markdown(f"**{op}:** {text}")

with col_right:
    m1, m2 = st.columns(2)
    m1.metric("TIME", f"{st.session_state.mission_time}m")
    m2.metric("VIS", f"{st.session_state.viability}%")

    
    with st.expander("🎯 OBJECTIVES", expanded=True):
        for obj_id, status in st.session_state.objectives.items():
            st.caption(f"{'✅' if status else '◽'} {obj_id.replace('obj_', '').title()}")

# Startup Trigger
if not st.session_state.messages:
    get_dm_response("Report in.")
    st.rerun()
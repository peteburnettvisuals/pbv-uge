import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime
import folium
from streamlit_folium import st_folium

# --- 1. CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="Gundogs C2: Cristobal HUD", initial_sidebar_state="collapsed")

if "locations" not in st.session_state:
    st.session_state.locations = {
        "SAM": "insertion_point", 
        "DAVE": "insertion_point", 
        "MIKE": "insertion_point"
    }

def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except: pass

local_css("style.css")

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

if "objectives" not in st.session_state:
    tree = ET.parse('mission_data.xml')
    st.session_state.objectives = {t.get('id'): (t.get('status').lower() == 'true') for t in tree.findall('.//task')}

if "viability" not in st.session_state:
    st.session_state.update({
        "viability": 100, "mission_time": 60, "messages": [], "chat_session": None,
        "locations": {"SAM": "Insertion Point", "DAVE": "Insertion Point", "MIKE": "Insertion Point"},
        "discovered_locations": [],
    })

def parse_operative_dialogue(text):
    pattern = r"(SAM|DAVE|MIKE):\s*(.*?)(?=\s*(?:SAM|DAVE|MIKE):|$)"
    segments = re.findall(pattern, text, re.DOTALL)
    cleaned_dict = {}
    for name, msg in segments:
        m = msg.strip().replace("**", "").strip('"').strip("'")
        cleaned_dict[name] = m
    return cleaned_dict

def get_dm_response(prompt):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash', generation_config={"temperature": 0.3})
    mission_tree = ET.parse("mission_data.xml")
    mission_root = mission_tree.getroot()
    intent = mission_root.find("intent")
    
    if st.session_state.chat_session is None:
        sys_instr = f"THEATER: {intent.find('theater').text}\nYOU ARE: PMC Tactical Multiplexer. End with [LOC_DATA: SAM=Loc, DAVE=Loc, MIKE=Loc] and [OBJ_DATA: obj_id=TRUE]. PROTOCOL: Multi-unit reporting (SAM, DAVE, MIKE) required."
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    enriched_prompt = f"[SYSTEM_STATE] Time:{st.session_state.mission_time}m | Viability:{st.session_state.viability}% | Commander Orders: {prompt}"
    response_text = st.session_state.chat_session.send_message(enriched_prompt).text

    # Update Locations
    loc_match = re.search(r"\[LOC_DATA: (SAM=[^,]+, DAVE=[^,]+, MIKE=[^\]]+)\]", response_text)
    if loc_match:
        for pair in loc_match.group(1).split(", "):
            unit, loc = pair.split("=")
            st.session_state.locations[unit] = loc.strip()

    # Clean & Parse
    clean_response = re.sub(r"\[(LOC_DATA|OBJ_DATA):.*?\]", "", response_text).strip()
    split_dialogue = parse_operative_dialogue(clean_response)

    # Save to history: 'content' is the dict for map, 'display_text' is for the log
    st.session_state.messages.append({"role": "assistant", "content": split_dialogue, "display_text": clean_response})
    return clean_response

# --- 2. LOGIC ENGINE (Crucial: Process state BEFORE drawing) ---

# Startup Trigger: Forces the first SITREP if none exists
if not any(msg.get("role") == "assistant" for msg in st.session_state.messages):
    get_dm_response("Team is at the insertion point. Give me a full SITREP.")
    st.rerun()

# Aggressive Comms Search: Finds the most recent radio chatter dictionary
latest_assistant = next((msg for msg in reversed(st.session_state.messages) if msg.get("role") == "assistant"), None)
current_comms = latest_assistant["content"] if (latest_assistant and isinstance(latest_assistant.get("content"), dict)) else {}

# --- 3. UI RENDERING ---

st.markdown("""
    <style>
        .block-container {padding-top: 1rem; padding-bottom: 0rem;}
        [data-testid="column"] {margin-top: -65px !important;}
        .stVerticalBlock {gap: 0rem !important;}
        .stButton button {width: 100%; background-color: rgba(255,0,0,0.1); border: 1px solid #ff4b4b; color: #ff4b4b;}
        .stButton button:hover {background-color: rgba(255,0,0,0.3); border: 1px solid #ff4b4b;}
    </style>
""", unsafe_allow_html=True)

# Assets
sam_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/sam-map1.png", icon_size=(45, 45))
dave_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/dave-map1.png", icon_size=(45, 45))
mike_token = folium.CustomIcon("https://peteburnettvisuals.com/wp-content/uploads/2026/01/mike-map1.png", icon_size=(45, 45))
tokens = {"SAM": sam_token, "DAVE": dave_token, "MIKE": mike_token}
offsets = {"SAM": [0.00035, 0], "DAVE": [-0.00025, 0.00035], "MIKE": [-0.00025, -0.00035]}
b_offsets = {"SAM": [0.0008, 0.0002], "DAVE": [-0.0004, 0.0007], "MIKE": [0.0008, -0.0004]}

m = folium.Map(location=[9.3525, -79.9100], zoom_start=15, tiles="CartoDB dark_matter")

# Map Markers (Static POIs)
for loc_id, info in MISSION_DATA.items():
    is_discovered = loc_id in st.session_state.discovered_locations
    folium.Circle(location=info["coords"], radius=40, color="#0f0", fill=True, fill_opacity=0.2 if is_discovered else 0.02).add_to(m)
    folium.Marker(location=info["coords"], icon=folium.DivIcon(html=f'<div style="font-family:monospace;font-size:8pt;color:{"#0f0" if is_discovered else "#999"};">{info["name"].upper()}</div>')).add_to(m)

# Squad Render Loop
for unit, icon in tokens.items():
    # Get the ID (e.g., 'insertion_point')
    loc_id = st.session_state.locations.get(unit, "insertion_point")
    
    # Find the POI by ID first, then fall back to name, then first available
    poi = MISSION_DATA.get(loc_id) or \
          next((info for info in MISSION_DATA.values() if info['name'].lower() == loc_id.lower()), 
          list(MISSION_DATA.values())[0])
    
    # Now the team will have a real lat/long to stand on
    coords = [poi["coords"][0] + offsets[unit][0], poi["coords"][1] + offsets[unit][1]]
    folium.Marker(coords, icon=icon, tooltip=unit).add_to(m)
    
    # Render Bubble only if dialogue exists in current_comms
    if unit in current_comms:
        b_pos = [coords[0] + b_offsets[unit][0], coords[1] + b_offsets[unit][1]]
        bubble_html = f'<div style="background:rgba(0,0,0,0.85); border:1px solid #0f0; color:#0f0; padding:8px; border-radius:5px; font-size:9pt; width:180px; font-family:monospace; box-shadow:2px 2px 10px #000;"><b>{unit}</b><br>{current_comms[unit]}</div>'
        folium.Marker(b_pos, icon=folium.DivIcon(icon_size=(200,120), html=bubble_html)).add_to(m)

# 🗺️ HERO MAP
st_folium(m, height=700, use_container_width=True, key="tactical_hud_final")

# 🖥️ CONTROL CONSOLE
col_left, col_right = st.columns([0.65, 0.35], gap="small")

with col_left:
    if prompt := st.chat_input("TRANSMIT COMMANDS..."):
        st.session_state.mission_time -= 1 
        st.session_state.messages.append({"role": "user", "content": prompt})
        get_dm_response(prompt)
        st.rerun()

    with st.container(height=280, border=True):
         for msg in reversed(st.session_state.messages):
             if msg["role"] == "user": st.markdown(f"**> CMD:** `{msg['content']}`")
             elif "content" in msg and isinstance(msg["content"], dict):
                 for op, text in msg["content"].items(): st.markdown(f"**{op}:** {text}")

with col_right:
    m1, m2 = st.columns(2)
    m1.metric("TIME", f"{st.session_state.mission_time}m")
    m2.metric("VIS", f"{st.session_state.viability}%")
    st.progress(st.session_state.viability / 100)
    
    with st.expander("🎯 OBJECTIVES", expanded=True):
        for obj_id, status in st.session_state.objectives.items():
            st.caption(f"{'✅' if status else '◽'} {obj_id.replace('obj_', '').title()}")
    
    # ABORT BUTTON (At the very bottom of the dashboard)
    if st.button("🚨 ABORT MISSION"):
        st.session_state.clear()
        st.rerun()
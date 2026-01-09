import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import json
import datetime

# --- 1. INITIALIZE SESSION STATE ---
# Following the ULE pattern: We initialize the AI session once and persist it.
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 25,
        "inventory": [],
        "messages": [],
        "current_waypoint": "1.1",
        "current_scene_image": "oakhaven_overview_21x9.jpg", 
        "current_overlay_image": None,
        "objectives": [{"task": "Find Silver Weapon", "done": False}, {"task": "Get Bane-Oil", "done": False}],
        "chat_session": None  # Placeholder for ULE-style session
    })

# --- 2. FUNCTION LIBRARY ---
BUCKET_NAME = "uge-repository-cu32"

@st.cache_resource
def get_gcs_client():
    from google.oauth2 import service_account
    from google.cloud import storage
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def load_poc_assets():
    client = get_gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    world_blob = bucket.blob("world_atlas_oakhaven.xml")
    mission_blob = bucket.blob("mission_warlock_malakor.xml")
    return ET.fromstring(world_blob.download_as_text()), ET.fromstring(mission_blob.download_as_text())

def get_image_url(filename):
    client = get_gcs_client()
    blob = client.bucket(BUCKET_NAME).blob(f"cinematics/{filename}")
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))

def process_dm_output(raw_text):
    """Parses hidden tags and updates session state."""
    scene_match = re.search(r"\[SET_SCENE: set_scene\((.*?)\)\]", raw_text)
    if scene_match:
        st.session_state.current_scene_image = f"{scene_match.group(1)}.jpg"

    overlay_match = re.search(r"\[SET_OVERLAY: set_overlay\((.*?)\)\]", raw_text)
    if overlay_match:
        st.session_state.current_overlay_image = overlay_match.group(1)
    else:
        st.session_state.current_overlay_image = None
    
    item_matches = re.findall(r"\[GIVE_ITEM: (.*?): (.*?)\]", raw_text)
    for name, weight in item_matches:
        st.session_state.inventory.append({"name": name, "weight": float(weight)})
        st.toast(f"🎒 Picked up: {name}")

    mana_match = re.search(r"\[MANA_MOD: (.*?)\]", raw_text)
    if mana_match:
        st.session_state.mana += int(mana_match.group(1))

    obj_match = re.search(r"\[OBJ_COMPLETE: (.*?)\]", raw_text)
    if obj_match:
        idx = int(obj_match.group(1))
        if idx < len(st.session_state.objectives):
            st.session_state.objectives[idx]["done"] = True

    return re.sub(r"\[.*?\]", "", raw_text).strip()

def get_dm_response(prompt):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash-exp', 
                                 generation_config={"temperature": 0.4}) # Slightly higher temp for "Inventive" prose

    world_atlas, mission_script = load_poc_assets()
    wp = mission_script.find(f".//waypoint[@id='{st.session_state.current_waypoint}']")
    loc = world_atlas.find(f".//location[@id='{wp.get('loc_ref')}']")

    # Initialize session if it doesn't exist (THE ULE TRANSPLANT)
    if st.session_state.chat_session is None:
        sys_instr = f"""
        ROLE: You are the Master Narrator. Your tone is genial, atmospheric, and highly immersive.
        
        SOURCE OF TRUTH (XML DATA):
        - LOCATION: {loc.get('name')}
        - DESCRIPTION: {loc.find('internal_desc').text}
        - MISSION: {wp.find('desc').text}

        INTUITION-BASED RULES:
        1. NO LISTS: Never provide a/b/c options. Instead, describe the world so vividly that the player's next move feels natural. Ask them what they want to do.
        2. ENCOURAGE INTUITION: If the player is stuck, describe a feeling—a chill down their spine, a smell on the wind—that subtly hints at canonical points of interest in the XML.
        3. ON-BOOK FLAVOR: You are free to invent the "mist" or "distant thunder," but do not invent new NPCs or buildings. If they aren't in the XML, they aren't there.
        4. FIRST TURN: If the user says 'start', provide a cinematic "Welcome" introduction to Oakhaven that sets the stakes and ends with a prompt for their first move.
        5. UI SIGNALING: Use [SET_OVERLAY: filename] when the player interacts with a canonical NPC.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    # Standard interaction
    response = st.session_state.chat_session.send_message(prompt)
    return response.text

# --- 3. DYNAMIC CSS CONFIGURATION (Jumbo Theme) ---
st.set_page_config(layout="wide", page_title="UGE: Warlock PoC")
st.markdown("""
    <style>
    .stApp { background: linear-gradient(180deg, #FFFFFF 0%, #D1D5DB 100%); background-attachment: fixed; }
    h1 { font-size: 3.5rem !important; }
    [data-testid="stCaptionContainer"] { font-size: 1.6rem !important; font-weight: 600 !important; }
    .stTabs [data-baseweb="tab"] div { font-size: 1.8rem !important; font-weight: 800 !important; }
    .stTabs [data-baseweb="tab"] { height: 70px !important; }
    [data-testid="stVerticalBlock"] p, [data-testid="stVerticalBlock"] li, [data-testid="stCheckbox"] label p {
        font-size: 1.5rem !important; line-height: 1.8 !important; color: #1A1C23 !important;
    }
    [data-testid="stCheckbox"] div[role="checkbox"] { width: 35px !important; height: 35px !important; }
    .stChatInput { padding-bottom: 20px !important; }
    [data-testid="stChatInput"] textarea { font-size: 1.4rem !important; padding: 15px !important; min-height: 60px !important; }
    .fixed-footer { position: fixed; bottom: 0; left: 0; width: 100%; background-color: #111827; color: #00FF41; padding: 15px 0; z-index: 999; border-top: 2px solid #00FF41; font-family: 'Courier New', Courier, monospace; }
    .footer-content { display: flex; justify-content: space-around; font-weight: bold; font-size: 1.3rem; }
    .main .block-container { padding-bottom: 150px; }
    </style>
""", unsafe_allow_html=True)

# --- 4. THE UI LAYOUT (Twin-Column) ---

if not st.session_state.messages:
    with st.spinner("The Narrator is preparing the stage..."):
        # We send a hidden 'start' prompt to trigger the first turn rules
        raw_response = get_dm_response("start")
        clean_narrative = process_dm_output(raw_response)
        st.session_state.messages.append({"role": "assistant", "content": clean_narrative})
        st.rerun()

col_visual, col_interaction = st.columns([1.2, 1], gap="large")

with col_visual:
    st.title("The Warlock of Certain Death Mountain")
    st.caption("Chapter 1: The Village of Oakhaven")
    
    # 21:9 Scene Image (Pinned)
    scene_url = get_image_url(st.session_state.current_scene_image)
    st.image(scene_url, use_column_width=True)
    
    # CHARACTER PORTRAIT (ULE Pattern)
    if st.session_state.current_overlay_image:
        overlay_url = get_image_url(st.session_state.current_overlay_image)
        # We wrap this in a container to give it some separation from the landscape
        st.markdown("<br>", unsafe_allow_html=True)
        st.image(overlay_url, width=400, caption="Current Interaction")

with col_interaction:
    tab_act, tab_inv, tab_obj = st.tabs(["Activity", "Inventory", "Objectives"])
    with tab_act:
        with st.container(height=550):
            for msg in st.session_state.messages:
                st.chat_message(msg["role"]).write(msg["content"])
        
        if prompt := st.chat_input("What is your move?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            raw_response = get_dm_response(prompt)
            clean_narrative = process_dm_output(raw_response)
            st.session_state.messages.append({"role": "assistant", "content": clean_narrative})
            st.rerun()

    with tab_inv:
        st.write("### Your Gear")
        if not st.session_state.inventory: st.info("No items carried.")
        for item in st.session_state.inventory: st.write(f"• {item['name']} ({item['weight']}kg)")

    with tab_obj:
        st.write("### Mission Intent")
        for obj in st.session_state.objectives:
            st.checkbox(obj['task'], value=obj['done'], disabled=True)

# 5. RENDER THE PINNED HUD
total_weight = sum(item['weight'] for item in st.session_state.inventory)
st.markdown(f"""
    <div class="fixed-footer">
        <div class="footer-content">
            <span>MANA_SIGNATURE: {st.session_state.mana}%</span>
            <span>PACK_WEIGHT: {total_weight}kg / 20kg</span>
            <span>WAYPOINT: {st.session_state.current_waypoint}</span>
        </div>
    </div>
""", unsafe_allow_html=True)
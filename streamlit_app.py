import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import json
import datetime

# --- 1. INITIALIZE SESSION STATE FIRST ---
# This ensures 'current_scene_image' exists before the CSS tries to use it
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 25,
        "inventory": [],
        "messages": [],
        "current_waypoint": "1.1",
        "current_scene_image": "oakhaven_overview_21x9.jpg", 
        "current_overlay_image": None,
        "objectives": [{"task": "Find Silver Weapon", "done": False}, {"task": "Get Bane-Oil", "done": False}]
    })

# --- 1. FUNCTION LIBRARY ---
BUCKET_NAME = "uge-repository-cu32"

@st.cache_resource
def get_gcs_client():
    from google.oauth2 import service_account
    from google.cloud import storage
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])


def load_poc_assets():
    """Pulls the decoupled XML files from the GCS bucket root."""
    client = get_gcs_client()
    bucket = client.bucket(BUCKET_NAME)
    
    # Pulling the two separate libraries
    world_blob = bucket.blob("world_atlas_oakhaven.xml")
    mission_blob = bucket.blob("mission_warlock_malakor.xml")
    
    world_xml = ET.fromstring(world_blob.download_as_text())
    mission_xml = ET.fromstring(mission_blob.download_as_text())
    
    return world_xml, mission_xml

def get_image_url(filename):
    """Fetch signed URL for the 21:9 cinematic assets."""
    client = get_gcs_client()
    # Assuming images are in a folder called 'cinematics' in your bucket
    blob = client.bucket(BUCKET_NAME).blob(f"cinematics/{filename}")
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))

def process_dm_output(raw_text):
    """
    Parses hidden tags and updates session state.
    Tags: [SET_SCENE:ID], [GIVE_ITEM:NAME:WEIGHT], [MANA_MOD:X], [OBJ_COMPLETE:INDEX]
    """
    # 1. Handle Scene Changes
    # This regex now looks for the 'set_scene' command within brackets
    # Matches: [SET_SCENE: set_scene(tavern_interior_21x9)]
    scene_match = re.search(r"\[SET_SCENE: set_scene\((.*?)\)\]", raw_text)
    if scene_match:
        asset_id = scene_match.group(1)
        # Add the extension back if your bucket needs it
        st.session_state.current_scene_image = f"{asset_id}.jpg"

    # 2. Handle NPC Overlay (Silhouette/Character)
    overlay_match = re.search(r"\[SET_OVERLAY: set_overlay\((.*?)\)\]", raw_text)
    if overlay_match:
        st.session_state.current_overlay_image = overlay_match.group(1)
    else:
        # Clear overlay if no NPC is currently engaged
        st.session_state.current_overlay_image = None
    
    # 2. Handle Inventory Additions
    item_matches = re.findall(r"\[GIVE_ITEM: (.*?): (.*?)\]", raw_text)
    for name, weight in item_matches:
        st.session_state.inventory.append({"name": name, "weight": float(weight)})
        st.toast(f"🎒 Picked up: {name}")

    # 3. Handle Mana Adjustments
    mana_match = re.search(r"\[MANA_MOD: (.*?)\]", raw_text)
    if mana_match:
        st.session_state.mana += int(mana_match.group(1))

    # 4. Handle Objective Updates
    obj_match = re.search(r"\[OBJ_COMPLETE: (.*?)\]", raw_text)
    if obj_match:
        idx = int(obj_match.group(1))
        if idx < len(st.session_state.objectives):
            st.session_state.objectives[idx]["done"] = True

    # Remove all tags from the text before displaying to player
    clean_text = re.sub(r"\[.*?\]", "", raw_text).strip()
    return clean_text

def get_dm_response(prompt):
    # 1. Configuration (Usually stored in st.secrets)
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash')

    # 2. Context Injection (The 'Decoupled' logic)
    # We pull the specific waypoint and world data from our ingested XMLs
    world_atlas, mission_script = load_poc_assets()
    
    current_wp_id = st.session_state.current_waypoint
    wp_node = mission_script.find(f".//waypoint[@id='{current_wp_id}']")
    
    # SAFETY CHECK: If waypoint or location is missing, use defaults
    loc_name = "Unknown Wilds"
    loc_desc = "A mysterious area."
    mission_desc = "Continue your journey."

    if wp_node is not None:
        mission_desc = wp_node.find('desc').text if wp_node.find('desc') is not None else mission_desc
        loc_ref = wp_node.get('loc_ref')
        loc_node = world_atlas.find(f".//location[@id='{loc_ref}']")
        if loc_node is not None:
            loc_name = loc_node.get('name')
            # Look for internal_desc instead of base_desc to match your latest XML
            loc_desc = loc_node.find('internal_desc').text if loc_node.find('internal_desc') is not None else loc_desc

    sys_instr = f"""
    You are the Narrator for 'Warlock of Certain Death Mountain'.
    CURRENT LOCATION: {loc_name} - {loc_desc}
    MISSION CONTEXT: {mission_desc}
    
    UI CONTROL PROTOCOL:
    You MUST use these tags to drive the UI. Do not show them to the player.
    - [SET_SCENE: LOC_ID] Use this if the player moves to a new location.
    - [GIVE_ITEM: Name: Weight] (Example: [GIVE_ITEM: Rusty Key: 0.1])
    - [MANA_MOD: +/-X] (Example: [MANA_MOD: 10] if they use magic)
    - [OBJ_COMPLETE: Index] (Use 0 for 'Find Weapon', 1 for 'Get Oil')

    INVENTORY: {st.session_state.inventory}
    """

    # 3. Generate content with history for continuity
    # We pass the last few messages to keep the thread alive
    chat = model.start_chat(history=[])
    response = chat.send_message([sys_instr, prompt])
    
    return response.text

def package_save_state():
    """Packages current session variables into a serializable dictionary."""
    save_data = {
        "metadata": {
            "timestamp": datetime.datetime.now().isoformat(),
            "waypoint": st.session_state.current_waypoint
        },
        "stats": {
            "mana": st.session_state.mana,
            "pack_weight": sum(item['weight'] for item in st.session_state.inventory)
        },
        "inventory": st.session_state.inventory,
        "objectives": st.session_state.objectives,
        "history": st.session_state.messages[-10:] # Keep the last 10 lines for context
    }
    return save_data

# --- 2. DYNAMIC CSS CONFIGURATION ---
st.set_page_config(layout="centered", page_title="UGE: Warlock PoC")

st.markdown("""
    <style>
    /* 1. Main Background Gradient */
    .stApp {
        background: linear-gradient(180deg, #FFFFFF 0%, #D1D5DB 100%);
        background-attachment: fixed;
    }

    /* 2. Containerizing the Main Content Area */
    .main .block-container {
        max-width: 800px;
        padding-bottom: 120px; /* Space for the pinned footer */
    }

    /* 3. Fixed-Height Chat Window */
    /* This prevents the page from expanding vertically forever */
    [data-testid="stChatMessageContainer"] {
        max-height: 500px;
        overflow-y: auto;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 10px;
        background: #F9FAFB;
    }

    /* 4. PINNED HUD FOOTER */
    .fixed-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 100%;
        background-color: #111827; /* Dark charcoal */
        color: #00FF41; /* Terminal green */
        padding: 15px 0;
        text-align: center;
        z-index: 999;
        border-top: 2px solid #00FF41;
        font-family: 'Courier New', Courier, monospace;
    }
    
    .footer-content {
        display: flex;
        justify-content: space-around;
        max-width: 800px;
        margin: 0 auto;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 4. THE UI LAYOUT ---

st.title("The Warlock of Certain Death Mountain")
st.caption("Chapter 1: The Village of Oakhaven")

tab_act, tab_inv, tab_obj = st.tabs(["Activity", "Inventory", "Objectives"])

with tab_act:
    # 1. Image Header (Inside the tab)
    scene_url = get_image_url(st.session_state.current_scene_image)
    st.image(scene_url, use_column_width=True)
    
    # 2. Containerized Chat Area
    # Streamlit's container(height=...) automatically handles the scrolling/pinning
    with st.container(height=500):
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).write(msg["content"])
    
    # 3. Input pinned just below the chat box
    if prompt := st.chat_input("What is your move?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        raw_response = get_dm_response(prompt)
        clean_narrative = process_dm_output(raw_response)
        st.session_state.messages.append({"role": "assistant", "content": clean_narrative})
        st.rerun()

    with tab_inv:
        st.write("### Your Gear")
        if not st.session_state.inventory:
            st.info("No items carried.")
        for item in st.session_state.inventory:
            st.write(f"• {item['name']} ({item['weight']}kg)")

    with tab_obj:
        st.write("### Mission Intent")
        for obj in st.session_state.objectives:
            st.checkbox(obj['task'], value=obj['done'], disabled=True)

# 5. RENDER THE PINNED HUD (Always visible at the bottom)
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

# THE PERSISTENCE TRIGGER (Manual Save)
st.divider()
if st.button("💾 SYNCHRONIZE STATE TO ARCHIVE"):
    save_payload = package_save_state()
    # For now, we can show the JSON so you can see it working
    st.json(save_payload) 
    st.success("State Packaged for Archive.")
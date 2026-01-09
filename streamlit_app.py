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
bg_url = get_image_url(st.session_state.current_scene_image)

st.markdown(f"""
    <style>
    /* 1. Full-screen background */
    .stApp {{
        background-color: #000000;
        background-image: url("{bg_url}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    /* 2. Make the main block container transparent */
    .main .block-container {{
        background-color: rgba(0, 0, 0, 0.0) !important;
    }}
    
    /* 3. SOLID PANEL FOR CHAT/INVENTORY (The Fix)
       This targets the inner container of the second column
    */
    div[data-testid="column"]:nth-of-type(2) > div {{
        background-color: rgba(14, 17, 23, 0.95) !important;
        border: 1px solid #444;
        border-radius: 15px;
        padding: 25px !important;
        box-shadow: 0 10px 30px rgba(0,0,0,1);
        min-height: 80vh;
    }}

    /* 4. Ensure all text inside the right panel is white/readable */
    div[data-testid="column"]:nth-of-type(2) p, 
    div[data-testid="column"]:nth-of-type(2) h3, 
    div[data-testid="column"]:nth-of-type(2) label,
    div[data-testid="column"]:nth-of-type(2) span {{
        color: #FFFFFF !important;
    }}

    /* 5. Tab styling to match the dark theme */
    .stTabs [data-baseweb="tab-list"] {{
        background-color: #0e1117;
        border-radius: 10px 10px 0 0;
    }}

    /* 6. Green HUD stats bar */
    .stats-overlay {{
        color: #00FF41;
        font-family: 'Courier New', Courier, monospace;
        background: rgba(0,0,0,0.9);
        padding: 15px;
        border-top: 2px solid #00FF41;
        font-weight: bold;
        display: inline-block;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- 4. THE UI LAYOUT ---

col_left, col_right = st.columns([1.8, 1.2], gap="large")

with col_left:
    # Spacer to push character overlays into the visible 21:9 area
    st.markdown('<div style="height: 10vh;"></div>', unsafe_allow_html=True)
    
    if st.session_state.current_overlay_image:
        overlay_url = get_image_url(st.session_state.current_overlay_image)
        st.markdown(f"""
            <div style="display: flex; justify-content: flex-start; align-items: flex-end;">
                <img src="{overlay_url}" style="width: 500px; filter: drop-shadow(5px 5px 15px black);">
            </div>
        """, unsafe_allow_html=True)
    else:
        # Maintenance spacer
        st.markdown('<div style="height: 400px;"></div>', unsafe_allow_html=True)
        
    # HUD STATS BAR
    total_weight = sum(item['weight'] for item in st.session_state.inventory)
    st.markdown(f"""
        <div class="stats-overlay">
            &gt; MANA_SIGNATURE: {st.session_state.mana}%<br>
            &gt; PACK_WEIGHT: {total_weight}kg / 20kg
        </div>
    """, unsafe_allow_html=True)

with col_right:
    # Right column now has a solid background from CSS for perfect readability
    tab_act, tab_inv, tab_obj = st.tabs(["ACTIVITY", "GEAR", "MISSION"])
    
    with tab_act:
        chat_container = st.container(height=400)
        with chat_container:
            for msg in st.session_state.messages:
                st.chat_message(msg["role"]).write(msg["content"])
        
        # In the main loop:
            if prompt := st.chat_input("What is your move?"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                # 1. Get raw response from Gemini
                raw_response = get_dm_response(prompt)
                
                # 2. Parse tags and update HUD/Inventory/Objectives
                clean_narrative = process_dm_output(raw_response)

                # TEMPORARY TEST LINE (Add after clean_narrative =)
                if "bob" in prompt.lower():
                    st.session_state.current_overlay_image = "npc_bob_barkeep.png"
                
                # 3. Add only the narrative to the chat history
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

# THE PERSISTENCE TRIGGER (Manual Save)
st.divider()
if st.button("💾 SYNCHRONIZE STATE TO ARCHIVE"):
    save_payload = package_save_state()
    # For now, we can show the JSON so you can see it working
    st.json(save_payload) 
    st.success("State Packaged for Archive.")
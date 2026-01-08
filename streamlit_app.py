import random
import streamlit as st
import xml.etree.ElementTree as ET
from google.cloud import storage
from google.oauth2 import service_account
import google.generativeai as genai
import datetime

# --- 1. CONFIGURATION ---
BUCKET_NAME = "uge-repository-cu32" # Based on your screenshot
st.set_page_config(layout="wide", page_title="UGE Console")

# Retro CSS
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #00FF41; font-family: 'Courier New', Courier, monospace; }
    [data-testid="stSidebar"] { background-color: #1A1C23; border-right: 1px solid #00FF41; }
    .stButton>button { width: 100%; border: 1px solid #00FF41; background-color: transparent; color: #00FF41; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GCS & AI SETUP ---
@st.cache_resource
def get_gcs_client():
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def get_image_url(filename, root_xml):
    config = root_xml.find("config")
    folder = config.find("asset_folder").text if config is not None else "default"
    path = f"uge_assets/{folder}/{filename}"
    client = get_gcs_client()
    blob = client.bucket(BUCKET_NAME).blob(path)
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))

def get_dm_response(prompt, sector_data, meta, exits_list):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # Format the exits into a string for the AI to see
    exit_desc = ", ".join([f"{e.get('direction').upper()}: {e.get('desc')}" for e in exits_list])
    
    sys_instr = f"""
    You are the genial dry-humoured narrator for '{meta['title']}'.
    Mood: {meta['mood']}
    Location: {sector_data['name']}
    Room Description: {sector_data['desc']}
    Available Move Options: {exit_desc}

    RULES:
    1. If the player asks what to do, refer them to the 'Available Exits' buttons under the image.
    2. NEVER invent 'Page numbers' or external gamebook mechanics.
    3. You can narrate 'poking around', but remind them that real progress happens through the exits.
    4. Stay in character: dry, slightly mean, and concise.
    """
    response = model.generate_content([sys_instr, prompt])
    
    # Wrap in Bright Green HTML for Toby's eyes
    bright_text = f"<div style='color: #00FF41; font-weight: bold; font-size: 1.1rem;'>{response.text}</div>"
    return bright_text

def handle_movement(target_x, target_y, success_prob=100, fail_text=None, fail_x=None, fail_y=None):
    """Processes movement, clears old chat logs, and triggers new narration."""
    if random.randint(1, 100) > int(success_prob):
        st.error(fail_text)
        if fail_x is not None:
            # On failure/death, we also clear the chat to narrate the "Respawn"
            st.session_state.messages = [] 
            st.session_state.coords = {"x": int(fail_x), "y": int(fail_y)}
            st.session_state.just_rewound = True 
            st.session_state.needs_narration = True
    else:
        # SUCCESSFUL MOVE: Clear the chat history for the new room
        st.session_state.messages = [] 
        st.session_state.coords = {"x": int(target_x), "y": int(target_y)}
        st.session_state.just_rewound = False
        st.session_state.needs_narration = True
    st.rerun()

def collect_gold(amount, sector_key):
    """Adds gold to wallet and marks the location as 'looted'."""
    if sector_key not in st.session_state.world_state['looted_gold']:
        st.session_state.gold += int(amount)
        st.session_state.world_state['looted_gold'].append(sector_key)
        return True
    return False

def buy_from_vending(item_id, cost):
    """Checks wallet and grants an Artifact ID if funds allow."""
    if st.session_state.gold >= int(cost):
        st.session_state.gold -= int(cost)
        st.session_state.inventory.append(item_id)
        return True
    return False

def get_library_info(ref_id, root_xml):
    """Looks up an ID in the library and returns its name/desc."""
    # We use root_xml passed from the current session
    entry = root_xml.find(f".//*[@id='{ref_id}']")
    if entry is not None:
        return {
            "name": entry.get("name", "Unknown Item"),
            "desc": entry.get("desc", "No description available.")
        }
    return {"name": "Unknown", "desc": ""}

# --- 3. SESSION STATE ---
if "phase" not in st.session_state:
    st.session_state.phase = "TITLE"
    st.session_state.coords = {"x": 0, "y": 0}
    st.session_state.messages = []
    st.session_state.inventory = [] # Added for items
    st.session_state.gold = 0        # Added for currency
    st.session_state.just_rewound = False
    st.session_state.world_state = {"looted_gold": []} # Added for persistence
    st.session_state.needs_narration = True

# --- 4. ENGINE PHASES ---

# PHASE: TITLE
if st.session_state.phase == "TITLE":
    st.markdown("<h1 style='text-align: center;'>UGE CONSOLE</h1>", unsafe_allow_html=True)
    
    client = get_gcs_client()
    blobs = client.list_blobs(BUCKET_NAME, prefix="cartridges/")
    cartridges = [b.name.split("/")[-1] for b in blobs if b.name.endswith(".xml")]
    
    selected = st.selectbox("Choose a Cartridge", cartridges)
    if st.button("INSERT CARTRIDGE"):
        blob = client.bucket(BUCKET_NAME).blob(f"cartridges/{selected}")
        root = ET.fromstring(blob.download_as_text())
        st.session_state.cartridge_root = root
        cfg = root.find("config")
        st.session_state.meta = {
            "title": cfg.find("game_title").text,
            "blurb": cfg.find("game_blurb").text,
            "cover": cfg.find("game_cover").text,
            "mood": cfg.find("mood").text,
            "genres": cfg.find("genre_categories").text
        }
        st.session_state.phase = "COVER"
        st.rerun()

# PHASE: COVER
elif st.session_state.phase == "COVER":
    # ... existing cover display code ...
    if st.button("START QUEST"):
        # Instead of going straight to PLAYING, go to PREAMBLE
        st.session_state.phase = "PREAMBLE"
        st.rerun()

# --- NEW PHASE: PREAMBLE ---
elif st.session_state.phase == "PREAMBLE":
    root = st.session_state.cartridge_root
    preamble_text = root.find("config/game_preamble").text
    
    st.markdown("<h1 style='text-align: center;'>The Story So Far...</h1>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 3, 1])
    with c2:
        # Style it like a classic 80s intro block
        st.markdown(f"### {preamble_text}")
        st.write("---")
        if st.button("START HERE"):
            st.session_state.coords = {"x": 0, "y": 0} # Resets position to the Cave
            st.session_state.just_rewound = False      # Clears any previous death flags
            st.session_state.phase = "PLAYING"
            st.rerun()

# PHASE: PLAYING
elif st.session_state.phase == "PLAYING":
    root = st.session_state.cartridge_root
    cx, cy = st.session_state.coords['x'], st.session_state.coords['y']
    sector = root.find(f".//sector[@x='{cx}'][@y='{cy}']")
    
    # Track visits
    loc_key = f"{cx},{cy}"
    if 'room_visits' not in st.session_state.world_state:
        st.session_state.world_state['room_visits'] = {}

    if sector is not None:
        revert_node = sector.find("revert_desc")
        display_text = revert_node.text if (st.session_state.get("just_rewound") and revert_node is not None) else sector.find("desc").text
        
        # Define s_info and exits so they are globally available in this block
        s_info = {"name": sector.find("name").text, "desc": display_text}
        exits = sector.findall("exit")
        visits = st.session_state.world_state['room_visits'].get(loc_key, 0)

        # --- AUTO-NARRATION TRIGGER ---
        if st.session_state.get("needs_narration"):
            st.session_state.world_state['room_visits'][loc_key] = visits + 1
            # Pass 'exits' to the DM so it knows the move options
            intro_prompt = f"I have just entered {s_info['name']}. Visit #{visits+1}. Narrate my arrival."
            response = get_dm_response(intro_prompt, s_info, st.session_state.meta, exits)
            
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.session_state.needs_narration = False
            st.rerun()

        col_l, col_r = st.columns([1, 1], gap="large")
        
        with col_l:
            st.header(sector.find("name").text)
            st.image(get_image_url(sector.find("image").text, root))
            
            # --- MOVEMENT SECTION ---
            st.subheader("Available Exits")
            if exits:
                cols = st.columns(len(exits))
                for i, ex in enumerate(exits):
                    req_item = ex.get("requires")
                    btn_label = f"{ex.get('direction').upper()}: {ex.get('desc')}"
                    
                    if req_item is None or req_item in st.session_state.inventory:
                        if cols[i].button(btn_label):
                            handle_movement(ex.get("target_x"), ex.get("target_y"), ex.get("success_prob", 100), ex.get("fail_outcome"), ex.get("fail_target_x"), ex.get("fail_target_y"))
                    else:
                        cols[i].button(f"🔒 {ex.get('direction').upper()} (Locked)", disabled=True)
                        st.caption(f"Requires: {get_library_info(req_item, root)['name']}")

            # --- INTERACTION HUB ---
            st.write("---")
            
            # 1. Gold
            gold_node = sector.find("contains_gold")
            if gold_node is not None and loc_key not in st.session_state.world_state['looted_gold']:
                if st.button(f"🔍 Search {s_info['name']}"):
                    if collect_gold(gold_node.get("amount"), loc_key):
                        st.rerun()

            # 2. Items (Take)
            item_node = sector.find("contains_item")
            if item_node is not None:
                item_id = item_node.get("ref")
                if item_id not in st.session_state.inventory:
                    details = get_library_info(item_id, root)
                    if st.button(f"📦 Take {details['name']}"):
                        st.session_state.inventory.append(item_id)
                        st.toast(f"Found: {details['name']}")
                        st.rerun()

            # 3. Vending (The Gift Shop)
            # Checking artifact library for 'vend_method' items in this room
            vend_node = sector.find("vending_item") # Or if it's in the artifact library
            # For your Gift Shop XML, a004 has 'cost: 5'. Let's check for it:
            if s_info['name'].lower() == "the giftshop":
                details = get_library_info("a004", root)
                if "a004" not in st.session_state.inventory:
                    if st.button(f"🛒 Buy {details['name']} (5 Gold)"):
                        if buy_from_vending("a004", 5):
                            st.rerun()
                        else:
                            st.error("Not enough gold!")

        with col_r:
            st.subheader("Dungeon Master")
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"], unsafe_allow_html=True)
            
            if prompt := st.chat_input("Ask the DM a question ..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                # DM now knows the room options to guide Toby
                response = get_dm_response(prompt, s_info, st.session_state.meta, exits)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
            
with st.sidebar:
    if st.session_state.phase != "TITLE":
        if st.button("Quit to Menu"):
            st.session_state.phase = "TITLE"
            st.session_state.messages = []
            st.rerun()
            
        st.header("🎒 Adventurer Stats")
        st.metric("Gold", f"🪙 {st.session_state.gold}")
        
        st.subheader("Inventory")
        if st.session_state.inventory:
            for item_id in st.session_state.inventory:
                details = get_library_info(item_id, st.session_state.cartridge_root)
                st.write(f"- {details['name']}")
        else:
            st.write("*Your pockets are empty.*")

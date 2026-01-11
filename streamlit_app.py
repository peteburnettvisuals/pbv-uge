import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai
import re
import datetime

# --- CONFIGURATION & INITIALIZATION ---
st.set_page_config(layout="wide", page_title="UGE: Warlock PoC")

# Session State Initialization (ULE Pattern)
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 75,  # Starting mana for the operative
        "inventory": ["Echo Shard"], # Operative starts with their comms device
        "messages": [],
        "current_chapter_id": "1", # Start in Chapter 1
        "current_location_desc": "The Village of Oakhaven", # Initial description for context
        "chat_session": None, # For ULE-style persistent AI memory
        "player_name": "Recruit" # Default player name for HUD
    })


# --- UTILITY FUNCTIONS ---
BUCKET_NAME = "uge-repository-cu32" # Your GCS bucket name

def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
    except FileNotFoundError:
        # Fallback if the file is missing during deployment
        st.warning("Tactical stylesheet missing. Reverting to default comms.")

local_css("style.css")

@st.cache_resource
def get_gcs_client():
    from google.oauth2 import service_account
    from google.cloud import storage
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def get_image_url(filename):
    """Generates a signed URL for an image in GCS."""
    if not filename:
        return "" # Return empty if no filename
    client = get_gcs_client()
    # Assuming images are in a folder called 'cinematics' in your bucket
    blob = client.bucket(BUCKET_NAME).blob(f"cinematics/{filename}")
    # Cache the URL for efficiency
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))

# --- AI ENGINE LOGIC (ULE-Style Stateful) ---
def get_dm_response(prompt):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 2.0-flash-exp is perfect for following these complex persona constraints
    model = genai.GenerativeModel('gemini-2.0-flash-exp', generation_config={"temperature": 0.4})

    # Load Game Sheet (XML Source of Truth)
    tree = ET.parse("game_sheet.xml")
    root = tree.getroot()
    
    # Context Injection: Pulling the Chapter Sandbox
    chapter_data = root.find(f"chapter[@id='{st.session_state.current_chapter_id}']")
    locations = chapter_data.find("locations").text.strip()
    npcs = chapter_data.find("npcs").text.strip()
    objectives = chapter_data.find("main_objectives").text.strip()

    if st.session_state.chat_session is None:
        sys_instr = f"""
        {root.find("synopsis").text}
        
        CHAPTER {st.session_state.current_chapter_id} SANDBOX DATA:
        - LOCATIONS: {locations}
        - NPCs: {npcs}
        - OBJECTIVES: {objectives}
        - LORE: {root.find("lore").text}

        OPERATIONAL PROTOCOLS (THE HANDLER):
        1. PERSONA: You are the 'Handler' communicating via Echo Shard. Tone is laconic, businesslike, and dry (Agent K style).
        2. INFOSEC (OBFUSCATION): Do not give away the game. You know the XML 'Dossier' on NPCs, but the operative (player) does not. 
           - Bad: "Greeb has a special dagger you need."
           - Good: "Greeb Snelling runs the Rusted Tankard. He's a veteran; might be worth seeing what he's picked up over the years."
        3. INTUITION OVER LISTS: Use environmental cues and tactical advice to suggest moves. Never use a/b/c menus.
        4. ASSET DEPLOYMENT: Use the [IMG: filename.jpg] tag ONLY when the player arrives at or looks directly at a canonical location/NPC. 
           - STARTING ASSET: Use [IMG: oakhaven.jpg] (the map with larger labels) for the first briefing.
        5. NO NODES: This is an open-world sandbox. Handle creative player moves by tethering them back to the sandbox lore.
        6. GUARDRAILS: You must strictly enforce the chapter constraints. If the operative attempts to leave Oakhaven or scale the mountain without meeting all objectives, describe a lethal obstacle or impediment that forces them back. Be the Handler—tell them they aren't ready.
        7. INVENTORY UPDATES: If the operative successfully acquires a significant item mentioned in the sandbox (like the Orichalcum dagger), append the tag [ADD_ITEM: Item Name] to your response.
        8. OPERATIONAL DISCIPLINE: If the operative performs actions that are counter-productive, absurd, or likely to draw unwanted attention (like mooning or twerking), respond with a scolding 'Handler' tone and append the tag [MANA_BURN: 5].
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    response_text = st.session_state.chat_session.send_message(prompt).text

    # --- INVENTORY LOGIC ---
    # Look for the acquisition tag
    item_match = re.search(r"\[ADD_ITEM:\s*([^\]]+)\]", response_text)
    if item_match:
        new_item = item_match.group(1).strip()
        if new_item not in st.session_state.inventory:
            st.session_state.inventory.append(new_item)
            st.toast(f"EQUIPMENT ACQUIRED: {new_item}")

    # --- MANA BURN LOGIC ---
    # Look for the penalty tag
    mana_match = re.search(r"\[MANA_BURN:\s*(\d+)\]", response_text)
    if mana_match:
        penalty = int(mana_match.group(1))
        st.session_state.mana = max(0, st.session_state.mana - penalty)
        st.toast(f"SIGNAL COMPROMISED: -{penalty}% Mana (Anti-Social Conduct)")

    # Check if the AI thinks the chapter is over
    if "[CHAPTER_COMPLETE]" in response_text:
        # 1. Advance the state
        st.session_state.current_chapter_id = str(int(st.session_state.current_chapter_id) + 1)
        st.session_state.current_location_desc = "Certain Death Mountain"
        
        # 2. CLEAN the response text so the tag isn't saved to history
        # This prevents the "Infinite Rerun" loop
        response_text = response_text.replace("[CHAPTER_COMPLETE]", "").strip()
        
        # 3. Inform the player
        st.toast("MISSION OBJECTIVES MET: Moving to next sector.")
        
        # 4. We don't return here; we let the function finish so the 
        # cleaned response_text is sent back to the main loop to be appended.

    # 3. ONLY return the text at the very end of the function
    return response_text


# --- UI LAYOUT (Single Column + Sidebar HUD) ---

with st.sidebar:
    # 1. Branding
    try:
        st.image("black_raven_logo.png", use_container_width=True)
    except:
        st.subheader("🦅 BLACK RAVEN HQ")

    # 2. Status & Chapter
    st.markdown(f'<div class="sidebar-chapter">Sector: {st.session_state.current_location_desc}</div>', unsafe_allow_html=True)
    st.metric("MANA SIGNATURE", f"{st.session_state.mana}%")
    st.progress(st.session_state.mana / 100)
    
    st.divider()
    
    # 3. Gear & Mission
    st.subheader("🎒 TACTICAL GEAR")
    for item in st.session_state.inventory:
        st.write(f"• {item}")
    
    st.divider()
    st.subheader("🎯 OBJECTIVES")
    # Display objectives from current chapter
    chapter_id = st.session_state.current_chapter_id
    try:
        tree = ET.parse("game_sheet.xml")
        root = tree.getroot()
        current_chapter = root.find(f"chapter[@id='{chapter_id}']")
        objectives_text = current_chapter.find("main_objectives").text.strip()
        # Splitting objectives into individual lines for better display
        for obj_line in objectives_text.split(". "):
            if obj_line.strip():
                st.write(f"• {obj_line.strip()}")
    except Exception as e:
        st.write(f"Error loading objectives: {e}")


# Chat Container - Fixed height with scrolling
chat_container = st.container(height=650, border=True)
with chat_container:
    # Auto-start Game Briefing if no messages yet
    if not st.session_state.messages:
        with st.spinner("Establishing Echo Shard link..."):
            initial_briefing = get_dm_response("start_game_briefing")
            st.session_state.messages.append({"role": "assistant", "content": initial_briefing})
            st.rerun() # Rerun to display the initial message

    # Display all messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            content_with_images = msg["content"]
            
            # Use regex to find all [IMG:] tags and split the string
            parts = re.split(r"(\[IMG:\s*[^\]]+\.jpg\])", content_with_images)
            
            for part in parts:
                if part.startswith("[IMG:"):
                    # Extract filename and generate URL
                    img_filename = part[len("[IMG:"): -1].strip()
                    img_url = get_image_url(img_filename)
                    if img_url:
                        st.image(img_url, width=650)
                else:
                    # Display text parts
                    st.write(part.strip())

# --- CHAT INPUT (Pinned at bottom, but constrained by style.css) ---
if prompt := st.chat_input("Operative, your move?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = get_dm_response(prompt)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()

# --- Example of potential future UI interactions (Mana usage, Inventory Management) ---
# This part can be developed as the game mechanics evolve
# For instance, a button in the sidebar to "Use Mana" which calls a specific AI function
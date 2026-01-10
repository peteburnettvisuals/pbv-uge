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

# --- CSS STYLING ---
st.markdown("""
    <style>
    /* White to Gray Gradient Background */
    .stApp { background: linear-gradient(180deg, #FFFFFF 0%, #D1D5DB 100%); }
    
    /* Jumbo Chat Text for mobile/desktop readability */
    [data-testid="stChatMessageContent"] p {
        font-size: 1.4rem !important;
        line-height: 1.7 !important;
    }
    
    /* Sidebar Stat Styling (The HUD) */
    [data-testid="stSidebar"] {
        background-color: #111827 !important; /* Dark background */
        color: #00FF41 !important; /* Cyberpunk green text */
        border-right: 2px solid #00FF41; /* Matching border */
    }
    /* Ensure sidebar elements inherit color */
    [data-testid="stSidebar"] * {
        color: #00FF41 !important;
    }
    /* Specific styling for progress bar in sidebar if needed */
    .stProgress > div > div > div > div {
        background-color: #00FF41 !important;
    }
    </style>
""", unsafe_allow_html=True)


# --- UTILITY FUNCTIONS ---
BUCKET_NAME = "uge-repository-cu32" # Your GCS bucket name

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
    model = genai.GenerativeModel('gemini-2.0-flash-exp', generation_config={"temperature": 0.4})

    # Load the Consolidated Game Sheet
    tree = ET.parse("game_sheet.xml")
    root = tree.getroot()
    
    # 1. PULL CHAPTER 1 AS A BUNDLE (No more waypoint IDs)
    chapter_data = root.find(f"chapter[@id='{st.session_state.current_chapter_id}']")
    locations = chapter_data.find("locations").text
    npcs = chapter_data.find("npcs").text
    objectives = chapter_data.find("main_objectives").text

    if st.session_state.chat_session is None:
        sys_instr = f"""
        {root.find("synopsis").text}
        
        CHAPTER 1 SANDBOX:
        - LOCATIONS: {locations}
        - NPCs: {npcs}
        - CURRENT OBJECTIVES: {objectives}

        HANDLING RULES:
        1. NO NODES: The player is in an open world. Do not look for 'nodes'. 
        2. STARTING POINT: The Operative begins at the Gates of Oakhaven.
        3. INTUITION: Suggest directions based on the Sandbox data. 
        4. GUARDRAILS: If they leave Oakhaven, remind them the mountain is impassable without the gear mentioned in the objectives.
        5. ASSETS: Deploy [IMG: filename.jpg] when they reach a canonical area.
        """
        st.session_state.chat_session = model.start_chat(history=[])
        st.session_state.chat_session.send_message(sys_instr)

    return st.session_state.chat_session.send_message(prompt).text

# --- UI LAYOUT (Single Column + Sidebar HUD) ---

# Sidebar: The Black Raven HUD
with st.sidebar:
    try:
        st.image("black_raven_logo.png")
    except:
        st.write("🦅 **BLACK RAVEN HQ**") # Text fallback if image is missing
    st.title("🦅 BLACK RAVEN HUD")
    st.write(f"**OPERATIVE:** {st.session_state.player_name}")
    st.metric("MANA SIGNATURE", f"{st.session_state.mana}%")
    st.progress(st.session_state.mana / 100) # Mana as a progress bar
    st.divider()
    st.subheader("🎒 TACTICAL GEAR")
    if not st.session_state.inventory:
        st.write("No gear equipped.")
    for item in st.session_state.inventory:
        st.write(f"• {item}")
    st.divider()
    st.subheader("🎯 CURRENT OBJECTIVES")
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


# Main Content Area: The Narrative Theatre
st.title("THE WARLOCK OF CERTAIN DEATH MOUNTAIN")
st.caption(f"Chapter {st.session_state.current_chapter_id}: {st.session_state.current_location_desc}")

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
                        st.image(img_url, use_column_width=True)
                else:
                    # Display text parts
                    st.write(part.strip())

# Chat Input at the bottom of the main column
if prompt := st.chat_input("Operative, your move?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    response = get_dm_response(prompt)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()

# --- Example of potential future UI interactions (Mana usage, Inventory Management) ---
# This part can be developed as the game mechanics evolve
# For instance, a button in the sidebar to "Use Mana" which calls a specific AI function
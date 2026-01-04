import streamlit as st
import xml.etree.ElementTree as ET

# --- 1. CONFIGURATION & UI SKINNING ---
st.set_page_config(layout="wide", page_title="UGE - Universal Gaming Engine")

# Injecting some 'Retro Console' CSS
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #00FF41; font-family: 'Courier New', Courier, monospace; }
    [data-testid="stSidebar"] { background-color: #1A1C23; border-right: 1px solid #00FF41; }
    .stButton>button { width: 100%; border: 1px solid #00FF41; background-color: transparent; color: #00FF41; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. SESSION STATE INITIALIZATION ---
if "phase" not in st.session_state:
    st.session_state.phase = "TITLE"
    st.session_state.coords = {"x": 0, "y": 0, "z": 0}
    st.session_state.inventory = ["Rusty Key", "Half-eaten Apple"]

# --- 3. THE "CARTRIDGE" LOADER (DUMMY XML) ---
# In production, this would load from your XML file
def get_current_sector(x, y):
    # Mock XML data logic
    world_data = {
        (0, 0): {"name": "The Dark Forest", "img": "https://via.placeholder.com/400x200?text=Dark+Forest", "desc": "Tall, gnarled trees block the moonlight."},
        (1, 0): {"name": "The Old Cabin", "img": "https://via.placeholder.com/400x200?text=Old+Cabin", "desc": "A dilapidated wooden structure with a smoking chimney."}
    }
    return world_data.get((x, y), {"name": "The Void", "img": "", "desc": "You have reached the edge of the world."})

# --- 4. UI LAYOUT: SIDEBAR ---
with st.sidebar:
    st.title("👾 UGE v1.0")
    st.image("https://via.placeholder.com/150?text=GAME+LOGO") # Replace with xml-driven logo
    st.divider()
    st.subheader("Player Stats")
    st.write(f"**ID:** RetroExplorer_79")
    st.progress(85, text="Health")
    st.divider()
    st.subheader("Inventory")
    for item in st.session_state.inventory:
        st.caption(f"- {item}")

# --- 5. MAIN SCREEN LOGIC ---
if st.session_state.phase == "TITLE":
    st.markdown("<h1 style='text-align: center;'>PRESS START</h1>", unsafe_allow_html=True)
    if st.button("INITIALIZE CARTRIDGE"):
        st.session_state.phase = "PLAYING"
        st.rerun()

elif st.session_state.phase == "PLAYING":
    col_left, col_right = st.columns([1, 1], gap="large")

    # LEFT COLUMN: World View (XML Driven)
    with col_left:
        sector = get_current_sector(st.session_state.coords['x'], st.session_state.coords['y'])
        st.header(sector['name'])
        st.image(sector['img'])
        st.info(sector['desc'])
        
        # Movement Logic
        st.write("---")
        m_col1, m_col2, m_col3 = st.columns(3)
        if m_col2.button("▲ N"): st.session_state.coords['y'] += 1; st.rerun()
        if m_col1.button("◀ W"): st.session_state.coords['x'] -= 1; st.rerun()
        if m_col3.button("▶ E"): st.session_state.coords['x'] += 1; st.rerun()
        if m_col2.button("▼ S"): st.session_state.coords['y'] -= 1; st.rerun()

    # RIGHT COLUMN: Gemini Interaction
    with col_right:
        st.subheader("Dungeon Master")
        
        # Chat History Container
        chat_container = st.container(height=400)
        with chat_container:
            st.chat_message("assistant").write("The air is cold. What would you like to do?")
            
        # User Input
        if prompt := st.chat_input("Type your action..."):
            with chat_container:
                st.chat_message("user").write(prompt)
                # Here is where Gemini 2.0 API call would happen
                st.chat_message("assistant").write(f"The DM considers your attempt to '{prompt}'...")
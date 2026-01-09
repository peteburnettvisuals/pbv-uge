import streamlit as st
import xml.etree.ElementTree as ET
import google.generativeai as genai

# --- 1. CORE POC CONFIGURATION ---
st.set_page_config(layout="wide", page_title="UGE: Warlock PoC")

# CSS: Implementing the "Cinematic" look
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #FFFFFF; }
    /* Cinematic Background Container */
    .cinematic-container {
        border: 2px solid #333;
        border-radius: 10px;
        padding: 10px;
        background: #1A1C23;
    }
    .stats-overlay {
        color: #00FF41;
        font-family: 'Courier New', Courier, monospace;
        background: rgba(0,0,0,0.6);
        padding: 10px;
        border-radius: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DECOUPLED INGESTION ---
def load_poc_assets():
    # In production, these pull from your GCS bucket
    # For now, we simulate the merge of World and Mission
    world_xml = """<world><location id='LOC_TAVERN' name='Rusty Tankard' image='tavern_21x9.jpg'/></world>"""
    mission_xml = """<mission><chapter id='1'><waypoint id='1.1' loc_ref='LOC_TAVERN' desc='The air is thick with whispers.'/></waypoint></chapter></mission>"""
    return ET.fromstring(world_xml), ET.fromstring(mission_xml)

# --- 3. SESSION STATE (The "Manual Save" Hub) ---
if "mana" not in st.session_state:
    st.session_state.update({
        "mana": 25,
        "inventory": [], # Array of dicts: {"name": "Silver Dagger", "weight": 1.5}
        "messages": [],
        "current_waypoint": "1.1",
        "objectives": [{"task": "Find Silver Weapon", "done": False}, {"task": "Get Bane-Oil", "done": False}]
    })

# --- 4. THE UI LAYOUT (Matching your screenshot) ---

# TOP HEADER
col_head_1, col_head_2 = st.columns([4, 1])
with col_head_1:
    st.subheader("Game: The Warlock of Certain Death Mountain")
    st.caption(f"Chapter 1: The Village of Oakhaven")
with col_head_2:
    st.markdown("### UGE")

# MAIN CONTENT AREA
col_left, col_right = st.columns([2, 1], gap="medium")

with col_left:
    # 21:9 CINEMATIC AREA
    st.markdown('<div class="cinematic-container">', unsafe_allow_html=True)
    st.image("https://via.placeholder.com/1200x514/1A1C23/00FF41?text=Cinematic+21:9+View") # Placeholder
    st.markdown('</div>', unsafe_allow_html=True)
    
    # STATS BAR (Bottom Left of Art)
    total_weight = sum(item['weight'] for item in st.session_state.inventory)
    st.markdown(f"""
        <div class="stats-overlay">
            MANA SIGNATURE: {st.session_state.mana}% | 
            PACK WEIGHT: {total_weight}kg / 20kg
        </div>
    """, unsafe_allow_html=True)

with col_right:
    # THE TABBED INTERFACE
    tab_act, tab_inv, tab_obj = st.tabs(["Activity", "Inventory", "Objectives"])
    
    with tab_act:
        chat_container = st.container(height=400)
        with chat_container:
            for msg in st.session_state.messages:
                st.chat_message(msg["role"]).write(msg["content"])
        
        if prompt := st.chat_input("What is your move?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            # Logic to trigger Gemini DM response would go here
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
    # This is where your GCS/DB write logic lives
    st.success("State Saved.")
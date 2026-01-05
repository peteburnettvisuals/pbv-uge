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
    path = f"assets/{folder}/{filename}"
    client = get_gcs_client()
    blob = client.bucket(BUCKET_NAME).blob(path)
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60))

def get_dm_response(prompt, sector_data, meta):
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    sys_instr = f"""
    You are the narrator for '{meta['title']}'.
    Mood: {meta['mood']}
    Location: {sector_data['name']}
    Room Description: {sector_data['desc']}
    Action: Describe the results of the player's action in 2-3 sentences. Stay in character.
    """
    response = model.generate_content([sys_instr, prompt])
    return response.text

# --- 3. SESSION STATE ---
if "phase" not in st.session_state:
    st.session_state.phase = "TITLE"
    st.session_state.coords = {"x": 0, "y": 0}
    st.session_state.messages = []

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
    m = st.session_state.meta
    st.markdown(f"<h1 style='text-align: center;'>{m['title']}</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(get_image_url(m['cover'], st.session_state.cartridge_root))
        st.info(m['blurb'])
        st.caption(f"Genres: {m['genres']}")
        if st.button("START GAME"):
            st.session_state.phase = "PLAYING"
            st.rerun()

# PHASE: PLAYING
elif st.session_state.phase == "PLAYING":
    root = st.session_state.cartridge_root
    cx, cy = st.session_state.coords['x'], st.session_state.coords['y']
    sector = root.find(f".//sector[@x='{cx}'][@y='{cy}']")

    col_l, col_r = st.columns([1, 1], gap="large")
    
    with col_l:
        if sector is not None:
            st.header(sector.find("name").text)
            st.image(get_image_url(sector.find("image").text, root))
            st.info(sector.find("desc").text)
            
            # Movement
            st.write("---")
            m1, m2, m3 = st.columns(3)
            if m2.button("▲ N"): st.session_state.coords['y'] += 1; st.rerun()
            if m1.button("◀ W"): st.session_state.coords['x'] -= 1; st.rerun()
            if m3.button("▶ E"): st.session_state.coords['x'] += 1; st.rerun()
            if m2.button("▼ S"): st.session_state.coords['y'] -= 1; st.rerun()
        
    with col_r:
        st.subheader("Dungeon Master")
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).write(msg["content"])
            
        if prompt := st.chat_input("What do you do?"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun() # Forces UI refresh before AI call
            
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    with st.chat_message("assistant"):
        sector = root.find(f".//sector[@x='{cx}'][@y='{cy}']")
        s_info = {"name": sector.find("name").text, "desc": sector.find("desc").text}
        response = get_dm_response(st.session_state.messages[-1]["content"], s_info, st.session_state.meta)
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.write(response)

# --- SIDEBAR ---
with st.sidebar:
    if st.session_state.phase != "TITLE":
        if st.button("Quit to Menu"):
            st.session_state.phase = "TITLE"
            st.session_state.messages = []
            st.rerun()
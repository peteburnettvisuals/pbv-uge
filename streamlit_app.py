import streamlit as st
import xml.etree.ElementTree as ET
from google.cloud import storage
from google.oauth2 import service_account
import datetime
import google.generativeai as genai

# --- 1. CONFIGURATION & UI SKINNING --- ##########################################################################################################
st.set_page_config(layout="wide", page_title="UGE - Universal Gaming Engine")

# Retro Console CSS
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #00FF41; font-family: 'Courier New', Courier, monospace; }
    [data-testid="stSidebar"] { background-color: #1A1C23; border-right: 1px solid #00FF41; }
    .stButton>button { width: 100%; border: 1px solid #00FF41; background-color: transparent; color: #00FF41; }
    .stInfo { background-color: #1A1C23; color: #00FF41; border: 1px solid #00FF41; }
    </style>
    """, unsafe_allow_html=True)



# --- 2. GCS & ASSET UTILITIES --- ################################################################################################################
BUCKET_NAME = "uge-repository-cu32"  # <--- UPDATE THIS

@st.cache_resource
def get_gcs_client():
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def get_signed_url(blob_path):
    """Generates a secure, temporary link for assets"""
    try:
        client = get_gcs_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(blob_path)
        return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60), method="GET")
    except:
        return "https://via.placeholder.com/400x200?text=Asset+Error"

def get_image_resolver(filename, root_xml):
    """Combines asset_folder from XML with the filename"""
    config = root_xml.find("config")
    folder = config.find("asset_folder").text if config is not None else "default"
    return get_signed_url(f"assets/{folder}/{filename}")

def test_gemini_connection():
    try:
        # Pull key from secrets
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Test prompt using your specific Warlock/Carroll mood
        test_prompt = """
        System: You are an 80s Choose Your Own Adventure narrator with a dash of Lewis Carroll absurdism.
        Context: The player is standing in 'The Great Hall' of the Warlock of Certain Death Mountain.
        Task: Give a 2-sentence opening narration.
        """
        
        response = model.generate_content(test_prompt)
        return response.text
    except Exception as e:
        return f"❌ Error: {str(e)}"



# --- 3. SESSION STATE --- ##################################################################################################################
if "phase" not in st.session_state:
    st.session_state.phase = "TITLE"
    st.session_state.coords = {"x": 0, "y": 0}
    st.session_state.inventory = []
    st.session_state.cartridge_root = None
    st.session_state.meta = {}



# --- 4. MAIN UI LOGIC --- #################################################################################################################

# PHASE 1: TITLE (Library View)
if st.session_state.phase == "TITLE":
    st.markdown("<h1 style='text-align: center;'>UGE CONSOLE</h1>", unsafe_allow_html=True)
    st.write("---")
    
    client = get_gcs_client()
    blobs = client.list_blobs(BUCKET_NAME, prefix="cartridges/")
    cartridges = [b.name.split("/")[-1] for b in blobs if b.name.endswith(".xml")]

    if cartridges:
        selected = st.selectbox("Choose a Cartridge", cartridges)
        if st.button("INSERT CARTRIDGE"):
            # Load XML
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(f"cartridges/{selected}")
            root = ET.fromstring(blob.download_as_text())
            st.session_state.cartridge_root = root
            
            # Store Metadata
            cfg = root.find("config")
            st.session_state.meta = {
                "title": cfg.find("game_title").text,
                "author": cfg.find("game_author").text,
                "blurb": cfg.find("game_blurb").text,
                "cover": cfg.find("game_cover").text,
                "genres": cfg.find("categories").text.split(",")
            }
            st.session_state.phase = "COVER"
            st.rerun()
    else:
        st.warning("Empty Library. Please upload XMLs to GCS.")

     
    
    with st.expander("🛠️ System Diagnostics"):
        if st.button("Test Gemini Brain"):
            with st.spinner("Consulting the Oracle..."):
                result = test_gemini_connection()
                st.write("**DM Response:**")
                st.info(result)

# PHASE 2: COVER (The Splash Screen)
elif st.session_state.phase == "COVER":
    m = st.session_state.meta
    st.markdown(f"<h1 style='text-align: center;'>{m['title']}</h1>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        cover_url = get_image_resolver(m['cover'], st.session_state.cartridge_root)
        st.image(cover_url)
        st.write(f"**Author:** {m['author']}")
        st.info(m['blurb'])
        
        # Display genre badges
        st.write(" | ".join([f"`{g.strip()}`" for g in m['genres']]))
        
        if st.button("BEGIN ADVENTURE", type="primary"):
            st.session_state.phase = "PLAYING"
            st.rerun()

# PHASE 3: PLAYING (The Game Loop)
elif st.session_state.phase == "PLAYING":
    root = st.session_state.cartridge_root
    cx, cy = st.session_state.coords['x'], st.session_state.coords['y']
    
    # XPath search for coordinates
    sector = root.find(f".//sector[@x='{cx}'][@y='{cy}']")

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        if sector is not None:
            st.header(sector.find("name").text)
            img_filename = sector.find("image").text
            st.image(get_image_resolver(img_filename, root))
            st.info(sector.find("desc").text)
        else:
            st.error("The Void: No sector data here.")
        
        # D-PAD
        st.write("---")
        m1, m2, m3 = st.columns(3)
        if m2.button("▲ N"): st.session_state.coords['y'] += 1; st.rerun()
        if m1.button("◀ W"): st.session_state.coords['x'] -= 1; st.rerun()
        if m3.button("▶ E"): st.session_state.coords['x'] += 1; st.rerun()
        if m2.button("▼ S"): st.session_state.coords['y'] -= 1; st.rerun()

    with col_right:
        st.subheader("Dungeon Master")
        # Placeholder for Gemini 2.0 Chat
        st.chat_message("assistant").write(f"Welcome to {st.session_state.meta['title']}. What is your first move?")
        if prompt := st.chat_input("I examine the surroundings..."):
             st.chat_message("user").write(prompt)
             st.write("*(Gemini logic incoming...)*")

# --- SIDEBAR GLOBAL ---
with st.sidebar:
    if st.session_state.phase != "TITLE":
        if st.button("Return to Library"):
            st.session_state.phase = "TITLE"
            st.rerun()
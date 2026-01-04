import streamlit as st
import xml.etree.ElementTree as ET
from google.cloud import storage
from google.oauth2 import service_account
import datetime

# --- 1. CONFIGURATION & UI SKINNING ---
st.set_page_config(layout="wide", page_title="UGE - Universal Gaming Engine")

st.markdown("""
    <style>
    .stApp { background-color: #0E1117; color: #00FF41; font-family: 'Courier New', Courier, monospace; }
    [data-testid="stSidebar"] { background-color: #1A1C23; border-right: 1px solid #00FF41; }
    .stButton>button { width: 100%; border: 1px solid #00FF41; background-color: transparent; color: #00FF41; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GCS CONNECTION & UTILITIES ---
@st.cache_resource
def get_gcs_client():
    creds_info = st.secrets["gcp_service_account"]
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    return storage.Client(credentials=credentials, project=creds_info["project_id"])

def load_cartridge(bucket_name, cartridge_name):
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(f"cartridges/{cartridge_name}")
    xml_content = blob.download_as_text()
    return ET.fromstring(xml_content)

def get_signed_asset_url(bucket_name, asset_path):
    """Generates a temporary URL for private assets (videos/images)"""
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(asset_path)
    return blob.generate_signed_url(expiration=datetime.timedelta(minutes=60), method="GET")

# --- 3. GAME LOGIC ---
def get_sector_from_xml(root, x, y):
    """Finds a sector by coordinates in the loaded XML"""
    # XPath to find sector with specific x and y attributes
    query = f".//sector[@x='{x}'][@y='{y}']"
    sector = root.find(query)
    
    if sector is not None:
        return {
            "name": sector.find("name").text if sector.find("name") is not None else "Unknown Location",
            "desc": sector.find("desc").text if sector.find("desc") is not None else "No description available.",
            "img_path": sector.find("image").text if sector.find("image") is not None else None
        }
    return None

# --- 4. SESSION STATE INITIALIZATION ---
if "phase" not in st.session_state:
    st.session_state.phase = "TITLE"
    st.session_state.coords = {"x": 0, "y": 0}
    st.session_state.inventory = []
    st.session_state.cartridge_root = None

# --- 5. UI LAYOUT: SIDEBAR ---
with st.sidebar:
    st.title("👾 UGE v1.0")
    # Dynamically load logo from GCS if cartridge is loaded
    st.image("https://via.placeholder.com/150?text=UGE+CONSOLE")
    st.divider()
    if st.session_state.phase == "PLAYING":
        st.subheader("Stats & Inventory")
        st.write(f"**Loc:** {st.session_state.coords['x']}, {st.session_state.coords['y']}")
        st.write(f"**Items:** {', '.join(st.session_state.inventory) if st.session_state.inventory else 'Empty'}")
        if st.button("Quit Game"):
            st.session_state.phase = "TITLE"
            st.rerun()

# --- 6. MAIN SCREEN LOGIC ---
BUCKET_NAME = "uge-repository-cu32" # Replace with your actual bucket name

if st.session_state.phase == "TITLE":
    st.markdown("<h1 style='text-align: center;'>UGE CONSOLE</h1>", unsafe_allow_html=True)
    
    # Cartridge Selection
    client = get_gcs_client()
    blobs = client.list_blobs(BUCKET_NAME, prefix="cartridges/")
    cartridges = [b.name.split("/")[-1] for b in blobs if b.name.endswith(".xml")]
    
    selected_game = st.selectbox("Select a Cartridge", cartridges)
    
    if st.button("INSERT CARTRIDGE & START"):
        st.session_state.cartridge_root = load_cartridge(BUCKET_NAME, selected_game)
        st.session_state.phase = "PLAYING"
        st.rerun()

elif st.session_state.phase == "PLAYING":
    col_left, col_right = st.columns([1, 1], gap="large")
    
    sector_data = get_sector_from_xml(st.session_state.cartridge_root, st.session_state.coords['x'], st.session_state.coords['y'])

    with col_left:
        if sector_data:
            st.header(sector_data['name'])
            if sector_data['img_path']:
                # Resolve the image from GCS using a signed URL
                img_url = get_signed_asset_url(BUCKET_NAME, f"assets/{sector_data['img_path']}")
                st.image(img_url)
            st.info(sector_data['desc'])
        else:
            st.error("You have entered a glitch in the matrix (No XML data for these coordinates).")
            if st.button("Return to Origin"):
                st.session_state.coords = {"x": 0, "y": 0}
                st.rerun()
        
        # D-PAD Controls
        st.write("---")
        m_col1, m_col2, m_col3 = st.columns(3)
        if m_col2.button("▲ N"): st.session_state.coords['y'] += 1; st.rerun()
        if m_col1.button("◀ W"): st.session_state.coords['x'] -= 1; st.rerun()
        if m_col3.button("▶ E"): st.session_state.coords['x'] += 1; st.rerun()
        if m_col2.button("▼ S"): st.session_state.coords['y'] -= 1; st.rerun()

    with col_right:
        st.subheader("Dungeon Master")
        chat_container = st.container(height=400)
        with chat_container:
            st.chat_message("assistant").write("I am the UGE Interpreter. What is your command?")
            
        if prompt := st.chat_input("What do you do?"):
            with chat_container:
                st.chat_message("user").write(prompt)
                st.chat_message("assistant").write("Gemini 2.0 is processing your destiny...")
import streamlit as st
import requests

# Configure your backend URL
BACKEND_URL = "http://localhost:8000/ask_with_file"  # Change if different

# App title
st.title("📁 Local AI Assistant with File Upload")

# ========== SIDEBAR FOR FILE UPLOAD ==========
with st.sidebar:
    st.header("📂 Upload Files")
    
    # File uploader widget
    uploaded_files = st.file_uploader(
        "Choose files to analyze",
        type=["txt", "py", "json", "csv", "md", "log", "pdf", "docx"],
        accept_multiple_files=True
    )
    
    # Show uploaded files
    if uploaded_files:
        st.subheader("Uploaded Files:")
        for file in uploaded_files:
            st.write(f"- {file.name} ({file.size} bytes)")
    
    st.divider()
    st.caption("Files are sent to your local AI for processing.")

# ========== MAIN CHAT AREA ==========
st.header("💬 Chat with AI")

# Input for user question
user_question = st.text_area("Ask about your uploaded files:")

# Process button
if st.button("Get AI Analysis", type="primary") and user_question:
    with st.spinner("Analyzing files with AI..."):
        try:
            # Prepare form data
            form_data = {"prompt": user_question}
            files_data = []
            
            # Add uploaded files
            if uploaded_files:
                for file in uploaded_files:
                    file.seek(0)  # Reset file pointer
                    files_data.append(("file", (file.name, file.read(), file.type)))
            
            # Send request to backend
            if files_data:
                # With files
                response = requests.post(
                    BACKEND_URL,
                    data=form_data,
                    files=files_data,
                    timeout=60
                )
            else:
                # Without files
                response = requests.post(
                    "http://localhost:8000/ask",  # Your standard endpoint
                    json={"prompt": user_question},
                    timeout=60
                )
            
            # Handle response
            if response.status_code == 200:
                result = response.json()
                st.success("✅ Analysis Complete!")
                st.markdown("### AI Response:")
                st.markdown(result.get("response", "No response received"))
            else:
                st.error(f"❌ Backend error: {response.status_code}")
                st.code(response.text)
                
        except requests.exceptions.ConnectionError:
            st.error("🚫 Cannot connect to AI backend. Make sure your local LLM server is running.")
            st.info("Start your backend with: `uvicorn main:app --reload`")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

# ========== SIDEBAR STATUS ==========
with st.sidebar:
    st.divider()
    
    # Backend connection check
    try:
        status_response = requests.get("http://localhost:8000/", timeout=2)
        if status_response.status_code == 200:
            st.success("✅ Backend Connected")
        else:
            st.warning("⚠️ Backend responded with error")
    except:
        st.error("❌ Backend Not Connected")
        st.caption("Start your AI server first")
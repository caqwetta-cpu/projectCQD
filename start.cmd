@echo off
cd /d %~dp0

call venv\Scripts\activate.bat

streamlit run projectCQD.py --server.address 0.0.0.0 --server.port 8501

pause
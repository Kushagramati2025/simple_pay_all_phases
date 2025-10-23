import subprocess, sys, pathlib

def main():
    try:
        app = pathlib.Path(__file__).with_name("main.py")
        # Launch Streamlit correctly so SessionContext exists
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app), "--server.fileWatcherType=watchdog"],check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while trying to run the Streamlit app: {e}")
main()
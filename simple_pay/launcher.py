# import streamlit.web.bootstrap
# import os
# from streamlit import config

# if __name__ == "__main__":
#     config.set_option("server.port", 3000)
#     config.set_option("server.address", "localhost")
    
#     # Path to your actual Streamlit script
#     script_path = os.path.join(os.path.dirname(__file__), "main.py")
#     print(script_path)
#     streamlit.web.bootstrap.run(script_path, "", [], {})


# import os
# import streamlit.web.cli as stcli
# import sys

# if getattr(sys, 'frozen', False):
#     # Running in PyInstaller bundle
#     base_path = sys._MEIPASS
# else:
#     # Running in normal Python
#     base_path = os.path.dirname(__file__)
    
# if __name__ == "__main__":
#     script_path = os.path.join(os.path.dirname(__file__), "main.py")
#     sys.argv = ["streamlit", "run", script_path, "--server.port=3000", "--server.address=localhost"]
#     sys.exit(stcli.main())


# import os
# import streamlit.web.bootstrap

# if __name__ == "__main__":
#     script_path = os.path.join(os.path.dirname(__file__), "main.py")
#     streamlit.web.bootstrap.run(
#         script_path,
#         args=[],
#         is_hello=False,
#         flag_options={"server.port": 8001, "server.address": "0.0.0.0"}
#     )



# import os
# import sys
# import streamlit.web.cli as stcli

# if __name__ == "__main__":
#     # Disable file watcher inside PyInstaller bundle
#     os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"

#     script_path = os.path.join(os.path.dirname(__file__), "main.py")
    
#     sys.argv = ["streamlit", "run", script_path, "--server.port=8501", "--server.address=0.0.0.0"]
#     sys.exit(stcli.main())


import streamlit.web.bootstrap
import os
from streamlit import config
import sys

if __name__ == "__main__":
    config.set_option("server.port", 3000)
    config.set_option("server.address", "localhost")

    if getattr(sys, 'frozen', False):
        script_path = os.path.join(sys._MEIPASS, "main.py")
    else:
        script_path = os.path.join(os.path.dirname(__file__), "main.py")

    print(script_path)
    streamlit.web.bootstrap.run(script_path, "", [], {})
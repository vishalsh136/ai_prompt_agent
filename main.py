"""
main.py — Launcher for the Indian Market Study Tool
=====================================================
Run this file to start the Streamlit application:

    python main.py

Or equivalently:

    streamlit run app.py

⚠️  EDUCATIONAL USE ONLY. Not financial advice. See README.md for details.
"""

import subprocess
import sys


def main() -> None:
    """Launch the Streamlit app via subprocess."""
    print("Starting Indian Market Study Tool …")
    print("Open http://localhost:8501 in your browser if it doesn't open automatically.")
    print("Press Ctrl+C to stop the server.")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "false"],
        check=True,
    )


if __name__ == "__main__":
    main()

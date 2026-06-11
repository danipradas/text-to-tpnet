# text-to-tpnet
Repository for the source code of an AI model that converts natural language to Ecler's TP-NET protocol commands.

<img src="https://github.com/user-attachments/assets/2e10f877-7a55-47df-90e4-c542e0f3f690" alt="Image" width="400">

## About TP-NET
TP-NET is a protocol developed by Ecler to control their audio devices. It is a text-based protocol that allows users to send commands to the devices. The protocol is based on a set of commands that are sent to the device to control its functionalities, such as volume control, input selection, and power management, among others. The commands are sent in plain text format, making it easy to implement and use.

This project currently targets the **VIDA series only**. The TP-NET protocol itself also covers the HUB and MIMO series, and extending support to those families is a possible future direction (it would require a dedicated system prompt and schema per device family — see `config/model_config.json`).

More information about the TP-NET protocol can be found in the [official documentation](https://media.ecler.com/1702317974-ecler-tp-net-protocol-en.pdf).

## About the project
This project aims to develop an AI model that converts natural language commands to TP-NET protocol commands. Supports speech or text input and returns the corresponding TP-NET command. The model is built using the `llama-3.3-70b-versatile` LLM from Meta AI, and deployed using Groq cloud and Streamlit for the web UI. 


## Setting a local environment

### 0. Prerequisites

Recommended to have Python 3.12 or higher. If you are using Windows as the operating system, you may download the [Windows Installer (64-bit)](https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe) executable. If you are using macOS, you may download the [macOS 64-bit universal2 installer](https://www.python.org/ftp/python/3.12.6/python-3.12.6-macos11.pkg) version. For other operating systems or specific versions, check out the [release page](https://www.python.org/downloads/release/python-3126/) of the Python version.


**Important**: Make sure to check the box **"Add Python 3.12 to PATH"** during the installation process.


### 1. Clone the repository
Clone our repository to your local machine using the following command:
```bash
git clone https://github.com/daniampr/text-to-tpnet.git
```

### 2. Create a virtual environment
Create a virtual environment in the root directory of the project:
```bash
python -m venv .venv
```
To activate the virtual environment, run:
```bash
source .venv/bin/activate # For MacOS / Linux
.\.venv\Scripts\activate  # For Windows
```

### 3. Install the dependencies
Install the required dependencies using the following command:
```bash
pip install -r requirements.txt
```

### 4. Set up API keys
The application reads its API keys from `.streamlit/secrets.toml` via `st.secrets[...]` (not from environment variables). You need:
- `GROQ_API_KEY`: Your Groq API key for accessing the LLM model. You can obtain it for free by signing up on the [Groq website](https://console.groq.com/home?utm_source=website&utm_medium=outbound_link&utm_campaign=dev_console_click).
- `OPENAI_API_KEY`: Your OpenAI API key for accessing the Whisper model for speech recognition.

Copy the example file and fill in your keys:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Then, open the `.streamlit/secrets.toml` file and replace the placeholder values with your actual API keys:
```toml
GROQ_API_KEY = "your_groq_api_key_here"
OPENAI_API_KEY = "your_openai_api_key_here"
```

### 5. Run the application
To run the application, execute the command:
```bash
streamlit run app.py
```

## Using TP-NET from Claude Desktop (MCP server)

The repo also ships an MCP server, `server.py`, that exposes the same UDP + parser layer as the Streamlit app over the Model Context Protocol. Any MCP client (e.g. Claude Desktop) can drive the VIDA device using natural language — the *client's* LLM produces the structured TP-NET command, and the server sends it.

The server exposes two tools:
- `tpnet_get_device_status` — runs `GET ALL` and returns the parsed device state as JSON.
- `tpnet_send_command` — sends any TP-NET command (GET/SET/INC/DEC/SUBSCRIBE/UNSUBSCRIBE/SYSTEM); for SET/INC/DEC it auto-issues a follow-up GET because TP-NET does not ACK those.

The target device IP is **not** an LLM-controllable parameter; it is read from the `TPNET_DEVICE_IP` environment variable. `SYSTEM CONNECT` is issued lazily on the first tool call and reused for the rest of the process lifetime.

Add this entry to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), adjusting the absolute paths and the IP for your environment:

```json
{
  "mcpServers": {
    "tpnet": {
      "command": "C:\\ecler_projects\\tfg-2\\text-to-tpnet\\.venv\\Scripts\\python.exe",
      "args":    ["C:\\ecler_projects\\tfg-2\\text-to-tpnet\\server.py"],
      "env":     { "TPNET_DEVICE_IP": "192.168.1.50" }
    }
  }
}
```

Restart Claude Desktop; the `tpnet` server should appear in the MCP panel and Claude will be able to call both tools. The Streamlit app is unaffected — `server.py` is a second, independent entry point.

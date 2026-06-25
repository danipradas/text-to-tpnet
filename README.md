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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) — it manages both Python and the virtual environment, so no separate Python installation is required:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 1. Clone the repository
```bash
git clone https://github.com/daniampr/text-to-tpnet.git
cd text-to-tpnet
```

### 2. Install dependencies
`uv sync` creates the `.venv` and installs all dependencies declared in `pyproject.toml` in one step:
```bash
uv sync
```

### 3. Set up API keys
The application reads its API key from `.streamlit/secrets.toml` via `st.secrets[...]` (not from environment variables). You need:
- `GROQ_API_KEY`: Your Groq API key, used for both the LLM (`llama-3.3-70b-versatile`) and speech recognition (`whisper-large-v3-turbo`). You can obtain it for free by signing up on the [Groq website](https://console.groq.com/home?utm_source=website&utm_medium=outbound_link&utm_campaign=dev_console_click).

Copy the example file and fill in your key:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Then, open the `.streamlit/secrets.toml` file and replace the placeholder value with your actual API key:
```toml
GROQ_API_KEY = "your_groq_api_key_here"
```

### 4. Run the application
```bash
uv run streamlit run app.py
```

## Using TP-NET from Claude Desktop (MCP server)

The repo also ships an MCP server, `server.py`, that exposes the same UDP + parser layer as the Streamlit app over the Model Context Protocol. Any MCP client (e.g. Claude Desktop) can drive the VIDA device using natural language — the *client's* LLM produces the structured TP-NET command, and the server sends it.

The server exposes two tools:
- `tpnet_get_device_status` — runs `GET ALL` and returns the parsed device state as JSON.
- `tpnet_send_command` — sends any TP-NET command (GET/SET/INC/DEC/SUBSCRIBE/UNSUBSCRIBE/SYSTEM); for SET/INC/DEC it auto-issues a follow-up GET because TP-NET does not ACK those.

Device IP is resolved per tool call in this order:
1. `device_ip` argument passed to the tool — filled by the LLM when the user asks to target a specific IP (e.g. *"connect to 192.168.1.50"*).
2. `DEFAULT_DEVICE_IP` environment variable — the server's default, set in the MCP client config (optional).
3. If neither is available, the tool returns a clear error asking the user to provide an IP.

`SYSTEM CONNECT` is issued lazily on the first call to each device IP and reused for the rest of the process lifetime. State (connection handshake + parsed device data) is tracked per IP, so the server can address multiple VIDA devices in the same session without them interfering with each other.

Add this entry to your Claude Desktop config:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Replace `<PATH_TO_PROJECT>` with the absolute path to the cloned repo. `uv` must be on your `PATH` (it is, after running the installer above).

**With a default device IP** (omit the `env` block if you always want to specify the IP in chat):

```json
{
  "mcpServers": {
    "tpnet": {
      "command": "uv",
      "args":    ["run", "--directory", "<PATH_TO_PROJECT>", "python", "server.py"],
      "env":     { "DEFAULT_DEVICE_IP": "<DEVICE_IP>" }
    }
  }
}
```

**Without a default** (user must name an IP in every conversation):

```json
{
  "mcpServers": {
    "tpnet": {
      "command": "uv",
      "args":    ["run", "--directory", "<PATH_TO_PROJECT>", "python", "server.py"]
    }
  }
}
```

Restart Claude Desktop; the `tpnet` server should appear in the MCP panel and Claude will be able to call both tools. The Streamlit app is unaffected — `server.py` is a second, independent entry point.

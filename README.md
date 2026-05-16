# text-to-tpnet
Repository for the source code of an AI model that converts natural language to Ecler's TP-NET protocol commands.

<img src="https://github.com/user-attachments/assets/2e10f877-7a55-47df-90e4-c542e0f3f690" alt="Image" width="400">

## About TP-NET
TP-NET is a protocol developed by Ecler to control their audio devices. It is a text-based protocol that allows users to send commands to the devices. The protocol is based on a set of commands that are sent to the device to control its functionalities, such as volume control, input selection, and power management, among others. The commands are sent in plain text format, making it easy to implement and use.
Available devices that support TP-NET protocol in this project are:
- VIDA series
- HUB series
- MIMO series

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
To run the application, you need to set up the following API keys as environment variables:
- `GROQ_API_KEY`: Your Groq API key for accessing the LLM model. You can obtain it for free by signing up on the [Groq website](https://console.groq.com/home?utm_source=website&utm_medium=outbound_link&utm_campaign=dev_console_click).
- `OPENAI_API_KEY`: Your OpenAI API key for accessing the Whisper model for speech recognition
You can set the environment variables in your terminal using the following commands:
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

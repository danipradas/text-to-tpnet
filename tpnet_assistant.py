from typing import List, Literal
import os

from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import BaseModel, Field
import socket
import json
import logging
import jsonschema
import streamlit as st


class TPNetCommand(BaseModel):
    """A single TP-NET protocol message for an Ecler VIDA device."""

    type: Literal[
        "GET", "SET", "SYSTEM", "INC", "DEC", "SUBSCRIBE", "UNSUBSCRIBE"
    ] = Field(description="TP-NET message TYPE keyword.")
    command: str = Field(
        description=(
            "TP-NET command keyword (second token), e.g. OLEVEL,"
            " POWER, PRESET. Must be valid for the chosen 'type'"
            " per the system prompt."
        )
    )
    params: List[str] = Field(
        description=(
            "Ordered parameter tokens for the command, as strings."
            " Use an empty list when the command takes no parameters."
        )
    )


logger = logging.getLogger("tpnet_assistant")


with open('config/model_config.json') as f:
    model_config = json.load(f)

model = 'gpt-5.4-mini'

llm = ChatOpenAI(
    model=model,
    temperature=0,
    max_tokens=2000,
    max_retries=2,
    api_key=st.secrets['OPENAI_API_KEY'],
)

openai_client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

WHISPER_MODEL = "whisper-1"


def transcribe(audio_file: str) -> str:
    """Transcribe an audio file to text using OpenAI's Whisper endpoint.

    Parameters:
        audio_file (str): Path to the audio file to transcribe.
    Returns:
        str: The transcribed text.
    """
    logger.debug("Transcribing audio file: %s", audio_file)
    with open(audio_file, "rb") as f:
        transcription = openai_client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=(os.path.basename(audio_file), f.read()),
        )
    logger.debug("Whisper transcription: %r", transcription.text)
    return transcription.text


def get_struct_tpnet_response(user_prompt: str) -> dict:
    '''
    Obtains the TP-NET command output from the model, forcing the response
    to follow the TP-NET command structure (VIDA devices only).
    Parameters:
        user_prompt (str): The user prompt to send to the model.
    Returns:
        dict: {"type": str, "command": str, "params": list[str]}
    '''
    try:
        logger.debug("get_struct_tpnet_response prompt=%r", user_prompt)
        structured = llm.with_structured_output(TPNetCommand)
        messages = [
            {"role": "system",
             "content": model_config["system_prompt_VIDA"]
             },
            {"role": "user", "content": user_prompt}
        ]
        result: TPNetCommand = structured.invoke(messages)
        response = result.model_dump()
        logger.debug("LLM structured response: %r", response)
        return response
    except Exception as exc:
        logger.exception("Failed to obtain structured TP-NET response")
        raise RuntimeError(
            f"LLM call failed ({type(exc).__name__}): {exc}"
        ) from exc


def parse_output(output: dict) -> str:
    '''
    Checks if the output is valid according to the schema and returns the
    formatted TPNET command to send to the device.
    Parameters:
        output (dict): The structured output from the model.
    Returns:
        str: The formatted TPNET command to send to the device.
    '''
    jsonschema.validate(output, model_config["schema"])
    params = "".join(f" {p}" for p in output['params'])
    return f"{output['type']} {output['command']}{params}\n"


# Configure the VIDA device
PORT = 5800  # UDP port 5800
BUFFER_SIZE = 4096  # Buffer size for receiving data

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_tpnet_command(
        command: str, timeout: float = 2.0, refresh=True) -> str:
    """Send a TPnet command to the Ecler device.
    Parameters:
        command (str): The TP-net command to send.
        refresh (bool): If True, call ``refresh_device_data()`` after the
            reply is drained. Internal helpers that are themselves invoked
            from ``refresh_device_data`` (e.g. ``verify_set``) MUST pass
            ``refresh=False`` to avoid an infinite GET-ALL loop.

    Returns:
        str: The full response received from the device.
    """
    device_ip = st.session_state.device_ip
    try:
        # Send the command to the device
        logger.info(
            "TP-NET -> %s:%d %r (timeout=%.2fs)",
            device_ip, PORT, command, timeout,
        )
        sock.sendto(command.encode(), (device_ip, PORT))

        # Receive the response from the device
        response = []
        sock.settimeout(timeout)
        while True:
            try:
                data, addr = sock.recvfrom(4096)  # Buffer size is 4096 bytes
                chunk = data.decode()
                logger.debug("TP-NET <- %s %r", addr, chunk)
                response.append(chunk)
            except socket.timeout:
                break

        # Combine the response into a single string
        full_response = "".join(response)
        logger.info(
            "TP-NET full response (%d bytes):\n%s",
            len(full_response), full_response,
        )

        # Update the device data
        refresh_device_data() if refresh else None

        return full_response

    except Exception as e:
        logger.exception("send_tpnet_command failed: %s", e)
        raise


def verify_set(cmd: dict) -> str:
    """Read back the device state after a SET/INC/DEC, which TP-NET
    does not acknowledge by protocol.

    Re-issues a GET using the same command keyword and the addressing
    tokens (every parameter except the trailing value/flag), so the
    DATA line the device replies with reflects what it actually stored.
    """
    command = cmd["command"]
    params = cmd.get("params") or []
    addressing = params[:-1] if params else []
    suffix = (" " + " ".join(addressing)) if addressing else ""
    wire = f"GET {command}{suffix}\n"
    logger.debug("verify_set wire=%r", wire)
    return send_tpnet_command(wire, timeout=1.5, refresh=False)


# -------------------------------
# Helper function: parse GET ALL
# -------------------------------


def refresh_device_data():
    logger.debug("Refreshing device data (GET ALL)")
    response = send_tpnet_command("GET ALL\n", timeout=1, refresh=False)
    parse_device_data(response)
    return response


def parse_device_data(data_response: str):
    """
    Parses a multi-line TP-NET response (from GET ALL, etc.) and stores each
    recognized DATA line in st.session_state["device_data"] (VIDA only).
    """

    # Ensure we have a device_data dict with all possible keys
    if "device_data" not in st.session_state:
        st.session_state["device_data"] = {
            "olevel": {},
            "omute": {},
            "slevel": {},
            "smute": {},
            "xlevel": {},
            "xmute": {},
            "gmute": {},
            "glevel": {},
            "info": {},
            "power": "",
            "preset": "",
            "gpi": {},   # GPI <Input> <Value>
            "gpo": {},   # GPO <Output> <Value>
        }

    lines = data_response.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line.startswith("DATA"):
            continue

        parts = line.split(maxsplit=2)  # e.g. ["DATA","OLEVEL","1 35"]
        if len(parts) < 2:
            continue

        tag = parts[1]       # e.g. "OLEVEL", "ILEVEL", "INAME"
        rest = parts[2] if len(parts) >= 3 else ""

        # Split the remainder to handle parameters
        tokens = rest.split()

        # ------------------------------------------------------------
        #  Existing VIDA fields first (SLEVEL, OLEVEL, SMUTE, etc.)
        # ------------------------------------------------------------
        if tag == "OLEVEL":
            # OLEVEL <channel> <value>
            if len(tokens) >= 2:
                ch, level_str = tokens[0], tokens[1]
                try:
                    st.session_state[
                        "device_data"]["olevel"][ch] = float(level_str)
                except ValueError:
                    pass

        elif tag == "SLEVEL":
            # SLEVEL <source> <value>
            if len(tokens) >= 2:
                src, level_str = tokens[0], tokens[1]
                try:
                    st.session_state[
                        "device_data"]["slevel"][src] = float(level_str)
                except ValueError:
                    pass

        elif tag == "OMUTE":
            # OMUTE <channel> YES/NO
            if len(tokens) >= 2:
                ch, status = tokens[0], tokens[1]
                st.session_state["device_data"]["omute"][ch] = status

        elif tag == "SMUTE":
            # SMUTE <source> YES/NO
            if len(tokens) >= 2:
                src, status = tokens[0], tokens[1]
                st.session_state["device_data"]["smute"][src] = status

        elif tag == "XLEVEL":
            # XLEVEL <source> <out_ch> <value>
            if len(tokens) >= 3:
                src, out_ch, level_str = tokens[0], tokens[1], tokens[2]
                try:
                    st.session_state[
                        "device_data"]["xlevel"][(src, out_ch)] = float(
                            level_str)
                except ValueError:
                    pass

        elif tag == "XMUTE":
            # XMUTE <source> <out_ch> YES/NO
            if len(tokens) >= 3:
                src, out_ch, status = tokens[0], tokens[1], tokens[2]
                st.session_state[
                    "device_data"]["xmute"][(src, out_ch)] = status

        elif tag == "GMUTE":
            # GMUTE <Loc/Net/Gen> <groupNum?> YES/NO
            if len(tokens) == 2:
                group_type, status = tokens
                st.session_state[
                    "device_data"]["gmute"][(group_type,)] = status
            elif len(tokens) == 3:
                group_type, group_id, status = tokens
                st.session_state[
                    "device_data"]["gmute"][(group_type, group_id)] = status

        elif tag == "GLEVEL":
            # GLEVEL <Loc/Net/Gen> <groupNum?> <level>
            if len(tokens) == 2:
                group_type, level_str = tokens
                try:
                    st.session_state[
                        "device_data"
                    ]["glevel"][(group_type,)] = float(level_str)
                except ValueError:
                    pass
            elif len(tokens) == 3:
                group_type, group_id, level_str = tokens
                try:
                    st.session_state[
                        "device_data"
                    ]["glevel"][(group_type, group_id)] = float(level_str)
                except ValueError:
                    pass

        elif tag == "POWER":
            # POWER RUNNING/SLEEPING
            st.session_state["device_data"]["power"] = rest

        elif tag == "PRESET":
            # PRESET "User Preset 02"
            st.session_state["device_data"]["preset"] = rest.strip()

        elif tag == "INFO_NAME":
            st.session_state[
                "device_data"]["info"]["name"] = rest.strip().strip('"')

        elif tag == "INFO_MODEL":
            st.session_state["device_data"]["info"]["model"] = rest.strip()

        elif tag == "INFO_VERSION":
            st.session_state["device_data"]["info"]["version"] = rest.strip()

        elif tag == "INFO_MAC":
            # INFO_MAC <NET1/NET2/..> <MAC>
            net_tokens = rest.split()
            if len(net_tokens) >= 2:
                net_interface, mac_addr = net_tokens[0], net_tokens[1]
                if "mac" not in st.session_state["device_data"]["info"]:
                    st.session_state["device_data"]["info"]["mac"] = {}
                st.session_state[
                    "device_data"]["info"]["mac"][net_interface] = mac_addr

        elif tag == "IP_CONFIG":
            # IP_CONFIG <NET1/NET2> <IP> <Netmask> <Gateway>
            net_tokens = rest.split()
            if len(net_tokens) >= 4:
                net_interface = net_tokens[0]
                ip_addr = net_tokens[1]
                netmask = net_tokens[2]
                gateway = net_tokens[3]
                if "ip_config" not in st.session_state["device_data"]["info"]:
                    st.session_state["device_data"]["info"]["ip_config"] = {}
                st.session_state[
                    "device_data"]["info"]["ip_config"][net_interface] = {
                    "ip": ip_addr,
                    "netmask": netmask,
                    "gateway": gateway
                }

        elif tag == "GPI":
            # GPI <Input> <Value>
            if len(tokens) >= 2:
                ch, val_str = tokens[0], tokens[1]
                st.session_state["device_data"]["gpi"][ch] = val_str

        elif tag == "GPO":
            # GPO <Output> <Value>
            if len(tokens) >= 2:
                out_ch, val_str = tokens[0], tokens[1]
                st.session_state["device_data"]["gpo"][out_ch] = val_str

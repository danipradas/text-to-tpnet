#!/usr/bin/env python3
"""Local STDIO MCP server for Ecler TP-NET (VIDA devices).

Mirrors the UDP transport + DATA parser of tpnet_assistant.py (without
Streamlit, Groq, or Whisper) so any MCP client (e.g. Claude Desktop) can
drive a VIDA device using natural language. The client's LLM produces the
structured TP-NET command; this server just sends it over UDP and parses
the reply.

Device IP resolution per tool call:
  1. `device_ip` argument passed to the tool (user asked to target a specific IP)
  2. `DEFAULT_DEVICE_IP` environment variable (set in the MCP client config)
  3. RuntimeError if neither is available

State (SYSTEM CONNECT handshake + parsed device data) is tracked per IP so
the server can address multiple devices in the same process without leaking
connection or cache state between them.
"""

import json
import logging
import os
import socket
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

PORT = 5800
BUFFER_SIZE = 4096
DEFAULT_TIMEOUT = 2.0

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_default_device_ip: str | None = os.environ.get("DEFAULT_DEVICE_IP")

# Per-IP connection and data state.
_connected_ips: set[str] = set()
_device_data_by_ip: dict[str, dict] = {}

# STDIO MCP uses stdout for JSON-RPC; logging.basicConfig defaults to
# stderr, which is what we want. Never `print()` in this file.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tpnet_mcp")

mcp = FastMCP("tpnet_mcp")


# ---------------------------------------------------------------------------
# Per-IP state helpers
# ---------------------------------------------------------------------------

def _blank_device_data() -> dict:
    return {
        "olevel": {}, "omute": {},
        "slevel": {}, "smute": {},
        "xlevel": {}, "xmute": {},
        "glevel": {}, "gmute": {},
        "info": {}, "power": "", "preset": "",
        "gpi": {}, "gpo": {},
    }


def _device_state(ip: str) -> dict:
    if ip not in _device_data_by_ip:
        _device_data_by_ip[ip] = _blank_device_data()
    return _device_data_by_ip[ip]


def _resolve_ip(device_ip: str | None) -> str:
    ip = device_ip or _default_device_ip
    if not ip:
        raise RuntimeError(
            "No device IP available. Either pass `device_ip` to the tool "
            "call (e.g. when the user specifies an IP), or set "
            "`DEFAULT_DEVICE_IP` in the MCP client config env block and "
            "restart the server."
        )
    return ip


# ---------------------------------------------------------------------------
# UDP transport + DATA parsing (ported from tpnet_assistant.py)
# ---------------------------------------------------------------------------

def _send(command: str, device_ip: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Send one TP-NET wire command to `device_ip` and drain replies until timeout."""
    logger.info("TP-NET -> %s:%d %r", device_ip, PORT, command)
    _sock.sendto(command.encode(), (device_ip, PORT))
    _sock.settimeout(timeout)
    chunks: list[str] = []
    while True:
        try:
            data, _addr = _sock.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            break
        chunks.append(data.decode())
    reply = "".join(chunks)
    logger.info("TP-NET <- (%d bytes) %r", len(reply), reply)
    return reply


def _verify_set(command: str, params: list[str], device_ip: str) -> str:
    """Re-issue a GET after a SET/INC/DEC (which TP-NET never ACKs).

    Strips the trailing value/flag and asks the device for the addressing
    part, so the DATA line returned reflects what the device actually
    stored. Mirrors `verify_set` in tpnet_assistant.py.
    """
    addressing = params[:-1] if params else []
    suffix = (" " + " ".join(addressing)) if addressing else ""
    return _send(f"GET {command}{suffix}\n", device_ip, timeout=1.5)


def _parse_device_data(raw: str, device_ip: str) -> None:
    """Parse DATA lines (from GET ALL or any reply) into the per-IP state dict."""
    data = _device_state(device_ip)
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line.startswith("DATA"):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        tag = parts[1]
        rest = parts[2] if len(parts) >= 3 else ""
        tokens = rest.split()

        if tag == "OLEVEL" and len(tokens) >= 2:
            try:
                data["olevel"][tokens[0]] = float(tokens[1])
            except ValueError:
                pass
        elif tag == "SLEVEL" and len(tokens) >= 2:
            try:
                data["slevel"][tokens[0]] = float(tokens[1])
            except ValueError:
                pass
        elif tag == "OMUTE" and len(tokens) >= 2:
            data["omute"][tokens[0]] = tokens[1]
        elif tag == "SMUTE" and len(tokens) >= 2:
            data["smute"][tokens[0]] = tokens[1]
        elif tag == "XLEVEL" and len(tokens) >= 3:
            try:
                data["xlevel"][(tokens[0], tokens[1])] = float(tokens[2])
            except ValueError:
                pass
        elif tag == "XMUTE" and len(tokens) >= 3:
            data["xmute"][(tokens[0], tokens[1])] = tokens[2]
        elif tag == "GLEVEL":
            if len(tokens) == 2:
                try:
                    data["glevel"][(tokens[0],)] = float(tokens[1])
                except ValueError:
                    pass
            elif len(tokens) == 3:
                try:
                    data["glevel"][(tokens[0], tokens[1])] = float(tokens[2])
                except ValueError:
                    pass
        elif tag == "GMUTE":
            if len(tokens) == 2:
                data["gmute"][(tokens[0],)] = tokens[1]
            elif len(tokens) == 3:
                data["gmute"][(tokens[0], tokens[1])] = tokens[2]
        elif tag == "POWER":
            data["power"] = rest
        elif tag == "PRESET":
            data["preset"] = rest.strip()
        elif tag == "INFO_NAME":
            data["info"]["name"] = rest.strip().strip('"')
        elif tag == "INFO_MODEL":
            data["info"]["model"] = rest.strip()
        elif tag == "INFO_VERSION":
            data["info"]["version"] = rest.strip()
        elif tag == "INFO_MAC" and len(tokens) >= 2:
            data["info"].setdefault("mac", {})[tokens[0]] = tokens[1]
        elif tag == "IP_CONFIG" and len(tokens) >= 4:
            data["info"].setdefault("ip_config", {})[tokens[0]] = {
                "ip": tokens[1],
                "netmask": tokens[2],
                "gateway": tokens[3],
            }
        elif tag == "GPI" and len(tokens) >= 2:
            data["gpi"][tokens[0]] = tokens[1]
        elif tag == "GPO" and len(tokens) >= 2:
            data["gpo"][tokens[0]] = tokens[1]


def _jsonable(obj):
    """Recursively convert tuple dict keys to 'a|b' strings so the
    matrix and group dicts can be JSON-serialized."""
    if isinstance(obj, dict):
        return {
            ("|".join(k) if isinstance(k, tuple) else str(k)): _jsonable(v)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return obj


def _ensure_connected(device_ip: str) -> None:
    """Idempotent SYSTEM CONNECT — runs once per IP per process lifetime."""
    if device_ip in _connected_ips:
        return
    reply = _send("SYSTEM CONNECT\n", device_ip)
    _parse_device_data(reply, device_ip)
    _connected_ips.add(device_ip)
    logger.info("SYSTEM CONNECT to %s established.", device_ip)


# ---------------------------------------------------------------------------
# Pydantic input model — mirrors TPNetCommand in tpnet_assistant.py:13
# ---------------------------------------------------------------------------

class SendCommandInput(BaseModel):
    """A single TP-NET protocol message for an Ecler VIDA device."""

    type: Literal[
        "GET", "SET", "SYSTEM", "INC", "DEC", "SUBSCRIBE", "UNSUBSCRIBE"
    ] = Field(description="TP-NET message TYPE keyword.")
    command: str = Field(
        description=(
            "TP-NET command keyword (second token), e.g. OLEVEL, POWER, "
            "PRESET. Must be valid for the chosen `type` per the grammar "
            "in the tool description."
        )
    )
    params: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered parameter tokens, as strings. Empty list when the "
            "command takes no parameters."
        ),
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="tpnet_get_device_status",
    annotations={
        "title": "Get full TP-NET device status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def tpnet_get_device_status(
    device_ip: str | None = Field(
        default=None,
        description=(
            "Target device IP address (e.g. '192.168.1.50'). Omit to use "
            "the server's DEFAULT_DEVICE_IP. Fill this when the user asks "
            "to connect to or query a specific IP address."
        ),
    ),
) -> str:
    """Refresh and return the full state of the target VIDA device.

    Sends `GET ALL` and returns the parsed device-state dict as JSON
    (output levels, source levels, matrix points, mutes, group levels,
    info block, power state, preset, GPI/GPO). Matrix/group keys that
    naturally need two tokens are joined with '|' — e.g. xlevel "1|2"
    means source 1 → output channel 2.
    """
    ip = _resolve_ip(device_ip)
    _ensure_connected(ip)
    _parse_device_data(_send("GET ALL\n", ip, timeout=1.0), ip)
    return json.dumps(_jsonable(_device_state(ip)), indent=2)


@mcp.tool(
    name="tpnet_send_command",
    annotations={
        "title": "Send a TP-NET command to the VIDA device",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def tpnet_send_command(
    params: SendCommandInput,
    device_ip: str | None = Field(
        default=None,
        description=(
            "Target device IP address (e.g. '192.168.1.50'). Omit to use "
            "the server's DEFAULT_DEVICE_IP. Fill this when the user asks "
            "to connect to or send a command to a specific IP address."
        ),
    ),
) -> str:
    """Send any TP-NET command to the configured VIDA device.

    Wire format produced: `<TYPE> <COMMAND> <PARAMS...>\\n`.
    Levels (OLEVEL/SLEVEL/XLEVEL) are 0–100 (percent). Mute flags are
    YES/NO. SET PRESET takes 0=factory, 1–10=user.

    For SET / INC / DEC the TP-NET protocol does not ACK; this tool
    auto-issues a follow-up GET with the same addressing tokens and
    returns the resulting DATA line so the caller always has confirmation.

    --- TP-NET command grammar (VIDA) ---

    1) GET commands:
       GET ALL                                   — full status dump (DATA lines)
       GET POWER                                 — RUNNING / SLEEP
       GET PRESET                                — current preset
       GET SLEVEL <Source>                       — source level
       GET OLEVEL <OutputChannel>                — output channel level
       GET XLEVEL <Source> <OutputChannel>       — matrix point level
       GET GLEVEL <Loc/Net/Gen> <Group>          — group level
       GET SMUTE  <Source>                       — source mute
       GET OMUTE  <OutputChannel>                — output channel mute
       GET XMUTE  <Source> <OutputChannel>       — matrix point mute
       GET GMUTE  <Loc/Net/Gen> <Group>          — group mute
       GET SVU    <Source>                       — source VU
       GET OVU    <OutputChannel>                — output channel VU
       GET ALARM_PROTECT <OutputChannel>         — protect-alarm status
       GET ALARM_FAULT   <OutputChannel>         — fault-alarm status
       GET GPI <Input>                           — GPI value
       GET GPO <Output>                          — GPO value
       GET EXTMUTE                               — external mute input
       GET INFO_NAME | INFO_MODEL | INFO_VERSION
       GET INFO_MAC  <NET1/NET2>
       GET IP_CONFIG <NET1/NET2>
       GET IP_LIST                               — registered TP-Net clients

    2) SET commands:
       SET POWER  ON|OFF
       SET PRESET <0..10>                        — 0=factory, 1..10=user
       SET SLEVEL <Source> <Level 0..100>
       SET OLEVEL <OutputChannel> <Level 0..100>
       SET XLEVEL <Source> <OutputChannel> <Level 0..100>
       SET GLEVEL <Loc/Net/Gen> <Group> <Level 0..100>
       SET SMUTE  <Source> YES|NO
       SET OMUTE  <OutputChannel> YES|NO
       SET XMUTE  <Source> <OutputChannel> YES|NO
       SET GMUTE  <Loc/Net/Gen> <Group> YES|NO
       SET GPO    <Output> <Value>

    3) INC / DEC commands (delta-by-Value, 0..100):
       INC|DEC SLEVEL <Source> <Value>
       INC|DEC OLEVEL <OutputChannel> <Value>
       INC|DEC XLEVEL <Source> <OutputChannel> <Value>
       INC|DEC GLEVEL <Loc/Net/Gen> <Group> <Value>

    4) SUBSCRIBE / UNSUBSCRIBE (VU streaming):
       SUBSCRIBE|UNSUBSCRIBE ALL
       SUBSCRIBE|UNSUBSCRIBE SVU <Source>
       SUBSCRIBE|UNSUBSCRIBE OVU <OutputChannel>

    5) SYSTEM:
       SYSTEM CONNECT / DISCONNECT  (CONNECT is auto-issued on first
                                     call; rarely needed manually).
    """
    ip = _resolve_ip(device_ip)
    _ensure_connected(ip)
    suffix = "".join(f" {p}" for p in params.params)
    wire = f"{params.type} {params.command}{suffix}\n"
    reply = _send(wire, ip)
    if params.type == "SYSTEM" and params.command == "DISCONNECT":
        _connected_ips.discard(ip)
    elif params.type in ("SET", "INC", "DEC"):
        reply = _verify_set(params.command, params.params, ip)
    _parse_device_data(reply, ip)
    return reply or "(command sent, no reply)"


if __name__ == "__main__":
    mcp.run()

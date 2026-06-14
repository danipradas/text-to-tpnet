import hashlib
import ipaddress
import logging
import os
import tempfile

import streamlit as st
from audio_recorder_streamlit import audio_recorder
from streamlit_extras.bottom_container import bottom
from tpnet_assistant import (
    get_struct_tpnet_response,
    parse_output,
    transcribe,
    send_tpnet_command,
    parse_device_data,
    refresh_device_data,
    verify_set,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

voice_input = False

st.logo(
    "https://help.ecler.com/hc/theming_assets/01HZKNMDPYB7DDPZFR3J1QZ9Y1",
    size="large"
)
st.title("Text-to-TPNET Assistant 🤖")
with st.expander("ℹ️ Disclaimer"):
    st.caption(
        """
        We appreciate your engagement! This model provides a TP-NET command
        based on your text or speech input. Please note, this is a demo version
        and may have limitations based on usage, and TP-NET commands generated
        may not be accurate or complete. Please verify the output you get.
        """
    )

# 1) IP and Connect
device_ip = st.text_input("Enter the IP address of the TPNET device")
st.session_state["device_ip"] = device_ip

ip_valid = False
if device_ip:
    try:
        ipaddress.ip_address(device_ip)
        ip_valid = True
    except ValueError:
        st.warning("Invalid IP address.")

col_connect, col_refresh = st.columns([2, 1])

with col_connect:
    if st.button(
        "Connect to device with TPNET (SYSTEM CONNECT)", disabled=not ip_valid
    ):
        logger.info("Connecting to device %s", device_ip)
        with st.spinner("Connecting to device..."):
            response = send_tpnet_command("SYSTEM CONNECT\n")
            parse_device_data(response)


with col_refresh:
    if st.button("Refresh Device Data (GET ALL)", disabled=not ip_valid):
        refresh_device_data()
        st.success("Device data refreshed!")


# 2) SIDEBAR Device Controls
st.sidebar.title("Device Controls")

if "device_data" in st.session_state:
    device_data = st.session_state["device_data"]
    # -- Device Info Display --
    st.sidebar.subheader("Device Info")
    info = device_data.get("info", {})
    st.sidebar.write(f"**Name**: {info.get('name','Unknown')}")
    st.sidebar.write(f"**Model**: {info.get('model','Unknown')}")
    st.sidebar.write(f"**Version**: {info.get('version','Unknown')}")
    mac_dict = info.get("mac", {})
    for net_intf, mac_str in mac_dict.items():
        st.sidebar.write(f"**{net_intf} MAC**: {mac_str}")

    ip_config = info.get("ip_config", {})
    for net_intf, ipdata in ip_config.items():
        ip_addr = ipdata["ip"]
        netmask = ipdata["netmask"]
        gateway = ipdata["gateway"]
        st.sidebar.write(
            f"**{net_intf}**: IP={ip_addr} NM={netmask} GW={gateway}")

    st.sidebar.write(f"**Power**: {device_data.get('power','')}")
    st.sidebar.write(f"**Preset**: {device_data.get('preset','')}")

    # -- OLEVEL + OMUTE --
    st.sidebar.subheader("Output Levels (OLEVEL + MUTE)")
    updated_olevels = {}
    updated_omutes = {}
    olevel_dict = device_data.get("olevel", {})
    omute_dict = device_data.get("omute", {})

    for ch, current_level in olevel_dict.items():
        current_mute = omute_dict.get(ch, "NO")

        cols = st.sidebar.columns([3, 1])
        with cols[0]:
            new_level = st.slider(
                f"OLEVEL Ch {ch}",
                min_value=0.0,
                max_value=100.0,
                value=float(current_level),
                step=1.0,
                key=f"olevel_slider_{ch}"
            )
        with cols[1]:
            new_mute_bool = st.checkbox(
                "Mute",
                value=(current_mute == "YES"),
                key=f"omute_checkbox_{ch}"
            )

        updated_olevels[ch] = new_level
        updated_omutes[ch] = new_mute_bool

    # -- SLEVEL + SMUTE --
    st.sidebar.subheader("Source Levels (SLEVEL + MUTE)")
    updated_slevels = {}
    updated_smutes = {}
    slevel_dict = device_data.get("slevel", {})
    smute_dict = device_data.get("smute", {})

    for src, current_level in slevel_dict.items():
        current_mute = smute_dict.get(src, "NO")

        cols = st.sidebar.columns([3, 1])
        with cols[0]:
            new_level = st.slider(
                f"SLEVEL Src {src}",
                min_value=0.0,
                max_value=100.0,
                value=float(current_level),
                step=1.0,
                key=f"slevel_slider_{src}"
            )
        with cols[1]:
            new_mute_bool = st.checkbox(
                "Mute",
                value=(current_mute == "YES"),
                key=f"smute_checkbox_{src}"
            )

        updated_slevels[src] = new_level
        updated_smutes[src] = new_mute_bool

    # -- XLEVEL + XMUTE --
    if "xlevel" in device_data and len(device_data["xlevel"]) > 0:
        st.sidebar.subheader("Matrix Crosspoint (XLEVEL + MUTE)")
        updated_xlevels = {}
        updated_xmutes = {}

        xlevel_dict = device_data["xlevel"]
        xmute_dict = device_data.get("xmute", {})

        for (src, out_ch), current_level in xlevel_dict.items():
            current_mute = xmute_dict.get((src, out_ch), "NO")

            label = f"XLEVEL S{src}→O{out_ch}"
            cols = st.sidebar.columns([3, 1])
            with cols[0]:
                new_level = st.slider(
                    label,
                    min_value=0.0,
                    max_value=100.0,
                    value=float(current_level),
                    step=1.0,
                    key=f"xlevel_slider_{src}_{out_ch}"
                )
            with cols[1]:
                new_mute_bool = st.checkbox(
                    "Mute",
                    value=(current_mute == "YES"),
                    key=f"xmute_checkbox_{src}_{out_ch}"
                )
            updated_xlevels[(src, out_ch)] = new_level
            updated_xmutes[(src, out_ch)] = new_mute_bool
    else:
        updated_xlevels = {}
        updated_xmutes = {}

    # -- Subscribe/Unsubscribe VU --
    st.sidebar.subheader("VU Meter Subscriptions")
    col_sub_all, col_unsub_all = st.sidebar.columns(2)
    with col_sub_all:
        if st.button("Subscribe ALL"):
            send_tpnet_command("SUBSCRIBE ALL\n")
            st.info("Subscribed to all VU-meters.")
    with col_unsub_all:
        if st.button("Unsubscribe ALL"):
            send_tpnet_command("UNSUBSCRIBE ALL\n")
            st.info("Unsubscribed from all VU-meters.")

    # -- Apply Changes Button --
    if st.sidebar.button("Apply Changes"):
        # OLEVEL
        for ch, new_val in updated_olevels.items():
            old_val = device_data["olevel"][ch]
            if old_val != new_val:
                cmd = f"SET OLEVEL {ch} {int(new_val)}\n"
                send_tpnet_command(cmd)
                device_data["olevel"][ch] = new_val

        # OMUTE
        for ch, new_mute_bool in updated_omutes.items():
            old_mute_str = device_data["omute"].get(ch, "NO")
            new_mute_str = "YES" if new_mute_bool else "NO"
            if old_mute_str != new_mute_str:
                cmd = f"SET OMUTE {ch} {new_mute_str}\n"
                send_tpnet_command(cmd)
                device_data["omute"][ch] = new_mute_str

        # SLEVEL
        for src, new_val in updated_slevels.items():
            old_val = device_data["slevel"][src]
            if old_val != new_val:
                cmd = f"SET SLEVEL {src} {int(new_val)}\n"
                send_tpnet_command(cmd)
                device_data["slevel"][src] = new_val

        # SMUTE
        for src, new_mute_bool in updated_smutes.items():
            old_mute_str = device_data["smute"].get(src, "NO")
            new_mute_str = "YES" if new_mute_bool else "NO"
            if old_mute_str != new_mute_str:
                cmd = f"SET SMUTE {src} {new_mute_str}\n"
                send_tpnet_command(cmd)
                device_data["smute"][src] = new_mute_str

        # XLEVEL
        for (src, out_ch), new_val in updated_xlevels.items():
            old_val = device_data["xlevel"][(src, out_ch)]
            if old_val != new_val:
                cmd = f"SET XLEVEL {src} {out_ch} {int(new_val)}\n"
                send_tpnet_command(cmd)
                device_data["xlevel"][(src, out_ch)] = new_val

        # XMUTE
        for (src, out_ch), new_mute_bool in updated_xmutes.items():
            old_mute_str = device_data["xmute"].get((src, out_ch), "NO")
            new_mute_str = "YES" if new_mute_bool else "NO"
            if old_mute_str != new_mute_str:
                cmd = f"SET XMUTE {src} {out_ch} {new_mute_str}\n"
                send_tpnet_command(cmd)
                device_data["xmute"][(src, out_ch)] = new_mute_str

        st.success("Changes applied!")

    # 3) Main Chat Section
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Render conversation
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Audio recorder pinned at bottom
    with bottom():
        audio_data = audio_recorder(pause_threshold=1.0, sample_rate=16000)

    # The pinned chat input
    prompt = st.chat_input("What TPNET command would you like to send?")

    transcribed_prompt = ""

    if audio_data:
        audio_hash = hashlib.md5(audio_data).hexdigest()
        if audio_hash != st.session_state.get("last_audio_hash"):
            st.session_state["last_audio_hash"] = audio_hash
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            st.success("Audio recorded successfully.")
            try:
                with st.spinner("Transcribing..."):
                    transcribed_text = transcribe(tmp_path)
                if transcribed_text and transcribed_text.strip():
                    transcribed_prompt = transcribed_text.strip()
                    voice_input = True
            finally:
                os.remove(tmp_path)

    # If there's typed input or voice input
    if prompt or voice_input:
        final_prompt = transcribed_prompt if voice_input else prompt

        # Append user message
        st.session_state.messages.append(
            {"role": "user", "content": final_prompt}
        )
        with st.chat_message("user"):
            st.markdown(final_prompt)

        # Generate assistant response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    ai_response_dict = get_struct_tpnet_response(
                        final_prompt
                    )
                    tpnet_input = parse_output(ai_response_dict)
                    tpnet_response = send_tpnet_command(tpnet_input, refresh=False)

                    # SET/INC/DEC have no TP-NET acknowledgement — read
                    # the value back so we always have something to show.
                    cmd_type = ai_response_dict["type"]
                    verification = ""
                    if cmd_type in ("SET", "INC", "DEC"):
                        verification = verify_set(ai_response_dict)

                    refresh_device_data()

                    st.markdown(f"**Command Generated**: {tpnet_input}")
                    if verification:
                        st.markdown(
                            f"**Device state**: {verification}"
                        )
                    elif tpnet_response:
                        st.markdown(
                            f"**Response from TPNET**: {tpnet_response}"
                        )
                    else:
                        st.markdown("**Command sent (no reply).**")

                    bubble = (
                        f"{tpnet_input}\n{verification or tpnet_response}"
                    )
                    st.session_state.messages.append(
                        {"role": "assistant", "content": bubble}
                    )
                    voice_input = False

                except Exception as e:
                    logger.exception("Chat request failed")
                    error_message = "An error occurred during your request."
                    st.error(f"{error_message}: {str(e)}")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": error_message}
                    )


else:
    st.sidebar.info(
        "No device data yet. Click 'Refresh Device Data (GET ALL)' after connecting."
    )

"""
VISION — Standalone Autonomous AI Multimodal Operating System.
Supports Interactive CLI Mode (with real-time speech output) and
continuous real-time Voice Mode (Mic listening -> Groq STT -> LLM -> Tools -> Cartesia TTS playback).
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

import asyncio
import argparse
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from vision.config import config
from vision.core.engine import vision_engine
from vision.cognitive.load_balancer import load_balancer
from vision.tools.registry import tool_registry
from vision.perception.audio_stream import audio_stream
from vision.perception.stt import smart_stt
from vision.logger import logger

console = Console()
stt = smart_stt


def print_banner():
    banner = Text("""
 ██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗
 ██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║
 ██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║
 ╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║
  ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║
   ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝
    Autonomous Multimodal AI Operating System
    """, style="bold cyan")
    console.print(Panel(banner, border_style="cyan", subtitle="v1.0.0 Real-Time CLI & Voice OS Engine"))

    table = Table(title="System Endpoints & Active Engine Config", border_style="blue")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Configuration / Status", style="green")

    table.add_row("LLM Load Balancer", f"{len(load_balancer.providers)} endpoints ({config.VISION_LOAD_BALANCER_STRATEGY})")
    table.add_row("Primary LLM", f"Groq ({config.VISION_LLM_MODEL})")
    table.add_row("Fallback / Sub-Agents", f"NVIDIA NIM ({config.VISION_NIM_LLM_MODEL})")
    table.add_row("TTS Engine", f"Cartesia Sonic-2 Neural TTS ({config.CARTESIA_VOICE_ID[:8]}...)")
    table.add_row("STT Engine", f"Smart STT (Groq {config.VISION_STT_MODEL} + Faster-Whisper)")
    table.add_row("Voice Pipeline", "Full-Duplex Interruption (Barge-in) & Pipelined TTFT <300ms")
    table.add_row("Registered Tools", f"{len(tool_registry.get_all_schemas())} tools active")
    table.add_row("Mobile Control", f"ADB -> {config.VISION_PHONE_IP}:{config.VISION_PHONE_PORT}")
    table.add_row("Active Interface", "Interactive Terminal CLI & Voice Mode")

    console.print(table)



async def run_voice_mode():
    """Continuous real-time voice interaction loop: Listen -> STT -> LLM -> Tools -> Speak."""
    await vision_engine.initialize()
    console.print("\n[bold green]VISION Live Voice Mode Active![/bold green]")
    console.print("[cyan]Speak into your microphone. VISION will listen, execute actions, and speak back.[/cyan]")
    console.print("[dim]Press Ctrl+C to switch or exit.[/dim]\n")

    session_id = "voice_session"

    # Initial greeting speech
    greeting = "Yo Nandu! VISION is online and locked in. What's the move today, bro?"
    console.print(f"[bold cyan]VISION:[/bold cyan] {greeting}\n")
    try:
        if vision_engine.tts:
            audio_bytes = await vision_engine.tts.synthesize(greeting)
            from vision.synthesis.player import audio_player
            await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, True)
    except Exception as e:
        logger.error(f"[Voice] Greeting synthesis error: {e}")

    loop = asyncio.get_running_loop()
    consecutive_mic_failures = 0
    pending_wav_bytes = None

    while True:
        try:
            # 1. Record voice phrase on microphone if not already captured from interruption
            if pending_wav_bytes is None:
                with console.status("[bold green]Listening for speech... (speak now)[/bold green]", spinner="dots"):
                    wav_bytes = await loop.run_in_executor(None, audio_stream.record_phrase)
            else:
                wav_bytes = pending_wav_bytes
                pending_wav_bytes = None

            if not wav_bytes:
                consecutive_mic_failures += 1
                if consecutive_mic_failures >= 3:
                    console.print("\n[yellow][!] Microphone input is unavailable or restricted by Windows permissions.[/yellow]")
                    console.print("[cyan]To enable: Go to Windows Settings > Privacy & security > Microphone and turn ON 'Let desktop apps access your microphone'.[/cyan]")
                    console.print("[green]Switching to Interactive CLI (with full spoken voice output)...[/green]\n")
                    await run_cli_mode()
                    return
                await asyncio.sleep(0.5)
                continue

            consecutive_mic_failures = 0

            # 2. Transcribe using Groq Whisper STT
            with console.status("[bold yellow]Transcribing speech (Groq Whisper)...[/bold yellow]", spinner="dots"):
                user_text = await stt.transcribe(wav_bytes)

            if not user_text or len(user_text.strip()) < 2:
                continue

            console.print(f"[bold yellow]You (Spoken) > [/bold yellow]{user_text}")

            if user_text.lower().strip() in ["exit", "quit", "goodbye", "bye"]:
                farewell = "Goodbye! Shutting down VISION."
                console.print(f"[bold cyan]VISION:[/bold cyan] {farewell}")
                if vision_engine.tts:
                    audio_bytes = await vision_engine.tts.synthesize(farewell)
                    from vision.synthesis.player import audio_player
                    await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, True)
                break

            # 3. Process query through LLM, execute tools, synthesize and speak back!
            # Run in full-duplex: while VISION is speaking, listen concurrently on the mic
            process_task = asyncio.create_task(
                vision_engine.process_user_input(
                    user_text=user_text,
                    session_id=session_id,
                    channel="voice",
                    synthesize_voice=True
                )
            )

            # Wait a moment for LLM processing / speech start before launching mic listener
            await asyncio.sleep(0.15)
            listen_task = loop.run_in_executor(None, audio_stream.record_phrase)

            done, pending = await asyncio.wait(
                [process_task, listen_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            if process_task in done:
                try:
                    result = process_task.result()
                    console.print(f"[bold cyan]VISION ({result.get('provider', 'AI')} - {result.get('latency_ms', 0):.0f}ms):[/bold cyan]\n{result.get('response')}\n")
                except Exception as ex:
                    console.print(f"[bold red]VISION error: {ex}[/bold red]\n")
                # Now wait for user's next spoken phrase
                pending_wav_bytes = await listen_task
            else:
                # listen_task returned first -> User interrupted while VISION was speaking!
                pending_wav_bytes = listen_task.result()
                try:
                    await vision_engine.stop_speech()
                    result = await process_task
                    console.print(f"[bold cyan]VISION [Interrupted]:[/bold cyan]\n{result.get('response')}\n")
                except Exception:
                    pass

        except KeyboardInterrupt:
            console.print("\n[bold red]Stopping Voice Mode...[/bold red]")
            break
        except Exception as e:
            console.print(f"[bold red]Voice loop error: {e}[/bold red]\n")
            await asyncio.sleep(1.0)


async def run_cli_mode():
    """Interactive CLI text chat loop with voice output speech."""
    if not vision_engine.is_running:
        await vision_engine.initialize()
    console.print("\n[bold green]VISION CLI Online.[/bold green] Type your message or type 'exit' to quit.\n")

    session_id = "cli_session"
    while True:
        try:
            user_input = console.input("[bold yellow]You > [/bold yellow]").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("[bold red]Shutting down VISION...[/bold red]")
                break

            with console.status("[bold cyan]VISION is thinking & orchestrating...[/bold cyan]", spinner="dots"):
                result = await vision_engine.process_user_input(
                    user_text=user_input,
                    session_id=session_id,
                    channel="cli",
                    synthesize_voice=True # Speaks response aloud through speakers
                )

            console.print(f"[bold cyan]VISION ({result.get('provider', 'AI')} - {result.get('latency_ms', 0):.0f}ms):[/bold cyan]\n{result.get('response')}\n")
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]\n")


async def run_wakeword_mode():
    """Ambient hands-free wake-word listening loop: Sits quietly until 'Hey VISION' is spoken."""
    await vision_engine.initialize()
    from vision.perception.wake_word import wake_word_engine

    console.print("\n[bold green]VISION Hands-Free Wake-Word Mode Active![/bold green]")
    console.print("[cyan]Say [bold white]'Hey VISION'[/bold white] from anywhere in the room to activate.[/cyan]")
    console.print("[dim]Press Ctrl+C to exit.[/dim]\n")

    session_id = "wakeword_session"
    loop = asyncio.get_running_loop()

    while True:
        try:
            # 1. Quiet ambient wake-word listener
            with console.status("[bold cyan]Listening for 'Hey VISION'... (ambient)[/bold cyan]", spinner="pulse"):
                detected = await loop.run_in_executor(None, wake_word_engine.listen_for_wake_word, 30.0)

            if not detected:
                await asyncio.sleep(0.1)
                continue

            console.print("\n[bold green]🎙️ Wake-Word Activated! Listening to your command...[/bold green]")

            # 2. Record voice command after wake-word
            with console.status("[bold green]Listening for command... (speak now)[/bold green]", spinner="dots"):
                wav_bytes = await loop.run_in_executor(None, audio_stream.record_phrase)

            if not wav_bytes:
                console.print("[dim]No speech detected. Returning to ambient listening...[/dim]\n")
                continue

            # 3. Transcribe via Groq Whisper STT
            with console.status("[bold yellow]Transcribing speech (Groq Whisper)...[/bold yellow]", spinner="dots"):
                user_text = await stt.transcribe(wav_bytes)

            if not user_text or len(user_text.strip()) < 2:
                continue

            console.print(f"[bold yellow]You > [/bold yellow]{user_text}")

            if user_text.lower().strip() in ["exit", "quit", "goodbye", "bye"]:
                farewell = "Goodbye, Nandu! Have a great day."
                console.print(f"[bold cyan]VISION:[/bold cyan] {farewell}")
                if vision_engine.tts:
                    audio_bytes = await vision_engine.tts.synthesize(farewell)
                    from vision.synthesis.player import audio_player
                    await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, True)
                break

            # 4. Process command through LLM, execute tools, synthesize and speak back!
            with console.status("[bold cyan]VISION is thinking & orchestrating...[/bold cyan]", spinner="dots"):
                result = await vision_engine.process_user_input(
                    user_text=user_text,
                    session_id=session_id,
                    channel="voice",
                    synthesize_voice=True
                )

            console.print(f"[bold cyan]VISION ({result.get('provider', 'AI')} - {result.get('latency_ms', 0):.0f}ms):[/bold cyan]\n{result.get('response')}\n")

        except KeyboardInterrupt:
            console.print("\n[bold red]Stopping Wake-Word Mode...[/bold red]")
            break
        except Exception as e:
            console.print(f"[bold red]Wake-word loop error: {e}[/bold red]\n")
            await asyncio.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="VISION Autonomous AI System")
    parser.add_argument(
        "--mode",
        choices=["voice", "wake", "cli"],
        default="voice",
        help="Operating mode: 'voice' (continuous direct voice), 'wake' (hands-free 'Hey VISION' trigger), or 'cli' (interactive text terminal)"
    )
    args = parser.parse_args()

    print_banner()

    if args.mode == "cli":
        asyncio.run(run_cli_mode())
    elif args.mode == "wake":
        asyncio.run(run_wakeword_mode())
    else:
        asyncio.run(run_voice_mode())


if __name__ == "__main__":
    main()

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MP3_PATH = PROJECT_ROOT / "public" / "input.mp3"
DEFAULT_MIDI_PATH = PROJECT_ROOT / "public" / "output.mid"

N_FFT = 2048
HOP_LENGTH = 512
VELOCITY = 100
THRESHOLD_RATIO = 0.1
NOTE_DURATION = 0.5

ENV_MP3_PATH = "PIANO_MP3_PATH"
ENV_MIDI_PATH = "PIANO_OUTPUT_MIDI_PATH"

FINAL_MP3_PATH = PROJECT_ROOT / "public" / "output_piano.mp3"
SOUNDFONT_PATH = PROJECT_ROOT / "public" / "soundfont.sf2"
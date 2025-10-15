# ----------------------------------------------------------
# p!ano
# Mac OS에서 GarageBand나 Logic을 이용해서 test 가능
# ----------------------------------------------------------
import numpy as np
import librosa
import pretty_midi
import json

def freq_to_midi(freq: int) -> int:
    """
        주파수를 MIDI 노트로 변환하는 함수

    Args:
        freq (int): frequency value

    Returns:
        int: MIDI
        
    Example:
        -----------------------------
        Frequency → MIDI Note 변환 공식
        -----------------------------
        MIDI = 69 + 12 x log2(f / 440)
        f = 440 Hz → MIDI = 69
        f = 880 Hz → MIDI = 81
        f = 220 Hz → MIDI = 57
        -----------------------------
    """
    return int(np.round(69 + 12 * np.log2(freq / 440.0)))


def talking_piano(config_path):
    # ----------------------------------------------------------
    # 설정
    # ----------------------------------------------------------
    with open(config_path, "r") as config_path:
        configs = json.load(config_path)
    mp3_path = configs["mp3_path"]
    output_midi_path = configs["output_midi_path"]
    n_fft = configs["n_fft"]
    hop_length = configs["hop_length"]
    velocity = configs["velocity"]
    threshold_ratio = configs["threshold_ratio"]
    note_duration = configs["note_duration"]

    # ----------------------------------------------------------
    # 1. MP3 로드
    # ----------------------------------------------------------
    y, sr = librosa.load(mp3_path, sr=44100, mono=True)

    # ----------------------------------------------------------
    # 2. STFT(Short-time Fourier transform) 계산
    # ----------------------------------------------------------
    D = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(D.shape[1]), sr=sr, hop_length=hop_length)

    # ----------------------------------------------------------
    # 3. MIDI 생성 및 frequency 매핑
    # ----------------------------------------------------------
    midi = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0)

    # thrashold는 특정 값 이하면 무시함 너무 많은 건반이 눌리는 것을 방지함
    threshold = threshold_ratio * np.max(D) 

    for t_idx, t in enumerate(times):
        for f_idx, f in enumerate(frequencies):
            if D[f_idx, t_idx] > threshold:
                note_number = freq_to_midi(f)
                # MIDI 범위 0~127 제한
                # MIDI에서는 음 높이(pitch) 가 0부터 127까지만 허용됨
                if 0 <= note_number <= 127:
                    note = pretty_midi.Note(
                        velocity=velocity,
                        pitch=note_number,
                        start=t,
                        end=t + note_duration
                    )
                    piano.notes.append(note)

    midi.instruments.append(piano)
    midi.write(output_midi_path)

    print(f"MIDI 생성 완료: {output_midi_path}")

if __name__ == "__main__":
    configs = "config.json"
    talking_piano(configs)
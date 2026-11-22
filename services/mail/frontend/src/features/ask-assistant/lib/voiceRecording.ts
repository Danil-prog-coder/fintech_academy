const MAX_RECORDING_MS = 120_000;
const SAMPLE_RATE = 16_000;

const encodeWav = async (recording: Blob): Promise<Blob> => {
  // Normalize each browser's recording format to mono PCM for the transcription service.
  const context = new OfflineAudioContext(1, 1, SAMPLE_RATE);
  const decoded = await context.decodeAudioData(await recording.arrayBuffer());
  const samples = Math.min(decoded.length, (MAX_RECORDING_MS / 1000) * SAMPLE_RATE);
  const channels = Array.from({ length: decoded.numberOfChannels }, (_, i) =>
    decoded.getChannelData(i),
  );
  const pcmSize = samples * 2;
  const wav = new ArrayBuffer(44 + pcmSize);
  const header = new DataView(wav);
  const bytes = new Uint8Array(wav);
  const encoder = new TextEncoder();

  bytes.set(encoder.encode('RIFF'), 0);
  header.setUint32(4, 36 + pcmSize, true);
  bytes.set(encoder.encode('WAVEfmt '), 8);
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true); // PCM
  header.setUint16(22, 1, true); // mono
  header.setUint32(24, SAMPLE_RATE, true);
  header.setUint32(28, SAMPLE_RATE * 2, true);
  header.setUint16(32, 2, true);
  header.setUint16(34, 16, true);
  bytes.set(encoder.encode('data'), 36);
  header.setUint32(40, pcmSize, true);

  for (let i = 0; i < samples; i += 1) {
    const mixed = channels.reduce((sum, channel) => sum + (channel[i] ?? 0), 0);
    const amplitude = Math.max(-1, Math.min(1, mixed / channels.length));
    header.setInt16(44 + i * 2, Math.round(amplitude * 32767), true);
  }
  return new Blob([wav], { type: 'audio/wav' });
};

export const recordVoice = async (
  signal: AbortSignal,
  onStart: (stop: () => void) => void,
  onStop: () => void,
): Promise<Blob> => {
  if (
    typeof navigator.mediaDevices === 'undefined' ||
    typeof navigator.mediaDevices.getUserMedia !== 'function' ||
    typeof MediaRecorder === 'undefined'
  ) {
    throw new Error('Для записи нужен браузер с доступом к микрофону и защищённое соединение.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  let recording: Blob;
  try {
    signal.throwIfAborted();
    const recorder = new MediaRecorder(stream);
    recording = await new Promise<Blob>((resolve, reject) => {
      const chunks: Blob[] = [];
      const stop = () => {
        if (recorder.state !== 'inactive') {
          recorder.stop();
        }
      };
      const timeout = window.setTimeout(stop, MAX_RECORDING_MS);
      const cancel = () => {
        window.clearTimeout(timeout);
        reject(new DOMException('Запись отменена', 'AbortError'));
      };
      const cleanup = () => {
        window.clearTimeout(timeout);
        signal.removeEventListener('abort', cancel);
      };
      signal.addEventListener('abort', cancel, { once: true });
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = () => {
        onStop();
        cleanup();
        resolve(new Blob(chunks, { type: recorder.mimeType }));
      };
      recorder.onerror = () => {
        cleanup();
        reject(new Error('Запись прервана. Попробуйте снова.'));
      };
      try {
        recorder.start(250);
        onStart(stop);
      } catch (error) {
        cleanup();
        reject(error instanceof Error ? error : new Error('Не удалось начать запись.'));
      }
    });
  } finally {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  }
  if (!recording.size) {
    throw new Error('Запись пуста. Попробуйте снова.');
  }
  return encodeWav(recording);
};

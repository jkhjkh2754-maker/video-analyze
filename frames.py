"""Stage 3: local periodic/scene frames with visual deduplication."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from analyzer import write_json


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    if data and len(data) != size:
        raise ValueError('Incomplete decoded frame')
    return bytes(data)


def fingerprint(rgb):
    # RGB thumbnail retains color differences that grayscale hashes miss.
    return bytes(rgb[(y * 640 + x) * 3 + c]
                 for y in range(5, 360, 10) for x in range(5, 640, 10)
                 for c in range(3))


def distance(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / (len(a) * 255)


def extract_frames(source, output=Path('outputs'), interval=10.0,
                   scene_threshold=0.3, similarity_threshold=0.03, max_images=120):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('입력 영상 파일이 없습니다.')
    if (not math.isfinite(interval) or interval <= 0 or
        not math.isfinite(scene_threshold) or not 0 <= scene_threshold <= 1 or
        not math.isfinite(similarity_threshold) or not 0 <= similarity_threshold <= 1 or
        not isinstance(max_images, int) or max_images <= 0):
        raise ValueError('간격·최대 수는 양수, 임계값은 0~1이어야 합니다.')
    folder = Path(output).resolve() / ('frames-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    result = {'stage': 3, 'status': 'running', 'source_file': str(source),
              'settings': {'interval_seconds': interval, 'scene_threshold': scene_threshold,
                           'similarity_threshold': similarity_threshold, 'max_images': max_images},
              'frames': [], 'duplicates_removed': 0, 'limit_reached': False}
    write_json(folder / 'frames.json', result)
    # Fixed media-relative time buckets preserve periodic selection across scene cuts.
    select = f"setpts=PTS-STARTPTS,select='isnan(prev_pts)+gt(floor(t/{interval}),floor(prev_t/{interval}))+gt(scene,{scene_threshold})',showinfo,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1"
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-i', str(source), '-map', '0:v:0',
               '-an', '-vf', select, '-fps_mode', 'vfr', '-pix_fmt', 'rgb24',
               '-f', 'rawvideo', 'pipe:1']
    signatures, selected = [], []
    process = None
    try:
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log)
            try:
                candidate_index = 0
                while True:
                    rgb = read_exact(process.stdout, 640 * 360 * 3)
                    if not rgb:
                        break
                    signature = fingerprint(rgb)
                    duplicate = next((i for i, old in enumerate(signatures)
                                      if distance(signature, old) <= similarity_threshold), None)
                    if duplicate is not None:
                        result['duplicates_removed'] += 1
                    else:
                        filename = f'frame-{len(selected) + 1:04d}.png'
                        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'rawvideo',
                                        '-pix_fmt', 'rgb24', '-s', '640x360', '-i', 'pipe:0',
                                        '-frames:v', '1', str(folder / filename)],
                                       input=rgb, capture_output=True, check=True, timeout=30)
                        selected.append((candidate_index, filename))
                        signatures.append(signature)
                        if len(selected) >= max_images:
                            result['limit_reached'] = True
                            process.terminate()
                            break
                    candidate_index += 1
            finally:
                process.stdout.close()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            log.seek(0)
            details = log.read().decode('utf-8', errors='replace')
            timestamps = [float(s) for s in re.findall(r'\bn:\s*\d+\s+pts:.*?pts_time:([\d.eE+\-]+)', details)]
            if process.returncode and not result['limit_reached']:
                raise ValueError('FFmpeg decoding failed: ' + details[-2000:])
            for index, filename in selected:
                if index >= len(timestamps):
                    raise ValueError('프레임 타임스탬프 누락')
                seconds = timestamps[index]
                result['frames'].append({'file': filename, 'timestamp_seconds': seconds,
                                         'timestamp': f'{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{seconds % 60:06.3f}'})
            if not selected:
                raise ValueError('추출 가능한 영상 프레임이 없습니다.')
            result['status'] = 'extracted'
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if process and process.poll() is None:
            process.kill()
            process.wait()
        result.update(status='failed', error=str(exc))
    result['image_count'] = len(result['frames'])
    write_json(folder / 'frames.json', result)
    return folder, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='2단계에서 확보한 영상 또는 로컬 영상')
    parser.add_argument('--output', type=Path, default=Path('outputs'))
    parser.add_argument('--interval', type=float, default=10)
    parser.add_argument('--scene-threshold', type=float, default=0.3)
    parser.add_argument('--similarity-threshold', type=float, default=0.03)
    parser.add_argument('--max-images', type=int, default=120)
    args = parser.parse_args()
    try:
        folder, result = extract_frames(args.source, args.output, args.interval,
                                        args.scene_threshold, args.similarity_threshold, args.max_images)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({'directory': str(folder), **result}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'extracted' else 1


if __name__ == '__main__':
    raise SystemExit(main())

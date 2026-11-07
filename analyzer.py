"""Stage 2: acquire one authorized public YouTube video and available captions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlparse
import uuid


class AcquisitionError(Exception):
    pass


def canonical_url(value):
    p = urlparse(value)
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('HTTPS YouTube 영상 URL을 입력하세요.')
    host = (p.hostname or '').lower()
    if host == 'youtu.be':
        video_id = p.path.strip('/')
    elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
        if p.path == '/watch':
            video_id = parse_qs(p.query).get('v', [''])[0]
        else:
            match = re.fullmatch(r'/(?:shorts|embed|live)/([^/]+)/?', p.path)
            video_id = match.group(1) if match else ''
    else:
        video_id = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('유효한 단일 YouTube 영상 URL이 아닙니다.')
    return 'https://www.youtube.com/watch?v=' + video_id


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def classify_error(message):
    lower = message.lower()
    if any(t in lower for t in ('private video', 'sign in', 'members-only', 'not available in your country', 'age-restricted', 'login required', 'video unavailable')):
        return 'ACCESS_RESTRICTED', '접근 제한 영상입니다. 우회하지 않습니다.'
    if any(t in lower for t in ('403', 'proxy', 'network', 'connection', 'timed out', 'resolve')):
        return 'NETWORK_ERROR', '네트워크·환경 정책 또는 원격 서버 차단을 확인하세요. 우회하지 않습니다.'
    return 'DOWNLOAD_ERROR', 'yt-dlp 처리 실패입니다. 로컬 로그를 확인하세요.'


def invoke(args, folder, timeout):
    command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
               '--no-progress', '--socket-timeout', '20', '--retries', '1',
               '--fragment-retries', '1', '--extractor-retries', '1',
               '--js-runtimes', 'node'] + args
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AcquisitionError('timed out: 작업 시간 제한 초과') from exc
    with (folder / 'processing.log').open('a', encoding='utf-8') as log:
        log.write(result.stderr + '\n')
    if result.returncode:
        raise AcquisitionError(result.stderr[-6000:])
    return result.stdout


def acquire(url, output, languages, timeout=3600):
    url = canonical_url(url)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg와 ffprobe가 필요합니다.')
    folder = output.resolve() / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    result = {'status': 'running', 'source_url': url, 'started_at': datetime.now(timezone.utc).isoformat(), 'files': []}
    write_json(folder / 'result.json', result)
    try:
        info = json.loads(invoke(['--dump-single-json', '--skip-download', url], folder, timeout))
        if info.get('_type', 'video') != 'video' or not info.get('id'):
            raise AcquisitionError('단일 영상 메타데이터가 아닙니다.')
        if info.get('availability') not in (None, 'public', 'unlisted'):
            raise AcquisitionError('private video or login required')
        if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
            raise AcquisitionError('진행 중 또는 예정된 라이브 영상은 지원하지 않습니다.')
        keys = ('id', 'title', 'duration', 'webpage_url', 'channel', 'channel_id', 'uploader', 'upload_date', 'description', 'license', 'availability', 'language')
        metadata = {key: info.get(key) for key in keys}
        metadata['source_url'] = url
        metadata['subtitle_languages'] = list((info.get('subtitles') or {}).keys())
        metadata['automatic_caption_languages'] = list((info.get('automatic_captions') or {}).keys())
        write_json(folder / 'metadata.json', metadata)
        selected = []
        for lang in languages:
            if lang in (info.get('subtitles') or {}):
                selected.append({'language': lang, 'source': 'manual'})
            elif lang in (info.get('automatic_captions') or {}):
                selected.append({'language': lang, 'source': 'automatic'})
        # No cookie, proxy override, paid service, or access-bypass options.
        args = ['--format', 'bv*+ba/b', '--merge-output-format', 'mkv',
                '--output', str(folder / 'video.%(ext)s')]
        if selected:
            args += ['--write-subs', '--write-auto-subs', '--sub-langs', ','.join(s['language'] for s in selected), '--sub-format', 'vtt']
        invoke(args + [url], folder, timeout)
        media = [p for p in folder.glob('video.*') if p.suffix in {'.mp4', '.mkv', '.webm', '.mov', '.flv', '.3gp'} and p.stat().st_size]
        if len(media) != 1:
            raise AcquisitionError('다운로드 완료 영상 파일을 확인할 수 없습니다.')
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(media[0])], capture_output=True, text=True, timeout=30)
        if probe.returncode:
            raise AcquisitionError('다운로드 영상 ffprobe 검증 실패')
        probed = json.loads(probe.stdout)
        if not any(s.get('codec_type') == 'video' for s in probed.get('streams', [])):
            raise AcquisitionError('영상 스트림이 없습니다.')
        write_json(folder / 'media-probe.json', probed)
        captions = []
        for sub in selected:
            path = folder / ('video.' + sub['language'] + '.vtt')
            if path.exists() and path.stat().st_size:
                captions.append({**sub, 'file': path.name})
        result.update(status='acquired', captions=captions,
                      transcription_status='captions_available' if captions else 'local_transcription_pending',
                      warnings=[] if captions else ['요청 언어 자막 없음. 로컬 음성 인식은 아직 구현하지 않았습니다.'])
    except (AcquisitionError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        code, message = classify_error(str(exc))
        result.update(status='failed', error_code=code, message=message)
        with (folder / 'processing.log').open('a', encoding='utf-8') as log:
            log.write(str(exc) + '\n')
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    result['files'] = [{'path': p.name, 'bytes': p.stat().st_size} for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'result.json']
    write_json(folder / 'result.json', result)
    return folder, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--output', type=Path, default=Path('downloads'))
    parser.add_argument('--languages', default='ko,en', help='쉼표로 구분한 자막 언어, 기본 ko,en')
    parser.add_argument('--timeout', type=int, default=3600, help='각 yt-dlp 호출 제한 시간(초)')
    args = parser.parse_args()
    languages = args.languages.split(',')
    if args.timeout <= 0 or not all(re.fullmatch(r'[A-Za-z0-9_-]+', s) for s in languages):
        parser.error('시간 제한은 양수, 언어는 ko,en 형태로 지정하세요.')
    try:
        folder, result = acquire(args.url, args.output, languages, args.timeout)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({'directory': str(folder), **result}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'acquired' else 1


if __name__ == '__main__':
    raise SystemExit(main())

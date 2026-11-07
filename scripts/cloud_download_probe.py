"""Download one authorized video on a normal GitHub runner; verify actual media.

Only a numeric verification report is logged. Raw media stay local.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from urllib.parse import urlparse, parse_qs


def canonical_url(url):
    p=urlparse(url)
    if p.scheme != 'https' or p.username or p.password or p.port:
        raise ValueError('HTTPS YouTube URL required')
    if p.hostname == 'youtu.be':
        video_id=p.path.strip('/')
    elif p.hostname in {'youtube.com','www.youtube.com','m.youtube.com'}:
        video_id=parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else p.path.strip('/').split('/')[-1] if p.path.startswith(('/shorts/','/live/')) else ''
    else:
        video_id=''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):
        raise ValueError('A single valid YouTube video URL is required')
    return 'https://www.youtube.com/watch?v='+video_id


def redact(text):
    return re.sub(r'https?://[^\s\x27\x22<>]+', '[URL redacted]',text)


@contextmanager
def cookie_file(enabled):
    """Consume a step-scoped secret without forwarding it to child processes."""
    content=os.environ.pop('YOUTUBE_COOKIES','')
    if not enabled:
        yield None
        return
    if not content or len(content.encode('utf-8'))>48*1024:
        raise ValueError('YOUTUBE_COOKIES must be present and at most 48 KiB')
    lines=content.replace('\r\n','\n').splitlines()
    if not lines or lines[0] not in ('# Netscape HTTP Cookie File','# HTTP Cookie File'):
        raise ValueError('YOUTUBE_COOKIES must be a Netscape cookie file')
    count=0
    for line in lines[1:]:
        if line.startswith('#HttpOnly_'):
            line=line[len('#HttpOnly_'):]
        elif not line or line.startswith('#'):
            continue
        parts=line.split('\t')
        if (len(parts)!=7 or parts[0].lstrip('.') not in {'youtube.com','www.youtube.com','m.youtube.com'}
                or parts[1] not in {'TRUE','FALSE'} or parts[3] not in {'TRUE','FALSE'}
                or not parts[4].isdigit() or not parts[5]
                or any(ord(c)<32 and c!='\t' for c in line)):
            raise ValueError('Invalid cookie row or non-YouTube domain; export YouTube cookies only')
        count+=1
    if not count:
        raise ValueError('Cookie file contains no usable YouTube cookies')
    with tempfile.TemporaryDirectory(prefix='youtube-auth-',dir=os.environ.get('RUNNER_TEMP')) as tmp:
        path=Path(tmp)/'cookies.txt'
        # mkstemp grants 0600 atomically; the parent directory is 0700.
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write('\n'.join(lines)+'\n')
        content=None
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


def check_download(media, info):
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)],text=True,timeout=60))
    video=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),None)
    if not video or not media.stat().st_size:
        raise ValueError('No actual video stream downloaded')
    duration=float(video.get('duration') or data['format']['duration'])
    declared=info.get('duration')
    if duration<=0 or declared and abs(duration-float(declared))>max(2,float(declared)*.01):
        raise ValueError('Downloaded duration does not match original metadata')
    digest=hashlib.sha256()
    with media.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            digest.update(block)
    return {'bytes':media.stat().st_size,'sha256':digest.hexdigest(),'actual_duration':duration,
            'video_codec':video.get('codec_name'),'audio_present':any(s.get('codec_type')=='audio' for s in data['streams'])}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',default='artifacts/download-probe')
    parser.add_argument('--source-dir',default='downloads/cloud-probe')
    parser.add_argument('--use-cookies',action='store_true',help='Read YOUTUBE_COOKIES from the environment only')
    args=parser.parse_args(argv)
    out=Path(args.output)
    source=Path(args.source_dir)
    out.mkdir(parents=True,exist_ok=True)
    result={'status':'failed','media_uploaded':False,'authentication_requested':args.use_cookies}
    try:
        url=canonical_url(args.url)
        result['source_url']=url
        if source.exists() and any(source.iterdir()):
            raise ValueError('Source directory must be empty')
        source.mkdir(parents=True,exist_ok=True)
        command=[sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--no-progress',
            '--abort-on-error','--js-runtimes','node','--retries','0','--extractor-retries','0',
            '--fragment-retries','0','--socket-timeout','20',
            '--match-filters','!is_live & duration <= 3600', '--max-filesize','2G',
            '-f','bv*[height<=720]+ba/b[height<=720]', '--merge-output-format','mkv',
            '--quiet','--no-simulate','--print','after_move:{"id":%(id)j,"duration":%(duration)j}',
            '--write-subs','--write-auto-subs','--sub-langs','ko,en',
            '--sub-format','vtt','--paths',str(source),'-o','video.%(ext)s',url]
        result['stage']='authentication_setup'
        with cookie_file(args.use_cookies) as cookies:
            if cookies:
                command[3:3]=['--cookies',str(cookies)]
            # Authenticated stderr is never captured: errors can contain credential values.
            result['stage']='download'
            process=subprocess.run(command,stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL if args.use_cookies else subprocess.PIPE,
                                   text=True,timeout=660)
        safe_log='Authenticated mode: raw downloader output suppressed.\n' if args.use_cookies else redact(process.stderr or '')[-50000:]
        (out/'download.log').write_text(safe_log,encoding='utf-8')
        result['yt_dlp_exit_code']=process.returncode
        if process.returncode:
            if not args.use_cookies:
                print(redact(process.stderr or '')[-10000:])
            raise ValueError('yt-dlp failed; see redacted download.log. Access restrictions are not bypassed.')
        result['stage']='verification'
        files=[f for f in source.iterdir() if f.suffix in {'.mkv','.mp4','.webm'} and not re.search(r'\.f\d+\.',f.name)]
        if len(files)!=1:
            raise ValueError('Complete video file not found (filtered/oversized/missing)')
        info=json.loads(process.stdout.strip().splitlines()[-1])
        result['media']=check_download(files[0],info)
        result['metadata']={'id':url.rsplit('=',1)[-1],'duration':float(info['duration'])}
        result['subtitle_files']=[p.name for p in source.glob('*.vtt')]
        result['status']='download_verified'
    except Exception as exc:
        # Never serialize exception text, TimeoutExpired output, or metadata in auth mode.
        result['error']='Authenticated download failed. Check secret format/expiry and normal account access; raw diagnostics are suppressed.' if args.use_cookies else redact(str(exc))[:2000]
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='download_verified' else 1


if __name__=='__main__':
    raise SystemExit(main())

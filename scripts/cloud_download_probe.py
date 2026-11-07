"""Download one authorized video on a normal GitHub runner; verify actual media.

Only small reports/captions are exported. Raw media and yt-dlp metadata stay local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
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
    args=parser.parse_args(argv)
    out=Path(args.output)
    source=Path(args.source_dir)
    out.mkdir(parents=True,exist_ok=True)
    result={'status':'failed','media_uploaded':False}
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
            '--write-info-json','--write-subs','--write-auto-subs','--sub-langs','ko,en',
            '--sub-format','vtt','--paths',str(source),'-o','video.%(ext)s',url]
        process=subprocess.run(command,capture_output=True,text=True,timeout=660)
        (out/'download.log').write_text(redact(process.stdout+'\n'+process.stderr)[-50000:],encoding='utf-8')
        result['yt_dlp_exit_code']=process.returncode
        if process.returncode:
            print(redact(process.stdout+'\n'+process.stderr)[-10000:])
            raise ValueError('yt-dlp failed; see redacted download.log. Access restrictions are not bypassed.')
        files=[f for f in source.iterdir() if f.suffix in {'.mkv','.mp4','.webm'} and not re.search(r'\.f\d+\.',f.name)]
        if len(files)!=1:
            raise ValueError('Complete video file not found (filtered/oversized/missing)')
        info=json.loads((source/'video.info.json').read_text())
        result['media']=check_download(files[0],info)
        result['metadata']={k:info.get(k) for k in ('id','title','duration','uploader','upload_date','license')}
        result['subtitle_files']=[p.name for p in source.glob('*.vtt')]
        result['status']='download_verified'
    except Exception as exc:
        result['error']=redact(str(exc))[:2000]
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='download_verified' else 1


if __name__=='__main__':
    raise SystemExit(main())

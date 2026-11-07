import importlib.util
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('cloud_probe',Path(__file__).resolve().parents[1]/'scripts/cloud_download_probe.py')
probe=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class CloudProbeTests(unittest.TestCase):
    COOKIE='# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2000000000\tTEST_SESSION\tFAKE_TEST_VALUE_NOT_A_REAL_COOKIE\n'

    def run_cookie_case(self, behavior):
        with tempfile.TemporaryDirectory() as tmp:
            seen=[]
            def download(command,**kwargs):
                cookie=Path(command[command.index('--cookies')+1])
                seen.append(cookie)
                self.assertTrue(cookie.exists())
                self.assertEqual(cookie.stat().st_mode & 0o777,0o600)
                self.assertEqual(cookie.parent.stat().st_mode & 0o777,0o700)
                self.assertNotIn('YOUTUBE_COOKIES',os.environ)
                self.assertNotIn('FAKE_TEST_VALUE',str(command))
                self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
                return behavior(command,kwargs,tmp)
            stdout=io.StringIO()
            with patch.dict(os.environ,{'YOUTUBE_COOKIES':self.COOKIE,'RUNNER_TEMP':tmp}), patch.object(probe.subprocess,'run',side_effect=download), contextlib.redirect_stdout(stdout):
                status=probe.main(['--url','https://youtu.be/Z0aXJeC4HiE','--output',tmp+'/report','--source-dir',tmp+'/media','--use-cookies'])
            self.assertTrue(seen)
            self.assertFalse(seen[0].exists())
            self.assertFalse(seen[0].parent.exists())
            exported=stdout.getvalue()+''.join(p.read_text() for p in Path(tmp+'/report').rglob('*') if p.is_file())
            self.assertNotIn('FAKE_TEST_VALUE_NOT_A_REAL_COOKIE',exported)
            self.assertNotIn('TEST_SESSION',exported)
            self.assertNotIn(str(seen[0]),exported)
            return status

    def test_authenticated_failure_does_not_export_raw_output(self):
        def fail(command,kwargs,tmp):
            return subprocess.CompletedProcess(command,1,self.COOKIE,self.COOKIE)
        self.assertEqual(self.run_cookie_case(fail),1)

    def test_timeout_exception_cannot_export_cookies(self):
        def timeout(command,kwargs,tmp):
            raise subprocess.TimeoutExpired(command,660,output=self.COOKIE,stderr=self.COOKIE)
        self.assertEqual(self.run_cookie_case(timeout),1)

    def test_cookie_removed_on_success(self):
        def success(command,kwargs,tmp):
            Path(tmp+'/media/video.mp4').write_bytes(b'fake media, media verification tested separately')
            return subprocess.CompletedProcess(command,0,'{"id":"Z0aXJeC4HiE","duration":2}\n',None)
        with patch.object(probe,'check_download',return_value={'actual_duration':2,'bytes':100}):
            self.assertEqual(self.run_cookie_case(success),0)

    def test_missing_or_invalid_secret_stops_before_download(self):
        for value in ('', 'bad file', self.COOKIE.replace('.youtube.com','.example.com'),self.COOKIE+'x'*50000):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'YOUTUBE_COOKIES':value}), patch.object(probe.subprocess,'run') as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(['--url','https://youtu.be/Z0aXJeC4HiE','--output',tmp+'/report','--source-dir',tmp+'/media','--use-cookies']),1)
                run.assert_not_called()

    def test_cookie_secret_is_discarded_when_opted_out(self):
        with patch.dict(os.environ,{'YOUTUBE_COOKIES':self.COOKIE}):
            with probe.cookie_file(False) as value:
                self.assertIsNone(value)
                self.assertNotIn('YOUTUBE_COOKIES',os.environ)
    def test_url_and_log_safety(self):
        self.assertEqual(probe.canonical_url('https://youtu.be/Z0aXJeC4HiE?si=test'),
                         'https://www.youtube.com/watch?v=Z0aXJeC4HiE')
        for url in ('https://evil.com/video','https://www.youtube.com/playlist?list=x','https://youtu.be/bad','http://youtu.be/Z0aXJeC4HiE'):
            with self.assertRaises(ValueError):
                probe.canonical_url(url)
        self.assertNotIn('token=secret',probe.redact('request https://example.org/?token=secret failed'))

    def test_filtered_video_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=['--url','https://youtu.be/Z0aXJeC4HiE','--output',tmp+'/report','--source-dir',tmp+'/media']
            with patch.object(probe.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'filtered','')):
                self.assertEqual(probe.main(args),1)
            self.assertEqual(json.loads(Path(tmp+'/report/result.json').read_text())['status'],'failed')

    def test_actual_file_check_and_short_download_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'video.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=160x120:r=4:d=2',
                            '-c:v','libx264','-y',str(video)],check=True)
            result=probe.check_download(video,{'duration':2})
            self.assertGreater(result['bytes'],0)
            self.assertEqual(result['actual_duration'],2)
            with self.assertRaises(ValueError):
                probe.check_download(video,{'duration':100})

    def test_workflow_injection_boundary(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/youtube-download-probe.yml').read_text()
        self.assertIn('VIDEO_URL: ${{ inputs.url }}',text)
        self.assertNotIn('run: python scripts/cloud_download_probe.py --url "${{',text)
        self.assertIn('if: github.event.repository.private == false',text)
        self.assertNotIn('upload-artifact@',text)
        self.assertIn('YOUTUBE_COOKIES: ${{ inputs.use_cookies && secrets.YOUTUBE_COOKIES',text)
        self.assertIn('Remove temporary authentication files',text)


if __name__=='__main__':
    unittest.main()

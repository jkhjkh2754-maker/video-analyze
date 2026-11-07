import importlib.util
import json
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


if __name__=='__main__':
    unittest.main()

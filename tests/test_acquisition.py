import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import analyzer


class AcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.sample = Path(cls.temp.name) / 'sample.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=2', '-t', '1', '-c:v', 'libx264', str(cls.sample)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_url_validation(self):
        for url in ['https://youtu.be/abcdefghijk', 'https://www.youtube.com/watch?v=abcdefghijk&list=foo', 'https://youtube.com/shorts/abcdefghijk']:
            self.assertEqual(analyzer.canonical_url(url), 'https://www.youtube.com/watch?v=abcdefghijk')
        for url in ['http://youtube.com/watch?v=abcdefghijk', 'https://youtube.com.evil/watch?v=abcdefghijk', 'file:///tmp/video', 'https://youtube.com/playlist?list=a', 'https://youtube.com/watch?v=bad']:
            with self.assertRaises(ValueError):
                analyzer.canonical_url(url)

    def run_case(self, info=None, error=None, video=True, caption=True):
        def fake(args, folder, timeout):
            if error:
                raise analyzer.AcquisitionError(error)
            if '--dump-single-json' in args:
                return json.dumps(info)
            if video:
                shutil.copyfile(self.sample, folder / 'video.mp4')
            if caption and '--write-subs' in args:
                (folder / 'video.ko.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:01.000\n시험\n')
            return ''
        with tempfile.TemporaryDirectory() as output, patch('analyzer.invoke', side_effect=fake) as mock:
            folder, result = analyzer.acquire('https://youtu.be/abcdefghijk', Path(output), ['ko', 'en'])
            self.assertEqual(json.loads((folder / 'result.json').read_text()), result)
            metadata = json.loads((folder / 'metadata.json').read_text()) if (folder / 'metadata.json').exists() else None
            return result, mock.call_count, metadata

    def test_manual_captions_and_real_probe(self):
        result, calls, meta = self.run_case({'id':'abcdefghijk', 'title':'시험', 'duration':1, 'subtitles':{'ko':[]}, 'automatic_captions':{'ko':[]}, 'url':'https://secret-expiring-url'})
        self.assertEqual(result['status'], 'acquired')
        self.assertEqual(result['captions'][0]['source'], 'manual')
        self.assertNotIn('url', meta)
        self.assertEqual(calls, 2)

    def test_automatic_captions(self):
        result, _, _ = self.run_case({'id':'abcdefghijk', 'automatic_captions':{'ko':[]}})
        self.assertEqual(result['captions'][0]['source'], 'automatic')

    def test_no_captions_explicitly_pending(self):
        result, _, _ = self.run_case({'id':'abcdefghijk'})
        self.assertEqual(result['status'], 'acquired')
        self.assertEqual(result['transcription_status'], 'local_transcription_pending')

    def test_missing_video_cannot_succeed(self):
        result, _, _ = self.run_case({'id':'abcdefghijk'}, video=False)
        self.assertEqual(result['status'], 'failed')

    def test_private_stops_before_download(self):
        result, calls, _ = self.run_case({'id':'abcdefghijk', 'availability':'private'})
        self.assertEqual(result['error_code'], 'ACCESS_RESTRICTED')
        self.assertEqual(calls, 1)

    def test_network_failure_is_recorded(self):
        result, _, _ = self.run_case(error='CONNECT tunnel failed 403')
        self.assertEqual(result['error_code'], 'NETWORK_ERROR')
        self.assertEqual(result['status'], 'failed')

    def test_live_stops_before_download(self):
        result, calls, _ = self.run_case({'id':'abcdefghijk','is_live':True})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()

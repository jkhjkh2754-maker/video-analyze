import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from frames import extract_frames


class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.scenes = cls.root / 'scenes.mkv'
        # Four 4-second scenes: repeated red tests global dedup after a cut.
        cmd = ['ffmpeg', '-v', 'error']
        for color in ['red', 'white', 'red', 'blue']:
            cmd += ['-f', 'lavfi', '-i', f'color={color}:s=160x90:r=2:d=4']
        cmd += ['-filter_complex', '[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0',
                '-c:v', 'ffv1', str(cls.scenes)]
        subprocess.run(cmd, check=True)
        cls.motion = cls.root / 'motion.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=s=160x90:r=2:d=25', '-c:v', 'ffv1', str(cls.motion)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_extract(self, source=None, **kwargs):
        folder, result = extract_frames(source or self.scenes, self.root / 'out', **kwargs)
        self.assertEqual(result['status'], 'extracted', result)
        self.assertEqual(json.loads((folder / 'frames.json').read_text()), result)
        self.assertEqual(len(list(folder.glob('*.png'))), result['image_count'])
        for frame in result['frames']:
            self.assertEqual((folder / frame['file']).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        return result

    def test_scene_detection_and_global_duplicates(self):
        result = self.run_extract(interval=100, scene_threshold=0.1)
        self.assertEqual([f['timestamp_seconds'] for f in result['frames']], [0, 4, 12])
        self.assertGreaterEqual(result['duplicates_removed'], 1)
        self.assertEqual(result['frames'][1]['timestamp'], '00:00:04.000')

    def test_default_ten_second_interval(self):
        result = self.run_extract(self.motion, scene_threshold=1, similarity_threshold=0)
        self.assertEqual([f['timestamp_seconds'] for f in result['frames']], [0, 10, 20])

    def test_maximum(self):
        result = self.run_extract(interval=1, scene_threshold=0.1, max_images=2)
        self.assertEqual(result['image_count'], 2)
        self.assertTrue(result['limit_reached'])

    def test_similar_images_removed(self):
        result = self.run_extract(self.motion, interval=1, scene_threshold=1, similarity_threshold=1)
        self.assertEqual(result['image_count'], 1)
        self.assertEqual(result['duplicates_removed'], 24)

    def test_invalid_options(self):
        for options in [{'interval': 0}, {'interval': float('nan')}, {'max_images': 0},
                        {'scene_threshold': 1.1}, {'similarity_threshold': -1}]:
            with self.assertRaises(ValueError):
                extract_frames(self.scenes, self.root / 'out', **options)

    def test_corrupt_input_records_failure(self):
        bad = self.root / 'bad.mp4'
        bad.write_bytes(b'not a video')
        folder, result = extract_frames(bad, self.root / 'out')
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((folder / 'frames.json').exists())


if __name__ == '__main__':
    unittest.main()

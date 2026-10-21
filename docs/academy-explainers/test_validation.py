import json
from pathlib import Path
import tempfile
import unittest
from validation import atomic_json, fingerprints, require_approved, timing_errors


class ValidationTest(unittest.TestCase):
    def test_collapsed_words_fail(self):
        asr = {'segments': [{'words': [{'start': 0, 'end': 0, 'word': 'hello'}] * 750}]}
        self.assertTrue(timing_errors(asr, 320))

    def test_missing_caption_words_fail(self):
        asr = {'segments': [{'text': 'hello world', 'words': [{'start': 1, 'end': 2, 'word': 'hello'}]}]}
        self.assertTrue(timing_errors(asr, 320))

    def test_invalid_word_ranges_fail(self):
        for start, end in [(2, 1), (-1, 2), (0, float('nan')), (0, 400)]:
            self.assertTrue(timing_errors({'segments': [{'words': [{'start': start, 'end': end}]}]}, 320))

    def test_receipt_rejects_changed_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            asr = {'segments': [{'text': 'hello', 'words': [{'start': 1, 'end': 2, 'word': 'hello'}]}]}
            atomic_json(directory / 'asr.json', asr)
            atomic_json(directory / 'lesson.json', {'duration': 320})
            (directory / 'narration.wav').write_bytes(b'original')
            atomic_json(directory / 'voice-check.json', {'pass': True, 'sha256': fingerprints(directory)})
            require_approved(directory)
            atomic_json(directory / 'asr.json', {'segments': []})
            with self.assertRaisesRegex(AssertionError, 'stale'):
                require_approved(directory)

    def test_resumed_checkpoint_preserves_unvisited(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = {'00.wav': {'text': 'first'}, '01.wav': {'text': 'second'}}
            checkpoint['00.wav'] = {'text': 'first'}
            path = Path(temporary) / 'timing.json'
            atomic_json(path, list(checkpoint.values()))
            self.assertEqual(len(json.loads(path.read_text())), 2)


if __name__ == '__main__':
    unittest.main()

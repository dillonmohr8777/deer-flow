import json
from pathlib import Path
import tempfile
import unittest
from validation import atomic_json, fingerprints, require_approved, timing_errors
from contract import accepted_sources, identity, voice_directory, ensure_generation, duration_ok, sha, SETTINGS
from synthesize import chunks
from transcribe import critical_differences, normalize, provider_transcript


class ValidationTest(unittest.TestCase):
    def fixture(self, root):
        (root / 'scripts').mkdir()
        source = root / 'scripts/00-platform-tour.json'
        atomic_json(source, {'title': 'Tour', 'chapters': [{'title': 'A', 'narration': 'Do not send 5 drafts.'}]})
        (root / 'ref.wav').write_bytes(b'authorized reference')
        atomic_json(root / 'SCRIPT-ACCEPTED.json', {'accepted': True, 'course': 'momentum-work', 'reference_sha256': sha(root / 'ref.wav'), 'lessons': [{'stem': source.stem, 'sha256': sha(source)}]})
        return source

    def test_caption_complete_valid(self):
        self.assertFalse(timing_errors({'segments': [{'text': 'hello world', 'words': [{'start': 1, 'end': 2, 'word': 'hello'}, {'start': 2, 'end': 3, 'word': 'world'}]}]}, 320))

    def test_missing_caption_words_fail(self):
        asr = {'segments': [{'text': 'hello world', 'words': [{'start': 1, 'end': 2, 'word': 'hello'}]}]}
        self.assertIn('Timed words do not cover accepted segment text', timing_errors(asr, 320))

    def test_collapsed_words_fail(self):
        asr = {'segments': [{'text': 'hello world', 'words': [{'start': 320, 'end': 320, 'word': word} for word in ('hello', 'world')]}]}
        self.assertIn('More than ten percent of word times collapsed', timing_errors(asr, 320))

    def test_invalid_word_ranges_fail(self):
        for start, end in [(2, 1), (-1, 2), (0, float('nan')), (0, 600)]:
            self.assertTrue(timing_errors({'segments': [{'text': 'x', 'words': [{'word': 'x', 'start': start, 'end': end}]}]}, 520))

    def test_missing_and_changed_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(AssertionError, 'Awaiting'):
                accepted_sources(root)
            source = self.fixture(root)
            self.assertEqual(accepted_sources(root)[0], [source])
            source.write_text('{}')
            with self.assertRaisesRegex(AssertionError, 'Unaccepted'):
                accepted_sources(root)

    def test_hold_blocks_generation_before_model_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.fixture(root)
            atomic_json(root / 'HOLD.json', {'reason': 'scope changed'})
            with self.assertRaisesRegex(AssertionError, 'held'):
                ensure_generation(root, source, root / 'ref.wav')

    def test_changed_ref_source_or_settings_get_new_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.fixture(root); ref = root / 'ref.wav'
            original = voice_directory(root, source, ref)[0]
            ref.write_bytes(b'different reference')
            self.assertNotEqual(original, voice_directory(root, source, ref)[0])
            self.assertNotEqual(voice_directory(root, source, ref)[0], voice_directory(root, source, ref, dict(SETTINGS, seed=11))[0])
            before = voice_directory(root, source, ref)[0]
            source.write_text('{}')
            self.assertNotEqual(before, voice_directory(root, source, ref)[0])

    def test_unaccepted_reference_rejected_before_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.fixture(root)
            (root / 'ref.wav').write_bytes(b'changed reference')
            with self.assertRaisesRegex(AssertionError, 'Unaccepted voice reference'):
                ensure_generation(root, source, root / 'ref.wav')

    def test_receipt_and_pending_marker_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = self.fixture(root)
            directory = ensure_generation(root, source, root / 'ref.wav')
            atomic_json(directory / 'asr.json', {'segments': [{'text': 'hello', 'words': [{'start': 1, 'end': 2, 'word': 'hello'}]}]})
            atomic_json(directory / 'lesson.json', {'duration': 520, 'course_stem': source.stem})
            atomic_json(directory / 'timing.json', [])
            (directory / 'narration.wav').write_bytes(b'original')
            atomic_json(directory / 'voice-check.json', {'pass': True, 'sha256': fingerprints(directory)})
            require_approved(directory)
            atomic_json(directory / 'ASR-RUNNING.json', {})
            with self.assertRaisesRegex(AssertionError, 'incomplete'):
                require_approved(directory)
            (directory / 'ASR-RUNNING.json').replace(directory / 'ASR-LAST-RUN.json')
            atomic_json(directory / 'timing.json', [{'text': 'changed'}])
            with self.assertRaisesRegex(AssertionError, 'stale'):
                require_approved(directory)

    def test_provider_words_preserved_and_audio_hash_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); audio = root / 'narration.wav'; audio.write_bytes(b'fixture')
            response = root / 'provider.json'
            words = [{'word': 'do', 'start': 0, 'end': .2}, {'word': 'not', 'start': .2, 'end': .5}]
            atomic_json(response, {'successful': True, 'data': {'text': 'do not', 'duration': 1, 'words': words}})
            original, parsed = provider_transcript(response, audio, sha(audio))
            self.assertEqual(parsed['segments'][0]['words'], words)
            self.assertFalse(timing_errors(parsed, 1))
            with self.assertRaisesRegex(AssertionError, 'input audio hash'):
                provider_transcript(response, audio, 'wrong')

    def test_protected_words_do_not_hide_under_coverage_tolerance(self):
        for token in ['not', 'no', 'never', '5', 'before', 'without']:
            self.assertTrue(critical_differences([{'expected': token, 'heard': ''}]))
        self.assertFalse(critical_differences([{'expected': 'balanced', 'heard': 'balance'}]))
        self.assertEqual(normalize("Don't send five"), normalize('Do not send 5'))

    def test_variable_duration_and_chunks(self):
        for duration, expected in [(479, False), (480, True), (599.9, True), (600, False)]:
            self.assertEqual(duration_ok({'course_stem': '00-platform-tour', 'duration': duration}), expected)
        self.assertFalse(duration_ok({'course_stem': '01-ai-at-work', 'duration': 480}))
        self.assertEqual(chunks('First sentence. Second sentence.'), ['First sentence.', 'Second sentence.'])
        self.assertTrue(all(len(part.split()) <= 30 for part in chunks('word ' * 75)))

class BuildContractTest(unittest.TestCase):
    def test_work_build_variable_chapters_and_default_caption_track(self):
        from build import build
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            original = Path(__file__).parent / 'work-visuals.json'
            board_count = len(json.loads(original.read_text())['00-platform-tour'])
            chapters = [{'title': f'Chapter {i}', 'narration': 'hello', 'start': i*520/board_count,
                         'duration': 520/board_count} for i in range(board_count)]
            source = root / 'scripts/00-platform-tour.json'
            atomic_json(source, {'title': 'Test fixture tour', 'chapters': chapters})
            (root / 'ref.wav').write_bytes(b'fixture reference')
            atomic_json(root / 'SCRIPT-ACCEPTED.json', {'accepted': True, 'course': 'momentum-work', 'reference_sha256': sha(root / 'ref.wav'), 'course_total': 16,
                        'lessons': [{'stem': source.stem, 'sha256': sha(source)}]})
            directory = ensure_generation(root, source, root / 'ref.wav')
            lesson = json.loads(source.read_text()); lesson.update(duration=520, course='momentum-work', course_stem=source.stem)
            atomic_json(directory / 'lesson.json', lesson)
            atomic_json(directory / 'asr.json', {'segments': [{'text': 'hello', 'words': [{'word': 'hello', 'start': 1, 'end': 2}]}]})
            atomic_json(directory / 'timing.json', [])
            (directory / 'narration.wav').write_bytes(b'fixture audio bytes - not real media')
            atomic_json(directory / 'voice-check.json', {'pass': True, 'sha256': fingerprints(directory)})
            assets = root / 'assets'; assets.mkdir()
            for name in ['momo-mark.svg', 'archivo-black.ttf', 'nunito-sans.ttf', 'gsap.min.js', 'experience.png']:
                (assets / name).write_bytes(b'fixture')
            build(directory / 'lesson.json', root / 'projects', assets)
            project = root / 'projects/00-platform-tour'
            document = (project / 'index.html').read_text()
            self.assertIn('LESSON 1 / 16', document)
            self.assertNotIn('class="clip caption"', document)
            self.assertEqual(len(list((project / 'compositions').glob('*.html'))), 12)
            self.assertIn('CHAPTER 12 / 12', (project / 'compositions/chapter-11.html').read_text())
            self.assertIn('WEBVTT', (project / 'captions.vtt').read_text())
            atomic_json(root / 'HOLD.json', {'reason': 'fixture hold'})
            with self.assertRaisesRegex(AssertionError, 'held'):
                build(directory / 'lesson.json', root / 'projects', assets)


if __name__ == '__main__':
    unittest.main()

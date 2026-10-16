"""Offline regression for output collisions, not an AI-editing acceptance test.

Run from the repository root with runtime dependencies and ffmpeg/ffprobe installed:
    PYTHONPATH=src:. python -m unittest discover -s tests -v
"""
import asyncio
import contextlib
import io
import json
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_storyline.config import load_settings
from open_storyline.nodes.core_nodes.speech_rough_cut import SpeechRoughCutNode
from open_storyline.nodes.node_state import NodeState
from open_storyline.nodes.node_summary import NodeSummary

ROOT = Path(__file__).resolve().parents[1]


class FixtureResponses:
    """Deterministic decisions isolate file naming from model quality and cost."""
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        return json.dumps({'res': next(self.rows)})


def no_network(*args, **kwargs):
    raise AssertionError('This regression must never call a network service')


class RoughCutOutputsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing binaries must fail visibly, not be reported as a passing skip.
        for name in ('ffmpeg', 'ffprobe'):
            if not shutil.which(name):
                raise RuntimeError(f'{name} is required for real file regression')
        cls.workspace = tempfile.TemporaryDirectory()
        cls.base = Path(cls.workspace.name)
        cls.sources = []
        for color in ('red', 'blue'):
            source = cls.base / f'{color}.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            f'color=c={color}:s=64x64:r=15:d=4',
                            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                            '-y', str(source)], check=True)
            cls.sources.append(source)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def run_case(self, decisions):
        cfg = load_settings(ROOT / 'config.toml')
        cfg.local_mcp_server.server_cache_dir = str(self.base / self.id())
        llm = FixtureResponses(decisions)
        inputs = []
        for i in range(len(decisions)):
            inputs.append({'path': str(self.sources[i % 2]), 'fps': 15,
                           'source_ref': {'media_id': f'media_{i}', 'width': 64, 'height': 64},
                           'asr_text': 'Fixture sentence.',
                           'asr_sentence_info': [{'text': 'Fixture sentence.', 'start': 0, 'end': 3500}]})
        state = NodeState(session_id='offline', artifact_id='cut', lang='zh',
                          node_summary=NodeSummary(auto_console=False), llm=llm, mcp_ctx=None)
        with patch.object(socket.socket, 'connect', no_network), \
             patch.object(socket.socket, 'connect_ex', no_network), \
             patch.object(socket, 'getaddrinfo', no_network), \
             contextlib.redirect_stdout(io.StringIO()):
            result = asyncio.run(SpeechRoughCutNode(cfg).process(state, {
                'asr': {'asr_infos': inputs}, 'speech_rough_cut': {},
                'gap_threshold': 400, 'user_request': 'Offline fixture only.'}))
        clips = result['clips']
        expected_count = sum(len(row) for row in decisions)
        self.assertEqual(llm.calls, len(decisions))
        self.assertEqual(len(clips), expected_count)
        self.assertEqual(len({c['path'] for c in clips}), expected_count)
        self.assertEqual(len({c['clip_id'] for c in clips}), expected_count)
        self.assertEqual(len(result['rough_cut_jsons']), len(decisions))
        for clip in clips:
            duration = float(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=nw=1:nk=1', clip['path']], text=True))
            self.assertAlmostEqual(duration, clip['source_ref']['duration'] / 1000, delta=0.2)
        return clips

    def test_multiple_sources_do_not_overwrite_files_or_repeat_ids(self):
        self.run_case([
            [{'text': 'one', 'start': 100, 'end': 900},
             {'text': 'two', 'start': 1800, 'end': 2900}],
            [],
            [{'text': 'three', 'start': 200, 'end': 1800}],
        ])

    def test_single_source_still_works(self):
        self.run_case([[{'text': 'single', 'start': 200, 'end': 1800}]])

    def test_empty_selection_creates_no_clip(self):
        self.run_case([[], []])


if __name__ == '__main__':
    unittest.main()

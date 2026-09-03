import os
import sys
import uuid
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GEMINI_API_KEY"] = "test_key"
os.environ["WHISPER_MODEL"] = "tiny"

import config
from utils.validators import validate_video_upload, secure_filename, generate_id, ValidationError
from utils.file_utils import safe_remove
from db import db, Meeting


class TestConfig(unittest.TestCase):
    def test_config_loads(self):
        self.assertIsNotNone(config.config.app.PORT)
        self.assertGreater(config.config.audio.SAMPLERATE, 0)
        self.assertIn("int8", config.config.whisper.COMPUTE_TYPE)


class TestValidators(unittest.TestCase):
    def test_secure_filename(self):
        self.assertEqual(secure_filename("my file.mp4"), "my file.mp4")
        self.assertNotIn("..", secure_filename("../../secret.txt"))
        self.assertNotIn("/", secure_filename("../etc/passwd"))

    def test_generate_id(self):
        id1 = generate_id()
        id2 = generate_id()
        self.assertNotEqual(id1, id2)
        self.assertEqual(len(id1), 32)

    def test_validate_video_upload(self):
        from werkzeug.datastructures import FileStorage
        import io
        with self.assertRaises(ValidationError):
            validate_video_upload(None)
        f = FileStorage(stream=io.BytesIO(b"data"), filename="")
        with self.assertRaises(ValidationError):
            validate_video_upload(f)
        f = FileStorage(stream=io.BytesIO(b"x" * 1024), filename="test.mp4")
        validate_video_upload(f)
        f = FileStorage(stream=io.BytesIO(b"x" * 1024), filename="test.exe")
        with self.assertRaises(ValidationError):
            validate_video_upload(f)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.test_db_path = f"data/test_meetings_{uuid.uuid4().hex[:8]}.db"
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        from db import Database
        self.db = Database(self.test_db_path)
        self.db.init_db()

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_create_and_get(self):
        m = Meeting(id="test123", title="Test", transcript="hello", summary="test summary")
        self.db.create_meeting(m)
        retrieved = self.db.get_meeting("test123")
        self.assertEqual(retrieved.title, "Test")
        self.assertEqual(retrieved.transcript, "hello")

    def test_update(self):
        m = Meeting(id="test123", title="Test", transcript="", summary=None)
        self.db.create_meeting(m)
        m.summary = "Updated"
        self.db.update_meeting(m)
        retrieved = self.db.get_meeting("test123")
        self.assertEqual(retrieved.summary, "Updated")

    def test_delete(self):
        m = Meeting(id="test123", title="Test", transcript="", summary=None)
        self.db.create_meeting(m)
        self.assertTrue(self.db.delete_meeting("test123"))
        self.assertIsNone(self.db.get_meeting("test123"))

    def test_list(self):
        for i in range(3):
            self.db.create_meeting(Meeting(id=f"test{i}", title=f"Meeting {i}", transcript="", summary=None))
        meetings, total = self.db.get_meetings()
        self.assertEqual(total, 3)
        self.assertEqual(len(meetings), 3)


class TestFileUtils(unittest.TestCase):
    def test_safe_remove_nonexistent(self):
        safe_remove("/nonexistent/path/that/does/not/exist")

    def test_safe_remove_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        self.assertTrue(os.path.exists(path))
        safe_remove(path)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()

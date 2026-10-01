import os
import tempfile
import unittest
from unittest.mock import patch


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.tmp.name, "api.sqlite3"))
        self.db_patch.start()
        from database import store
        store.init_db()
        from fastapi.testclient import TestClient
        from backend.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_health_and_unknown_run(self):
        self.assertEqual(self.client.get("/health").json()["status"], "healthy")
        self.assertEqual(self.client.get("/research/missing").status_code, 404)

    def test_create_research_and_read_status(self):
        with patch("backend.main._run_research"):
            response = self.client.post("/research", json={"question": "Analyze India's smartphone market"})
        self.assertEqual(response.status_code, 202)
        run_id = response.json()["id"]
        detail = self.client.get(f"/research/{run_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "queued")
        self.assertEqual(self.client.get(f"/research/{run_id}/status").status_code, 200)
        self.assertEqual(self.client.get(f"/research/{run_id}/sources").json()["sources"], [])
        self.assertEqual(self.client.get(f"/research/{run_id}/report").status_code, 404)


if __name__ == "__main__": unittest.main()

"""
Run: python -m unittest discover -s tests -v
Uses the fake AI and a temporary database — no API key or network needed.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "test.sqlite")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["LLM_PROVIDER"] = "fake"

import openpyxl
from fastapi.testclient import TestClient

from config import CATEGORY_SUBCATEGORIES
from modules.classifier.transaction_classifier import classify_transaction, _validate_and_clean
from modules.ingestion.kaspi_parser import parse_kaspi_excel
import app as app_module

LABELLED = json.loads((ROOT / "tests" / "labelled_transactions.json").read_text(encoding="utf-8"))
SAMPLE = str(ROOT / "data" / "sample_kaspi_statement.xlsx")
HEADER = ("Дата", "Контрагент", "Описание операции", "Кредит (приход)", "Дебет (расход)", "Остаток")


def make_xlsx(rows, header=HEADER) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    path = os.path.join(_tmp, f"t{len(os.listdir(_tmp))}.xlsx")
    wb.save(path)
    return path


class ParserTests(unittest.TestCase):
    def test_sample_file(self):
        r = parse_kaspi_excel(SAMPLE)
        self.assertEqual(r["summary"]["valid"], 8)
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual(r["summary"]["total_in"], 1130000.0)
        self.assertEqual(r["summary"]["total_out"], 515000.0)

    def test_bad_rows_reported(self):
        path = make_xlsx([
            ("15.01.2025", "A", "ok", 100, None, 100),
            ("не дата", "B", "bad date", 100, None, None),
            ("16.01.2025", "C", "not a number", "abc", None, None),
            ("17.01.2025", "D", "both", 50, 50, None),
            ("18.01.2025", "E", "empty amounts", None, None, None),
            ("19.01.2025", "F", "negative", -5, None, None),
        ])
        r = parse_kaspi_excel(path)
        self.assertEqual(r["summary"]["valid"], 1)
        self.assertEqual(sorted(e["row"] for e in r["errors"]), [3, 4, 5, 6, 7])

    def test_balance_mismatch_and_duplicate(self):
        path = make_xlsx([
            ("15.01.2025", "A", "x", 100, None, 100),
            ("16.01.2025", "B", "y", 50, None, 999),
            ("16.01.2025", "B", "y", 50, None, 999),
        ])
        r = parse_kaspi_excel(path)
        self.assertEqual(r["summary"]["valid"], 2)
        self.assertTrue(any("Остаток" in w["error"] for w in r["warnings"]))
        self.assertTrue(any("Дубликат" in w["error"] for w in r["warnings"]))

    def test_missing_columns(self):
        path = make_xlsx([("15.01.2025", "A")], header=("Дата", "Контрагент"))
        r = parse_kaspi_excel(path)
        self.assertTrue(any("Дебет" in e["error"] for e in r["errors"]))


class ClassifierTests(unittest.TestCase):
    def test_schema_for_every_label(self):
        for tx in LABELLED:
            r = classify_transaction(tx)
            self.assertIn(r["category"], CATEGORY_SUBCATEGORIES)
            self.assertTrue(0.0 <= r["confidence"] <= 1.0)
            if r["subcategory"]:
                self.assertIn(r["subcategory"], CATEGORY_SUBCATEGORIES[r["category"]])

    def test_accuracy_on_labelled_data(self):
        ok_cat = ok_sub = 0
        for tx in LABELLED:
            r = classify_transaction(tx)
            ok_cat += r["category"] == tx["expected_category"]
            ok_sub += r["category"] == tx["expected_category"] and r["subcategory"] == tx["expected_subcategory"]
        n = len(LABELLED)
        print(f"\ncategory accuracy {ok_cat}/{n}, subcategory accuracy {ok_sub}/{n}")
        self.assertGreaterEqual(ok_cat / n, 0.95)
        self.assertGreaterEqual(ok_sub / n, 0.90)

    def test_unclear_goes_to_review(self):
        r = classify_transaction({"direction": "out", "counterparty": "", "description": "xyz"})
        self.assertTrue(r["needs_review"])

    def test_validator_rejects_bad_output(self):
        self.assertIsNone(_validate_and_clean({"category": "banana"})["category"])
        r = _validate_and_clean({"category": "income", "subcategory": "Аренда офиса", "confidence": 5})
        self.assertEqual(r["subcategory"], "")  # expense subcategory not allowed for income
        self.assertLessEqual(r["confidence"], 1.0)


class WorkflowTests(unittest.TestCase):
    """upload -> classify -> accept/edit -> saved status"""

    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(app_module.app)
        cid = cls.c.post("/clients/create", data={"name": "Test IP"}).json()["client_id"]
        cls.pid = cls.c.post("/periods/create", data={"client_id": cid, "quarter": "Q1", "year": 2025}).json()["period_id"]

    def test_full_flow(self):
        c, pid = self.c, self.pid
        with open(SAMPLE, "rb") as f:
            up = c.post(f"/period/{pid}/upload-statement", files={"file": ("s.xlsx", f)}).json()
        self.assertTrue(up["ok"])
        self.assertEqual(up["imported"], 8)

        with open(SAMPLE, "rb") as f:  # re-upload: nothing new
            again = c.post(f"/period/{pid}/upload-statement", files={"file": ("s.xlsx", f)}).json()
        self.assertEqual(again["imported"], 0)

        self.assertEqual(c.post(f"/period/{pid}/classify-all").json()["classified"], 8)
        txs = {t["id"]: t for t in app_module.db.get_transactions(pid)}
        self.assertTrue(all(t["llm_suggestion"] for t in txs.values()))

        # bad category / subcategory rejected
        tid = next(iter(txs))
        self.assertEqual(c.post(f"/transaction/{tid}/approve", data={"category": "x"}).status_code, 400)
        self.assertEqual(c.post(f"/transaction/{tid}/approve", data={"category": "income", "subcategory": "Аренда офиса"}).status_code, 400)

        # accept AI as is -> accepted; change category -> edited
        t = txs[tid]
        r = c.post(f"/transaction/{tid}/approve", data={"category": t["llm_suggestion"], "subcategory": t["llm_subcategory"] or ""}).json()
        self.assertEqual(r["review_status"], "accepted")
        other = [i for i in txs if i != tid][0]
        r = c.post(f"/transaction/{other}/approve", data={"category": "personal"}).json()
        self.assertEqual(r["review_status"], "edited" if txs[other]["llm_suggestion"] != "personal" else "accepted")
        self.assertEqual(r["period_status"], "draft")

        # bulk accept confident, then finish the rest by hand
        c.post(f"/period/{pid}/accept-confident")
        for t in app_module.db.get_transactions(pid):
            if not t["approved_by"]:
                c.post(f"/transaction/{t['id']}/approve", data={"category": t["llm_suggestion"], "subcategory": t["llm_subcategory"] or ""})

        final = app_module.db.get_transactions(pid)
        self.assertTrue(all(t["approved_by"] and t["review_status"] in ("accepted", "edited") for t in final))
        self.assertEqual(app_module.db.get_period_with_client(pid)["status"], "reviewed")

        # review page renders
        page = c.get(f"/period/{pid}/review", cookies={app_module.AUTH_COOKIE_NAME: app_module._make_auth_token(app_module.AUTH_EMAIL)})
        self.assertEqual(page.status_code, 200)
        self.assertIn("Проверка операций", page.text)


if __name__ == "__main__":
    unittest.main()

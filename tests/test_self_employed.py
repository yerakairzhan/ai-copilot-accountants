"""
Tests for the self-employed tax regime (US-08 ... US-12).
Run: python -m unittest discover -s tests -v
Uses the fake AI and a temporary database - no API key or network needed.
"""
from modules.risk_engine.rules import analyze_risks
import app as app_module
from fastapi.testclient import TestClient
import pdfplumber
import openpyxl
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "self_employed.sqlite")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["LLM_PROVIDER"] = "fake"


NEW_RISKS = ("monthly_limit_exceeded", "salary_payment")
HEADER = ("Дата", "Контрагент", "Описание операции",
          "Кредит (приход)", "Дебет (расход)", "Остаток")
_counter = [0]


def make_xlsx(rows) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    _counter[0] += 1
    path = os.path.join(_tmp, f"se_{_counter[0]}.xlsx")
    wb.save(path)
    return path


def tx(i, date, amount, direction, desc="Оплата услуг"):
    return {"id": i, "date": date, "amount": amount, "direction": direction,
            "counterparty": "ТОО Альфа", "description": desc,
            "category": None, "approved_by": None}


def new_risk_types(regime, txs):
    return [r["risk_type"] for r in analyze_risks(txs, {}, regime) if r["risk_type"] in NEW_RISKS]


class RegimeFeatureTests(unittest.TestCase):
    """TC-N01 ... TC-N07: regime in the normal workflow"""

    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(app_module.app)
        cls.c.cookies.set(app_module.AUTH_COOKIE_NAME,
                          app_module._make_auth_token(app_module.AUTH_EMAIL))

    def setup_period(self, regime, year, rows, name="Test"):
        cid = self.c.post(
            "/clients/create", data={"name": name, "tax_regime": regime}).json()["client_id"]
        pid = self.c.post(
            "/periods/create", data={"client_id": cid, "quarter": "Q1", "year": year}).json()["period_id"]
        with open(make_xlsx(rows), "rb") as f:
            self.c.post(f"/period/{pid}/upload-statement",
                        files={"file": ("s.xlsx", f)})
        return cid, pid

    def approve_all(self, pid):
        self.c.post(f"/period/{pid}/classify-all")
        self.c.post(f"/period/{pid}/accept-confident")

    def test_n01_create_self_employed_client(self):
        r = self.c.post("/clients/create",
                        data={"name": "Self Client", "tax_regime": "SELF"})
        self.assertEqual(r.status_code, 200)
        conn = app_module.db.get_connection()
        regime = conn.execute("SELECT tax_regime FROM clients WHERE id = ?", (r.json()[
                              "client_id"],)).fetchone()[0]
        conn.close()
        self.assertEqual(regime, "SELF")
        self.assertIn("Самозанятый", self.c.get("/").text)

    def test_n02_unknown_regime_rejected(self):
        r = self.c.post("/clients/create",
                        data={"name": "X", "tax_regime": "ZZZ"})
        self.assertEqual(r.status_code, 400)

    def test_n03_self_employed_tax_is_4_percent(self):
        _, pid = self.setup_period(
            "SELF", 2026, [("10.01.2026", "ТОО Альфа", "Оплата услуг", 1000000, None, None)])
        self.approve_all(pid)
        summary = app_module.db.calculate_tax_summary(
            pid, app_module.TAX_RATES["SELF"])
        self.assertEqual(summary["tax"], 40000.0)
        page = self.c.get(f"/period/{pid}").text
        self.assertIn("Самозанятый 4%", page)
        self.assertIn("Налог (Самозанятый) 4%", page)
        self.assertIn("40 000", page)

    def test_n04_usn_tax_still_3_percent(self):
        _, pid = self.setup_period(
            "USN", 2026, [("10.01.2026", "ТОО Альфа", "Оплата услуг", 1000000, None, None)])
        self.approve_all(pid)
        summary = app_module.db.calculate_tax_summary(
            pid, app_module.TAX_RATES["USN"])
        self.assertEqual(summary["tax"], 30000.0)
        page = self.c.get(f"/period/{pid}").text
        self.assertIn("УСН 3%", page)
        self.assertIn("30 000", page)

    def test_n05_explanations_in_three_languages(self):
        _, pid = self.setup_period("SELF", 2026, [
            ("05.01.2026", "ТОО А", "Оплата", 700000, None, None),
            ("20.01.2026", "ТОО Б", "Оплата", 700000, None, None),
            ("12.02.2026", "Иванов", "Зарплата за январь", None, 80000, None),
        ])
        self.c.post(f"/period/{pid}/analyze-risks")
        found = [r for r in app_module.db.get_risks(
            pid) if r["risk_type"] in NEW_RISKS]
        self.assertEqual({r["risk_type"] for r in found}, set(NEW_RISKS))
        for r in found:
            text = self.c.get(f"/risk/{r['id']}/explain").json()["explanation"]
            for lang in ("RU:", "KZ:", "EN:"):
                self.assertIn(lang, text, r["risk_type"])

    def test_n06_pdf_shows_regime(self):
        _, pid = self.setup_period(
            "SELF", 2026, [("10.01.2026", "ТОО Альфа", "Оплата услуг", 1000000, None, None)])
        self.approve_all(pid)
        r = self.c.get(f"/period/{pid}/export-pdf")
        self.assertEqual(r.status_code, 200)
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = " ".join(page.extract_text() or "" for page in pdf.pages)
        self.assertIn("Self-employed", text)
        self.assertIn("tax (4%)", text)

    def test_n07_new_rules_do_not_run_for_usn(self):
        _, pid = self.setup_period("USN", 2026, [
            ("05.01.2026", "ТОО А", "Оплата", 700000, None, None),
            ("20.01.2026", "ТОО Б", "Оплата", 700000, None, None),
            ("12.02.2026", "Иванов", "Зарплата за январь", None, 80000, None),
        ])
        self.c.post(f"/period/{pid}/analyze-risks")
        risks = app_module.db.get_risks(pid)
        self.assertEqual([r for r in risks if r["risk_type"] in NEW_RISKS], [])
        self.assertTrue(risks)  # standard rules still work


class ReferenceScenarioTests(unittest.TestCase):
    """SC-01 ... SC-10: reference scenarios for the new rules (US-12)"""

    def test_sc01_income_equal_to_limit(self):
        self.assertEqual(new_risk_types(
            "SELF", [tx(1, "2026-01-10", 1297500, "in")]), [])

    def test_sc02_income_above_limit_by_one(self):
        self.assertEqual(new_risk_types(
            "SELF", [tx(1, "2026-01-10", 1297501, "in")]), ["monthly_limit_exceeded"])

    def test_sc03_two_payments_cross_limit(self):
        txs = [tx(1, "2026-01-05", 700000, "in"),
               tx(2, "2026-01-20", 700000, "in")]
        risks = analyze_risks(txs, {}, "SELF")
        hits = [r for r in risks if r["risk_type"] == "monthly_limit_exceeded"]
        self.assertEqual(len(hits), 1)
        # the payment that crossed the limit
        self.assertEqual(hits[0]["transaction_id"], 2)

    def test_sc04_limit_is_per_month(self):
        txs = [tx(1, "2026-01-05", 600000, "in"), tx(2, "2026-01-20", 600000, "in"),
               tx(3, "2026-02-05", 600000, "in"), tx(4, "2026-02-20", 600000, "in")]
        self.assertEqual(new_risk_types("SELF", txs), [])

    def test_sc05_2025_income_equal_to_limit(self):
        self.assertEqual(new_risk_types(
            "SELF", [tx(1, "2025-01-10", 1179600, "in")]), [])

    def test_sc06_2025_limit_is_lower(self):
        self.assertEqual(new_risk_types(
            "SELF", [tx(1, "2025-01-10", 1200000, "in")]), ["monthly_limit_exceeded"])

    def test_sc07_same_amount_ok_in_2026(self):
        self.assertEqual(new_risk_types(
            "SELF", [tx(1, "2026-01-10", 1200000, "in")]), [])

    def test_sc08_outgoing_salary_flagged(self):
        txs = [tx(1, "2026-02-12", 80000, "out", "Зарплата за январь")]
        self.assertEqual(new_risk_types("SELF", txs), ["salary_payment"])

    def test_sc09_incoming_salary_and_rent_not_flagged(self):
        txs = [tx(1, "2026-02-12", 80000, "in", "Зарплата за январь"),
               tx(2, "2026-02-13", 150000, "out", "Аренда офиса")]
        self.assertEqual(new_risk_types("SELF", txs), [])

    def test_sc10_one_flag_per_month(self):
        txs = [tx(1, "2026-01-10", 1300000, "in"), tx(2, "2026-02-10", 1300000, "in"),
               tx(3, "2026-03-10", 1300000, "in")]
        self.assertEqual(new_risk_types("SELF", txs), [
                         "monthly_limit_exceeded"] * 3)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Stub gspread and google.oauth2 before importing
sys.modules.setdefault("gspread", MagicMock())
sys.modules.setdefault("google", MagicMock())
sys.modules.setdefault("google.oauth2", MagicMock())
sys.modules.setdefault("google.oauth2.service_account", MagicMock())

from sheets import SheetsClient, _col_letter_to_index


TABLE_COLUMNS = {
    "A": "תאריך",
    "B": "שעה",
    "C": "תיאור",
    "D": "קלוריות",
    "E": "חלבון",
    "F": "סהכ קלוריות יומי",
    "G": "סהכ חלבון יומי",
}


@pytest.fixture
def sheets_client():
    with patch("sheets.Credentials") as mock_creds_cls, \
         patch("sheets.gspread") as mock_gspread:
        mock_creds = MagicMock()
        mock_creds_cls.from_service_account_file.return_value = mock_creds
        mock_gc = MagicMock()
        mock_gspread.authorize.return_value = mock_gc

        client = SheetsClient(
            credentials_file="config/google_credentials.json",
            sheet_id="test_sheet_id",
            tab_name="food_log",
            table_columns=TABLE_COLUMNS,
        )
        yield client, mock_gc


class TestColLetterToIndex:
    def test_a(self):
        assert _col_letter_to_index("A") == 0

    def test_f(self):
        assert _col_letter_to_index("F") == 5

    def test_lowercase(self):
        assert _col_letter_to_index("c") == 2


class TestSheetsClientInit:
    def test_total_cols(self, sheets_client):
        client, _ = sheets_client
        assert client.total_cols == 7  # A through G


class TestBuildRow:
    def test_places_values_at_correct_positions(self, sheets_client):
        client, _ = sheets_client
        row = client._build_row({
            "תאריך": "05/05/2026",
            "שעה": "14:30",
            "תיאור": "שניצל",
            "קלוריות": "400",
            "חלבון": "30",
            "סהכ קלוריות יומי": "1200",
            "סהכ חלבון יומי": "80",
        })
        assert row[0] == "05/05/2026"  # A
        assert row[1] == "14:30"       # B
        assert row[2] == "שניצל"       # C
        assert row[3] == "400"         # D
        assert row[4] == "30"          # E
        assert row[5] == "1200"        # F
        assert row[6] == "80"          # G

    def test_missing_values_are_empty(self, sheets_client):
        client, _ = sheets_client
        row = client._build_row({"תאריך": "05/05/2026"})
        assert row[0] == "05/05/2026"
        assert row[1] == ""
        assert row[2] == ""


class TestAppendFoodEntry:
    def test_appends_row_and_returns_row_number(self, sheets_client):
        client, mock_gc = sheets_client
        mock_spreadsheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_ws = MagicMock()
        mock_spreadsheet.worksheet.return_value = mock_ws
        mock_ws.append_row.return_value = {
            "updates": {"updatedRange": "food_log!A15:F15"}
        }

        row_num = client.append_food_entry(
            date_str="05/05/2026",
            time_str="14:30",
            description="שניצל וסלט",
            calories=400,
            protein=30,
            daily_total_cal=1200,
            daily_total_protein=80,
        )

        assert row_num == 15
        mock_ws.append_row.assert_called_once()
        row_arg = mock_ws.append_row.call_args[0][0]
        assert row_arg[0] == "05/05/2026"
        assert row_arg[2] == "שניצל וסלט"
        assert row_arg[3] == "400"
        assert row_arg[4] == "30"


class TestGetAllEntries:
    def test_skips_header_row(self, sheets_client):
        client, mock_gc = sheets_client
        mock_spreadsheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_ws = MagicMock()
        mock_spreadsheet.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [
            ["תאריך", "שעה", "תיאור", "קלוריות", "חלבון", "סהכ קלוריות יומי", "סהכ חלבון יומי"],
            ["05/05/2026", "14:30", "שניצל", "400", "30", "400", "30"],
        ]

        entries = client.get_all_entries()
        assert len(entries) == 1
        assert entries[0]["תיאור"] == "שניצל"
        assert entries[0]["קלוריות"] == "400"


class TestGetEntriesByDates:
    def test_filters_by_date(self, sheets_client):
        client, mock_gc = sheets_client
        mock_spreadsheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_ws = MagicMock()
        mock_spreadsheet.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [
            ["תאריך", "שעה", "תיאור", "קלוריות", "חלבון", "סהכ קלוריות יומי", "סהכ חלבון יומי"],
            ["05/05/2026", "14:30", "שניצל", "400", "30", "400", "30"],
            ["06/05/2026", "10:00", "קפה", "50", "3", "50", "3"],
            ["05/05/2026", "18:00", "סלט", "100", "5", "500", "35"],
        ]

        entries = client.get_entries_by_dates(["05/05/2026"])
        assert len(entries) == 2
        assert entries[0]["תיאור"] == "שניצל"
        assert entries[1]["תיאור"] == "סלט"

    def test_multiple_dates(self, sheets_client):
        client, mock_gc = sheets_client
        mock_spreadsheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_ws = MagicMock()
        mock_spreadsheet.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [
            ["תאריך", "שעה", "תיאור", "קלוריות", "חלבון", "סהכ קלוריות יומי", "סהכ חלבון יומי"],
            ["05/05/2026", "14:30", "שניצל", "400", "30", "400", "30"],
            ["06/05/2026", "10:00", "קפה", "50", "3", "50", "3"],
        ]

        entries = client.get_entries_by_dates(["05/05/2026", "06/05/2026"])
        assert len(entries) == 2

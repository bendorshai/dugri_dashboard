from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _col_letter_to_index(letter: str) -> int:
    return ord(letter.upper()) - ord("A")


class SheetsClient:
    def __init__(
        self,
        credentials_file: str,
        sheet_id: str,
        tab_name: str,
        table_columns: dict[str, str],
    ):
        creds = Credentials.from_service_account_file(credentials_file, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        self.sheet_id = sheet_id
        self.tab_name = tab_name
        self.table_columns = table_columns
        self.total_cols = max(_col_letter_to_index(c) for c in table_columns) + 1

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        return self.gc.open_by_key(self.sheet_id)

    def _get_worksheet(self) -> gspread.Worksheet:
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet(self.tab_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=self.tab_name, rows=1000, cols=self.total_cols,
            )
            header = self._build_row_by_headers()
            ws.append_row(header, value_input_option="USER_ENTERED", table_range="A1")
            ws.format("1", {"textFormat": {"bold": True}})
            return ws

    def _build_row_by_headers(self) -> list[str]:
        row = [""] * self.total_cols
        for col_letter, header_name in self.table_columns.items():
            row[_col_letter_to_index(col_letter)] = header_name
        return row

    def _build_row(self, values: dict[str, str]) -> list[str]:
        col_name_to_index = {
            name: _col_letter_to_index(letter)
            for letter, name in self.table_columns.items()
        }
        row = [""] * self.total_cols
        for col_name, value in values.items():
            if col_name in col_name_to_index:
                row[col_name_to_index[col_name]] = value
        return row

    def _col_letter_for(self, col_name: str) -> str | None:
        for letter, name in self.table_columns.items():
            if name == col_name:
                return letter
        return None

    def append_food_entry(
        self,
        date_str: str,
        time_str: str,
        description: str,
        calories: int,
        protein: int,
        daily_total_cal: int = 0,
        daily_total_protein: int = 0,
    ) -> int:
        ws = self._get_worksheet()
        values = {
            "תאריך": date_str,
            "שעה": time_str,
            "תיאור": description,
            "קלוריות": str(calories),
            "חלבון": str(protein),
            "סהכ קלוריות יומי": str(daily_total_cal) if daily_total_cal else "",
            "סהכ חלבון יומי": str(daily_total_protein) if daily_total_protein else "",
        }
        row = self._build_row(values)
        result = ws.append_row(row, value_input_option="USER_ENTERED", table_range="A1")
        updated_range = result.get("updates", {}).get("updatedRange", "")
        if updated_range and "!" in updated_range:
            cell_ref = updated_range.split("!")[-1].split(":")[0]
            row_digits = "".join(c for c in cell_ref if c.isdigit())
            if row_digits:
                return int(row_digits)
        return len(ws.get_all_values())

    def update_cell_by_name(self, row_number: int, col_name: str, value: str) -> None:
        col_letter = self._col_letter_for(col_name)
        if col_letter is None:
            return
        ws = self._get_worksheet()
        ws.update_acell(f"{col_letter}{row_number}", value)

    def delete_row(self, row_number: int) -> None:
        ws = self._get_worksheet()
        empty_row = [""] * self.total_cols
        ws.update(f"A{row_number}", [empty_row], value_input_option="RAW")

    def get_entry_data(self, row_number: int) -> dict[str, str]:
        ws = self._get_worksheet()
        row_values = ws.row_values(row_number)
        col_index_to_name = {
            _col_letter_to_index(letter): name
            for letter, name in self.table_columns.items()
        }
        result = {}
        for idx, val in enumerate(row_values):
            if idx in col_index_to_name:
                result[col_index_to_name[idx]] = val
        return result

    def get_all_entries(self) -> list[dict[str, str]]:
        ws = self._get_worksheet()
        all_rows = ws.get_all_values()
        if len(all_rows) <= 1:
            return []

        col_index_to_name = {
            _col_letter_to_index(letter): name
            for letter, name in self.table_columns.items()
        }
        entries = []
        for row in all_rows[1:]:
            entry = {}
            for idx, val in enumerate(row):
                if idx in col_index_to_name:
                    entry[col_index_to_name[idx]] = val
            if entry.get("תיאור") or entry.get("קלוריות"):
                entries.append(entry)
        return entries

import os
import datetime
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet(tab_name):
    """Return a worksheet object for the given tab name."""
    creds_file = os.path.join(os.path.dirname(__file__), os.getenv("GOOGLE_CREDENTIALS_FILE"))
    creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
    return spreadsheet.worksheet(tab_name)


def append_rows(tab_name, rows, value_input_option="USER_ENTERED"):
    """Append a list of row-lists to the given tab."""
    ws = get_sheet(tab_name)
    ws.append_rows(rows, value_input_option=value_input_option)
    return len(rows)


def update_cell(tab_name, cell, value):
    """Update a single cell (e.g. 'G1') in the given tab."""
    ws = get_sheet(tab_name)
    ws.update_acell(cell, value)


def clear_data_rows(tab_name):
    """Clear all data rows in a tab, keeping the header row intact."""
    ws = get_sheet(tab_name)
    row_count = ws.row_count
    if row_count > 1:
        # Delete rows 2 through end, leaving header in row 1
        ws.delete_rows(2, row_count)
    return row_count - 1  # number of rows cleared


def read_all(tab_name):
    """Read all rows from a tab, returned as list of dicts keyed by header."""
    ws = get_sheet(tab_name)
    rows = ws.get_all_values()
    if not rows or len(rows) < 2:
        return []
    headers = rows[0]
    # Deduplicate empty headers to avoid gspread error
    seen = {}
    clean_headers = []
    for h in headers:
        if not h:
            seen[""] = seen.get("", 0) + 1
            clean_headers.append(f"_blank_{seen['']}")
        else:
            clean_headers.append(h)
    return [dict(zip(clean_headers, row)) for row in rows[1:]]


def delete_old_rows(tab_name, date_col_index=0, days=7):
    """Delete rows with a Date value older than `days` days ago.

    Keeps the header row and any rows within the retention window.
    Returns the number of rows deleted.
    """
    ws = get_sheet(tab_name)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return 0

    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    header = rows[0]
    keep = []
    deleted = 0
    for row in rows[1:]:
        row_date = row[date_col_index] if date_col_index < len(row) else ""
        if row_date >= cutoff:
            keep.append(row)
        else:
            deleted += 1

    if deleted == 0:
        return 0

    # Rewrite: header + kept rows
    ws.clear()
    ws.update([header] + keep, value_input_option="RAW")
    return deleted


def get_existing_values(tab_name, col_index):
    """Return a set of values from a specific column (0-indexed) in the tab."""
    ws = get_sheet(tab_name)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return set()
    return {row[col_index] for row in rows[1:] if col_index < len(row)}

import os
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


def append_rows(tab_name, rows):
    """Append a list of row-lists to the given tab."""
    ws = get_sheet(tab_name)
    ws.append_rows(rows, value_input_option="USER_ENTERED")
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

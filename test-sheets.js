const { writeToSheet, readFromSheet, appendToSheet } = require("./sheets");

// Replace with your actual spreadsheet ID from the Google Sheet URL:
// https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
const SPREADSHEET_ID = process.argv[2];

if (!SPREADSHEET_ID) {
  console.error("Usage: node test-sheets.js <SPREADSHEET_ID>");
  console.error(
    "\n1. Create a Google Sheet at https://sheets.google.com"
  );
  console.error(
    "2. Share it with: jrm-sheets@jrm-social.iam.gserviceaccount.com (Editor)"
  );
  console.error("3. Copy the spreadsheet ID from the URL and pass it as an argument");
  process.exit(1);
}

async function main() {
  console.log("Testing Google Sheets integration...\n");

  // Step 1: Write header row
  console.log("1. Writing header row...");
  await writeToSheet(SPREADSHEET_ID, "Sheet1!A1:D1", [
    ["Title", "Platform", "Status", "Date"],
  ]);
  console.log("   Header written.\n");

  // Step 2: Append sample rows
  console.log("2. Appending sample content rows...");
  await appendToSheet(SPREADSHEET_ID, "Sheet1!A:D", [
    ["How AI Changes Content Creation", "Twitter", "Draft", "2026-03-31"],
    ["10 Tips for Better Reels", "Instagram", "Scheduled", "2026-04-01"],
    ["Building a Content Pipeline", "LinkedIn", "Published", "2026-03-30"],
  ]);
  console.log("   3 rows appended.\n");

  // Step 3: Read back data
  console.log("3. Reading back data...");
  const data = await readFromSheet(SPREADSHEET_ID, "Sheet1!A1:D10");
  console.log("   Data in sheet:");
  data.forEach((row) => console.log("   ", row.join(" | ")));

  console.log("\nGoogle Sheets integration is working!");
}

main().catch((err) => {
  console.error("Error:", err.message);
  process.exit(1);
});

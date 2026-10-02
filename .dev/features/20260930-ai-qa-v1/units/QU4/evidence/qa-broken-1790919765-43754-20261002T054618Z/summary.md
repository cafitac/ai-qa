# qa-broken-1790919765-43754-20261002T054618Z

State: COMPLETED

backend: no scenario file
Redaction: scanned attempt artifacts

| Scenario | Status | Summary |
| --- | --- | --- |
| frontend/seed-notes-listed | PASSED | Opened the start URL and waited 3 seconds for the Notes list to load. The page shows the 'Preview notes' h1 heading, and the Notes list has 2 items: 'Try adding a note.' and 'Welcome to preview-hub!'. All expectations were met. The page logged 1 console error. I couldn't read it because the console-messages tool was denied (it needs approval and this session has no way to grant it). Saved final.png. |
| frontend/add-note-shows-first | FAILED | I typed the unique note 'QA note 2026-10-02T05:47:30.123Z unique' and clicked Add note. The app showed an alert: 'Could not confirm the note was saved. Check the API connection and reload before retrying.' The new note did not appear in the list. The list still had only 'Try adding a note.' and 'Welcome to preview-hub!'. The page had 2 console errors that I couldn't read: the console and network tools were blocked by permissions. Screenshot saved as final.png. |

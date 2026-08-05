"""Named constants for issues.status, shared by ingest/analyst/admin.

Historical DB rows may still carry EXTRACTED from before ingest.ingest_issue
started writing pdf_path/status atomically with the ideas insert; it remains a
valid value to read but is no longer written.
"""

PENDING = "pending"
DOWNLOADING = "downloading"
DOWNLOAD_FAILED = "download_failed"
EXTRACT_FAILED = "extract_failed"
EXTRACTED = "extracted"
PARSED = "parsed"
ANALYZED = "analyzed"

DONE = (PARSED, ANALYZED)
FAILED = (DOWNLOAD_FAILED, EXTRACT_FAILED)

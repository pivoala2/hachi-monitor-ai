import os
import re
import glob
from datetime import datetime, timedelta

SUMMARY_FILE = "/app/summary.txt"
ARCHIVE_DIR = "/app/archive"

IMAGE_DIR = "/images"
IMAGE_RETENTION_DAYS = 3

SHOT_DIR = "/app/shared_summary/camera_shots"
SHOT_RETENTION_DAYS = 3

def rotate_log():
    if not os.path.exists(SUMMARY_FILE):
        return
    cutoff = datetime.now() - timedelta(days=30)
    keep_lines = []
    archive_lines = []
    with open(SUMMARY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r"(\d{14})", line)
            if not match:
                continue
            log_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            if log_time >= cutoff:
                keep_lines.append(line)
            else:
                archive_lines.append(line)
    if archive_lines:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_file = os.path.join(
            ARCHIVE_DIR,
            f"summary_{datetime.now().strftime('%Y%m')}.log"
        )
        with open(archive_file, "a", encoding="utf-8") as f:
            f.writelines(archive_lines)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.writelines(keep_lines)

def rotate_images():
    cutoff = datetime.now() - timedelta(days=IMAGE_RETENTION_DAYS)
    deleted = 0
    for ext in ["**/*.jpg", "**/*.mp4"]:
        files = glob.glob(os.path.join(IMAGE_DIR, ext), recursive=True)
        for f in files:
            m = re.search(r'(\d{14})', os.path.basename(f))
            if m:
                file_time = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
            else:
                file_time = datetime.fromtimestamp(os.path.getmtime(f))
            if file_time < cutoff:
                os.remove(f)
                deleted += 1
    print(f"[reolink] Deleted {deleted} old files (jpg + mp4)")

def rotate_shots():
    if not os.path.exists(SHOT_DIR):
        return
    cutoff = datetime.now() - timedelta(days=SHOT_RETENTION_DAYS)
    files = glob.glob(os.path.join(SHOT_DIR, "*.jpg"))
    deleted = 0
    for f in files:
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        if mtime < cutoff:
            os.remove(f)
            deleted += 1
    print(f"[shots] Deleted {deleted} old snapshots")

if __name__ == "__main__":
    rotate_log()
    rotate_images()
    rotate_shots()

# Direct CTX geotiff downloader — no browser, no scraping.
#
# The volume ID (mrox_XXXX) is taken directly from the PDSVolId field
# in the footprints shapefile, so no ASU viewer page scrape is needed.
# Downloads are streamed via requests so large files don't fill RAM.
#
# Replaces ctx_downloader_rqc.py
# Written for Impact Flux Project, June 2026

import os
import time
import requests

# ASU Mars image stream base URL
_BASE = 'https://image.mars.asu.edu/stream/'

def build_url(ctx_id, vol_id):
    """Construct the direct geotiff download URL for a CTX image.

    Args:
        ctx_id: CTX ProductId, e.g. 'P01_001378_1875_XI_07N175W'
        vol_id: PDSVolId from footprints shapefile, e.g. 'MROX_0042'
                (case-insensitive; stored uppercase in shapefile)
    """
    vol_id_lower = vol_id.lower()
    return (f'{_BASE}{ctx_id}.tiff'
            f'?image=/mars/images/ctx/{vol_id_lower}/prj_full/{ctx_id}.tiff')


def download_ctx(ctx_id, vol_id, dest_dir, retries=3, backoff=30):
    """Download a CTX geotiff to dest_dir/{ctx_id}.tiff.

    Returns True on success, False if all retries are exhausted.

    Args:
        ctx_id:    CTX ProductId string
        vol_id:    PDSVolId string from the footprints shapefile
        dest_dir:  Directory to write the file into
        retries:   Number of attempts before giving up
        backoff:   Seconds to wait between retries (doubles each attempt)
    """
    dest_path = os.path.join(dest_dir, ctx_id + '.tiff')

    if os.path.exists(dest_path):
        return True  # already on disk

    url = build_url(ctx_id, vol_id)
    wait = backoff

    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp_path = dest_path + '.part'
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            os.rename(tmp_path, dest_path)
            return True
        except Exception as e:
            print(f'  [attempt {attempt}/{retries}] {ctx_id} failed: {e}')
            if attempt < retries:
                time.sleep(wait)
                wait *= 2

    print(f'  FAILED after {retries} attempts: {ctx_id}')
    return False

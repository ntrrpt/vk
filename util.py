from bs4 import BeautifulSoup

from datetime import datetime
from time import sleep
from loguru import logger as log
from pathlib import Path
import requests
import re
import os
import unicodedata

from yarl import URL
from email.utils import parsedate_to_datetime
from aiohttp_socks import ProxyConnector
import asyncio
import aiofiles
import aiohttp
from tqdm import tqdm


async def dw_album(
    img_dict, dest_folder, proxy=None, concurrency=5, max_retries=5, retry_delay=10
):
    Path(dest_folder).mkdir(parents=True, exist_ok=True)

    connector = ProxyConnector.from_url(proxy) if proxy else None
    sem = asyncio.Semaphore(concurrency)
    all_len = len(str(len(img_dict)))

    async with aiohttp.ClientSession(connector=connector) as session:
        pbar = tqdm(
            total=len(img_dict),
            unit="img",
            ncols=100,
            miniters=1,
            leave=False,
        )
        try:
            tasks = [
                _dw_photo(
                    img,
                    all_len,
                    session,
                    dest_folder,
                    sem,
                    pbar,
                    max_retries,
                    retry_delay,
                )
                for img in img_dict
            ]
            await asyncio.gather(*tasks)
        finally:
            pbar.close()


async def _dw_photo(
    img, all_len, session, dest_folder, sem, pbar, max_retries, retry_delay
):
    # 0000_xxx, 0001_yyy
    filename = f"{img['index']:0{all_len}d}_{URL(img['url']).name}"
    dest_path = Path(dest_folder) / filename

    if dest_path.is_file():
        # log.trace(f"[skip] {dest_path}")
        pbar.update(1)
        return

    async with sem:
        for attempt in range(1, max_retries + 1):
            try:
                async with session.get(img["url"]) as r:
                    if r.status == 404:
                        log.error(f"{img['index']} not found")
                        return

                    r.raise_for_status()
                    async with aiofiles.open(dest_path, mode="wb") as f:
                        await f.write(await r.read())

                    if img.get("date"):
                        ts = img["date"]
                    elif "Last-Modified" in r.headers:
                        lm = r.headers["Last-Modified"]
                        dt = parsedate_to_datetime(lm)
                        ts = dt.timestamp()
                    else:
                        log.warning(f"ts pmo: {img['url']}")

                    if ts:
                        os.utime(dest_path, (ts, ts))

                    if img.get("text"):
                        desc_fn = Path(dest_folder) / f"{filename}_description.txt"
                        write(desc_fn, img["text"])
                        if ts:
                            os.utime(desc_fn, (ts, ts))

                    # log.trace(dest_path)
                    pbar.update(1)
                    return

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning(f"{img['index']} (attempt {attempt}/{max_retries}): {e}")

                if attempt >= max_retries:
                    log.error(f"failed {img['index']!r} after {max_retries} tries")
                    return

                await asyncio.sleep(retry_delay)

            except Exception as e:
                log.opt(exception=True).error(f"{img['index']}: {e}")
                return


def dt_now(fmt: str = "%y-%m-%d %H_%M_%S"):
    now = datetime.now()
    return now.strftime(fmt)


def ts_fmt(timestamp: int, fmt: str = "%Y-%m-%d %H:%M:%S"):
    fts = datetime.fromtimestamp(timestamp)
    return fts.strftime(fmt)


def sizeof_fmt(num):
    for x in ["bytes", "KB", "MB", "GB"]:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0
    return "%3.1f %s" % (num, "TB")


def html_fmt(path):
    html = open(path, encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    fmt_html = soup.prettify()

    with open(path, "w", encoding="utf-8") as f:
        f.write(fmt_html)


def str_toplus(value) -> str:
    return str(value).lstrip("-")


def str_tominus(value) -> str:
    s = str(value).lstrip("-")
    return "-" + s if s else s


def str_cut(string, letters, postfix="..."):
    return string[:letters] + (string[letters:] and postfix)


def esc(name: str, replacement: str = "_") -> str:
    allowed_brackets = "()[]{}"
    r = []

    for ch in name:
        cat = unicodedata.category(ch)

        if ch in '<>:"/\\|?*' or ch == "\x00":
            r.append(replacement)
        elif ch in allowed_brackets:
            r.append(ch)
        elif cat.startswith(("P", "S", "C")):
            r.append(replacement)
        else:
            r.append(ch)

    r = "".join(r)
    r = r.rstrip(" .")
    r = re.sub(r"_+", "_", r)

    return r[:255]


def float_fmt(number: int, digits: int):
    return f"{number:.{digits}f}"


def stamp_fmt(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%H:%M:%S %d/%m/%Y")


def append(path: Path | str, data: str, end: str = "\n"):
    path = Path(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(data + end)


def write(path: Path | str, data: str, end: str = "\n"):
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data + end)


def delete(path: Path | str):
    path = Path(path)
    rem_file = Path(path)
    rem_file.unlink(missing_ok=True)
    log.trace(f"{path} deleted")


def expand_ranges(s):
    # "1-5,8,10-12" => 1,2,3,4,5,8,10,11,12
    def replace_range(match):
        start, end = map(int, match.group().split("-"))
        return ",".join(map(str, range(start, end + 1)))

    return re.sub(r"\d+-\d+", replace_range, s)


# TODEL
def rqst_str(url, retries=5, headers={"Accept-Encoding": "identity"}):
    while retries:
        try:
            with requests.get(url, headers) as request:
                if request:
                    return request.content
                return False
        except:
            sleep(5)
            retries -= 1


def check_ffmpeg():
    import subprocess as sp

    try:
        r = sp.run(["ffmpeg", "-version"], stdout=sp.PIPE, stderr=sp.PIPE)
        return r.returncode == 0
    except FileNotFoundError:
        return False
